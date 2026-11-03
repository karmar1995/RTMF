import base64
import json
import os
import re
import subprocess
from urllib.parse import urlparse
from typing import Iterable, List
from types import SimpleNamespace

from services.simulators_repository.core.abstract_image_build_worker import (
    AbstractImageBuildWorker,
    BuildRequest,
    BuildResult,
    BuildStatus
)
from services.simulators_repository.build_worker.details.harbor_client import get_manifest_digest
from services.simulators_repository.build_worker.details.zip_safety import unzip_bytes
from services.simulators_repository.build_worker.details.dockerfile_builder import DockerfileBuilder
from services.simulators_repository.build_worker.details.dockerfile_director import DockerfileDirector, BaseImageCatalog
from services.simulators_repository.build_worker.details.request_adapter import parseRequest


_ALLOWED_TAG_RE = re.compile(r"[^a-z0-9_.-]+")


def createWorker(config):
    return BuildKitImageBuildWorker(config)


class BuildKitImageBuildWorker(AbstractImageBuildWorker):
    def __init__(self, config):
        self._config = SimpleNamespace(**config)
        self._buildProc = None
        self._buildLogFile = None
        self._buildId = None
        self._imageRef = None
        self._imageRepo = None
        self._tags = None
        self._imageDigest = None
        self._failFastException = None

    def submit_build(self, request: BuildRequest) -> str:
        self._buildId = request.build_id
        try:
            workspace = self._prepare_workspace(request)
            logs_path = os.path.join(workspace, "build.log")
            self._imageRepo, self._tags = self._build_and_push(workspace, request, logs_path)
        except Exception as e:
            self._failFastException = e
        return self._buildId

    def get_build_status(self, build_id: str) -> BuildResult:
        if build_id != self._buildId:
            raise RuntimeError(f"Requested status of other worker's build! Expected: {self._buildId}, got: {build_id}")

        status = self._get_build_status_based_on_build_proc()

        if status == BuildStatus.SUCCEEDED and self._tags:
            self._imageDigest = get_manifest_digest(
                registry=self._config.harbor_registry,
                project=self._config.harbor_project,
                repository=self._imageRepo,
                tag=self._tags[0],
                username=self._config.harbor_username,
                password=self._config.harbor_password,
            )

        result = BuildResult(build_id = self._buildId,
                             status=status,
                             image_ref=self._imageRef,
                             image_digest=self._imageDigest,
                             image_tags=self._tags,
                             logs='',
                             error=str(self._failFastException))
        return result

    def _get_build_status_based_on_build_proc(self):
        if self._failFastException is not None:
            return BuildStatus.FAILED
        retCode = self._buildProc.poll()
        if retCode is None:
            status = BuildStatus.RUNNING
        elif retCode == 0:
            #TODO: Analyze logs to make sure that it's actually success (for example, authorization error fails the build but process exits with 0)
            status = BuildStatus.SUCCEEDED
        else:
            status = BuildStatus.FAILED
        return status

    def cancel_build(self, build_id: str) -> bool:
        return False

    def _prepare_workspace(self, request: BuildRequest) -> str:
        # Build Dockerfile before proceed to ensure the request can be parsed
        dockerfile_contents = self._generate_dockerfile(request)
        build_id = request.build_id
        workspace = os.path.join(self._workspace_root(), "builds", build_id)
        os.makedirs(workspace)

        zip_path = os.path.join(workspace, "upload.zip")
        with open(zip_path, "wb") as zip_file:
            zip_file.write(request.zip_bytes)

        sim_dir = os.path.join(workspace, "sim")
        unzip_bytes(request.zip_bytes, sim_dir)

        dockerfile_path = os.path.join(workspace, "Dockerfile")
        with open(dockerfile_path, "w", encoding="utf-8") as dockerfile:
            dockerfile.write(dockerfile_contents)

        return workspace

    def _generate_dockerfile(self, request: BuildRequest) -> str:
        builder = DockerfileBuilder()
        director = DockerfileDirector(builder, self._base_image_catalog())
        return director.render(parseRequest(request))

    def _build_and_push(
        self, workspace: str, request: BuildRequest, logs_path: str
    ) -> tuple[str, List[str]]:
        model_name = _sanitize_name(request.model_name)
        version_tag = _sanitize_name(f"v-{request.version_id}")
        build_spec = request.build_spec or {}
        tag = _normalize_tags([], version_tag)[0].strip()

        if len(tag) == 0:
            raise RuntimeError("No tag to push!")

        image_repo = model_name
        image_base = (
            f"{_config_value(self._config.harbor_registry)}/"
            f"{_config_value(self._config.harbor_project)}/"
            f"{image_repo}"
        )
        platform = _buildkit_platform_value(build_spec) or self._buildkit_platform()

        docker_config_dir = self._write_docker_config(workspace)

        base_cmd = [
            "buildctl",
            "--addr",
            self._buildkit_addr(),
            "build",
            "--frontend",
            "dockerfile.v0",
            "--local",
            f"context={workspace}",
            "--local",
            f"dockerfile={workspace}",
            "--opt",
            f"platform={platform}",
        ]

        # TODO: Adjust registry insecure and http flags based on the config
        common_output_suffix = "push=true,registry.insecure=true,registry.http=true"

        image_ref = f"{image_base}:{tag}"
        cmd = base_cmd + [
                "--output",
                f"type=image,name={image_ref},{common_output_suffix}",
            ]

        self._buildLogFile = open(logs_path, "a", encoding="utf-8")
        self._buildLogFile.write(f"Executing: {cmd}\n")
        self._buildLogFile.flush()
        self._buildProc = subprocess.Popen(
            cmd,
            stdout=self._buildLogFile,
            stderr=subprocess.STDOUT,
            env={**os.environ.copy(), "DOCKER_CONFIG": docker_config_dir},
        )
        self._imageRef = image_ref
        return image_repo, [tag]

    def _base_image_catalog(self) -> BaseImageCatalog:
        return BaseImageCatalog(
            python_prefix=self._qualify_prefix(_config_value(
                getattr(self._config, "base_python_image_prefix", None)
            )),
            java_prefix=self._qualify_prefix(_config_value(
                getattr(self._config, "base_java_image_prefix", None)
            )),
            native_image=self._qualify_image_ref(
                _config_value(getattr(self._config, "base_native_image", None))
            ),
        )

    def _qualify_prefix(self, prefix: str) -> str:
        return self._qualify_image_ref(prefix)

    def _qualify_image_ref(self, image: str) -> str:
        image_text = _config_value(image)
        if not isinstance(image_text, str) or not image_text.strip():
            return image_text
        if "://" in image_text:
            return image_text

        registry_host = self._harbor_registry_host()
        normalized = image_text.strip()
        normalized_no_slash = normalized.lstrip("/")
        first_component = normalized_no_slash.split("/", 1)[0]
        if first_component == registry_host:
            return normalized_no_slash

        if self._looks_registry_qualified(first_component):
            return normalized_no_slash

        return f"{registry_host.rstrip('/')}/{normalized_no_slash}"

    def _looks_registry_qualified(self, first_component: str) -> bool:
        return (
            first_component == "localhost"
            or "." in first_component
            or ":" in first_component
        )

    def _harbor_registry_host(self) -> str:
        harbor_registry = _config_value(getattr(self._config, "harbor_registry", None))
        if not isinstance(harbor_registry, str) or not harbor_registry.strip():
            raise ValueError("harbor_registry must be a non-empty string")
        return _registry_host(harbor_registry)

    def _workspace_root(self) -> str:
        return self._config.workspace_root

    def _buildkit_platform(self) -> str:
        return self._config.buildkit_platform

    def _buildkit_addr(self) -> str:
        return self._config.buildkit_addr

    def _write_docker_config(self, workspace: str) -> str:
        registry = _config_value(self._config.harbor_registry)
        registry_host = _registry_host(registry)
        registry_with_scheme = _registry_with_scheme(registry)
        username = _config_value(self._config.harbor_username)
        password = _config_value(self._config.harbor_password)
        auth_token = _encode_auth(
            username,
            password,
        )
        docker_config_dir = os.path.join(workspace, "docker-config")
        os.makedirs(docker_config_dir, exist_ok=True)
        config_path = os.path.join(docker_config_dir, "config.json")
        auth_block = {
            "auth": auth_token,
            "username": username,
            "password": password,
        }
        auths = {registry_host: auth_block}
        if registry_with_scheme:
            auths[registry_with_scheme] = auth_block
        else:
            auths[f"http://{registry_host}"] = auth_block
        config = {"auths": auths}
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle)
        return docker_config_dir

def _sanitize_name(value: str) -> str:
    sanitized = _ALLOWED_TAG_RE.sub("-", value.lower()).strip("-")
    return sanitized or "latest"


def _normalize_tags(tags: Iterable[str], version_tag: str) -> List[str]:
    normalized = []
    for tag in tags or []:
        sanitized = _sanitize_name(tag)
        if sanitized not in normalized:
            normalized.append(sanitized)

    if version_tag not in normalized:
        normalized.append(version_tag)

    if not normalized:
        normalized.append("latest")

    return normalized


def _buildkit_platform_value(build_spec):
    platform = build_spec.get("platform")
    if platform is None:
        return None
    if isinstance(platform, str):
        text = platform.strip()
        if not text:
            raise ValueError("build_spec.platform must be a non-empty string")
        return text
    if isinstance(platform, dict):
        os_name = platform.get("os")
        arch = platform.get("arch")
        if not os_name:
            raise ValueError("build_spec.platform.os is required when platform is a dict")
        if arch:
            return f"{os_name}/{arch}"
        return str(os_name)
    raise ValueError("build_spec.platform must be a string or dict")


def _registry_host(registry: str) -> str:
    parsed = urlparse(registry if "://" in registry else f"https://{registry}")
    return parsed.netloc or parsed.path


def _registry_with_scheme(registry: str) -> str | None:
    if registry.startswith("http://") or registry.startswith("https://"):
        return registry
    return None


def _config_value(value):
    return value() if callable(value) else value


def _encode_auth(username: str, password: str) -> str:
    token = f"{username}:{password}".encode("utf-8")
    return base64.b64encode(token).decode("ascii")
