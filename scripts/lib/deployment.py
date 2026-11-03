"""Deployment rendering. Deliberately uses only the Python standard library."""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class DeploymentError(ValueError):
    pass


_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
_VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")
_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
CONTAINER_CONFIG = "/etc/rtmf/rtmf.main.json"


def _object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise DeploymentError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeploymentError(f"{label} must be a non-empty string")
    return value


def _port(value: Any, label: str) -> int:
    if type(value) is not int or not 1 <= value <= 65535:
        raise DeploymentError(f"{label} must be an integer between 1 and 65535")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DeploymentError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_manifest(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, json.JSONDecodeError) as exc:
        # JSONDecodeError's message has positions, without exposing file contents.
        raise DeploymentError(f"Cannot read deployment manifest {path}: {exc}") from exc
    _object(document, "manifest")
    if type(document.get("version")) is not int or document["version"] != 1:
        raise DeploymentError("manifest.version must be 1")
    return document


def merge(base: dict, overrides: Mapping) -> dict:
    """Merge objects recursively; scalar values and lists replace their defaults."""
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ReferenceResolver:
    """Resolve local JSON pointers, with object overrides, in selected subtrees."""

    def __init__(self, document: dict):
        self.document = document

    def resolve(self, value: Any, chain: tuple[str, ...] = ()) -> Any:
        if isinstance(value, list):
            return [self.resolve(item, chain) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" not in value:
            return {key: self.resolve(item, chain) for key, item in value.items()}

        pointer = value["$ref"]
        if not isinstance(pointer, str) or not pointer.startswith("#/"):
            raise DeploymentError("$ref must be a local JSON pointer starting with #/")
        if pointer in chain:
            raise DeploymentError(f"Cyclic reference: {' -> '.join((*chain, pointer))}")
        target: Any = self.document
        try:
            for token in pointer[2:].split("/"):
                if re.search(r"~(?![01])", token):
                    raise KeyError(token)
                token = token.replace("~1", "/").replace("~0", "~")
                if isinstance(target, list):
                    if not re.fullmatch(r"0|[1-9][0-9]*", token):
                        raise KeyError(token)
                    target = target[int(token)]
                else:
                    target = target[token]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise DeploymentError(f"Unknown reference: {pointer}") from exc
        resolved = self.resolve(target, (*chain, pointer))
        overrides = {key: item for key, item in value.items() if key != "$ref"}
        if overrides:
            if not isinstance(resolved, dict):
                raise DeploymentError(f"Reference overrides require an object: {pointer}")
            resolved = merge(resolved, self.resolve(overrides, chain))
        return resolved


def environment_requirements(value: Any) -> tuple[set[str], set[str]]:
    """Inspect Dependency Injector placeholders without resolving secret values."""
    required: set[str] = set()
    optional: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, str):
            for match in _ENV.finditer(item):
                (required if match.group(2) is None else optional).add(match.group(1))
            if "${" in _ENV.sub("", item):
                raise DeploymentError("Malformed environment placeholder in selected configuration")

    walk(value)
    if "RTMF_MAIN_CONFIGURATION_FILE" in required | optional:
        raise DeploymentError("RTMF_MAIN_CONFIGURATION_FILE is reserved for the generated config path")
    return required, optional - required


def read_environment(path: Path | None, inherited: Mapping[str, str] | None = None) -> dict[str, str]:
    """Read literal KEY=value pairs. Never evaluate shell code or expand variables."""
    values: dict[str, str] = {}
    if path is not None:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise DeploymentError(f"Cannot read secrets file {path}: {exc}") from exc
        for number, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not separator or not _VARIABLE.fullmatch(key) or key in values:
                raise DeploymentError(f"Invalid or duplicate environment entry at {path}:{number}")
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise DeploymentError(f"Unclosed environment value at {path}:{number}")
                value = value[1:-1]
            if "\x00" in value:
                raise DeploymentError(f"Invalid environment value at {path}:{number}")
            values[key] = value
    values.update(os.environ if inherited is None else inherited)
    return values


def validate_environment(bundles: list[Bundle], environment: Mapping[str, str]) -> None:
    validate_required_environment({name for bundle in bundles for name in bundle.required}, environment)


def validate_required_environment(required: set[str], environment: Mapping[str, str]) -> None:
    missing = sorted(name for name in required if not environment.get(name, "").strip())
    if missing:
        raise DeploymentError("Missing or empty required environment variables: " + ", ".join(missing))


@dataclass
class Bundle:
    service: str
    runtime: dict
    compose: dict
    required: set[str]
    optional: set[str]


def render_bundles(
    document: dict,
    services: list[str] | None = None,
    *,
    repository: str | None = None,
    tag: str | None = None,
    image: str | None = None,
    project_name: str | None = None,
) -> list[Bundle]:
    deployment = _object(document.get("deployment"), "deployment")
    definitions = _object(deployment.get("services"), "deployment.services")
    selected = list(dict.fromkeys(services if services else definitions))
    if not selected:
        raise DeploymentError("No services selected for deployment")
    for name in selected:
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name not in definitions:
            raise DeploymentError(f"Unknown deployment service: {name}")
    document = _with_local_endpoints(document, selected)
    resolver = ReferenceResolver(document)
    deployment = document["deployment"]
    definitions = deployment["services"]
    runtime = _object(_object(document.get("runtime"), "runtime").get("services"), "runtime.services")
    if image is not None and len(selected) != 1:
        raise DeploymentError("--image requires exactly one selected service")
    project = project_name if project_name is not None else deployment.get("name", "rtmf")
    if not isinstance(project, str) or not _PROJECT.fullmatch(project):
        raise DeploymentError("deployment.name must be a lowercase Compose project name")
    images = _object(resolver.resolve(deployment.get("images", {})), "deployment.images")
    repository = _text(repository if repository is not None else images.get("repository", "rtmf"), "image repository").rstrip("/")
    if not repository or any(char.isspace() for char in repository) or "$" in repository or "://" in repository:
        raise DeploymentError("image repository must be a Docker repository prefix")
    tag = tag if tag is not None else images.get("tag", "latest")
    if not isinstance(tag, str) or not _TAG.fullmatch(tag):
        raise DeploymentError("image tag is invalid")
    bundles = []
    publications: list[tuple[str, int]] = []
    for name in selected:
        spec = _object(resolver.resolve(definitions[name]), f"deployment.services.{name}")
        unknown = set(spec) - {"image", "publish", "compose", "endpoint"}
        if unknown:
            raise DeploymentError(f"Unknown deployment settings for {name}: " + ", ".join(sorted(unknown)))
        sections = [name, "use_case"] if name == "front" else [name]
        config = {}
        for section in sections:
            if section not in runtime:
                raise DeploymentError(f"Missing runtime.services.{section} for {name}")
            config[section] = _object(resolver.resolve(runtime[section]), f"runtime.services.{section}")
        rest = _object(config[name].get("rest"), f"runtime.services.{name}.rest")
        _text(rest.get("host"), f"runtime.services.{name}.rest.host")
        port = _port(rest.get("port"), f"runtime.services.{name}.rest.port")
        required, optional = environment_requirements(config)
        image_ref = image if image is not None else spec.get("image", f"{repository}/{name.replace('_', '-')}:{tag}")
        _text(image_ref, f"deployment.services.{name}.image")
        if any(char.isspace() for char in image_ref) or "$" in image_ref or "://" in image_ref:
            raise DeploymentError(f"Invalid image reference for {name}")

        compose = _object(spec.get("compose", {}), f"deployment.services.{name}.compose")
        if set(compose) - {"services", "volumes", "networks", "configs", "secrets"}:
            raise DeploymentError(f"Unsupported Compose fragment fields for {name}")
        compose_services = _object(compose.setdefault("services", {}), f"{name}.compose.services")
        options = _object(compose_services.get(name, {}), f"{name} Compose service")
        if {"image", "environment", "ports", "network_mode"} & options.keys():
            raise DeploymentError(f"{name}: image, environment, ports and network_mode are managed by the renderer")
        # Compose fragments describe infrastructure, not a second variable layer.
        # Use manifest references for shared values; runtime secrets stay in JSON.
        if "${" in json.dumps(compose):
            raise DeploymentError(f"{name}: Compose fragments must use manifest references, not environment interpolation")
        volumes = options.get("volumes", [])
        if not isinstance(volumes, list):
            raise DeploymentError(f"{name}.compose volumes must be a list")
        for volume in volumes:
            target = volume.get("target") if isinstance(volume, dict) else None
            if target == CONTAINER_CONFIG or isinstance(volume, str) and CONTAINER_CONFIG in volume:
                raise DeploymentError(f"{name}: the configuration mount is managed by the renderer")
        app = merge({"restart": "unless-stopped"}, options)
        networks = app.setdefault("networks", ["default"])
        if isinstance(networks, list) and all(isinstance(network, str) for network in networks):
            if "default" not in networks:
                networks.append("default")
        elif isinstance(networks, dict):
            networks.setdefault("default", None)
        else:
            raise DeploymentError(f"{name}.compose networks must be a list or object")
        app.update({
            "image": image_ref,
            "environment": {
                "RTMF_MAIN_CONFIGURATION_FILE": CONTAINER_CONFIG,
                **{variable: None for variable in sorted(required | optional)},
            },
            "volumes": [
                {"type": "bind", "source": f"./services/{name}/rtmf.main.json", "target": CONTAINER_CONFIG,
                 "read_only": True, "bind": {"create_host_path": False}},
                *volumes,
            ],
        })
        # Compose otherwise cannot detect changes inside a bind-mounted JSON file.
        labels = app.get("labels", {})
        if not isinstance(labels, dict):
            raise DeploymentError(f"{name}.compose labels must be an object")
        app["labels"] = {**labels, "io.rtmf.configuration-sha256": hashlib.sha256(
            json_text({"services": config}).encode("utf-8")
        ).hexdigest()}
        publish = spec.get("publish")
        if publish is not None:
            publish = _object(publish, f"deployment.services.{name}.publish")
            host = _text(publish.get("host", "0.0.0.0"), f"{name}.publish.host")
            try:
                ipaddress.ip_address(host)
            except ValueError as exc:
                raise DeploymentError(f"{name}.publish.host must be an IPv4 or IPv6 bind address") from exc
            published = _port(publish.get("port"), f"{name}.publish.port")
            for previous_host, previous_port in publications:
                if previous_port == published and (host == previous_host or host in {"0.0.0.0", "::"} or previous_host in {"0.0.0.0", "::"}):
                    raise DeploymentError(f"Conflicting published port {published} for selected services")
            publications.append((host, published))
            app["ports"] = [{"target": port, "published": str(published), "host_ip": host, "protocol": "tcp"}]
        compose_services[name] = app
        compose["name"] = project
        bundles.append(Bundle(name, {"services": config}, compose, required, optional))
    compose_application(bundles)  # Check cross-service collisions before any writes.
    return bundles


def _with_local_endpoints(document: dict, selected: list[str]) -> dict:
    """Rewrite referenced client URLs only for services installed on this machine."""
    result = copy.deepcopy(document)
    deployment = result["deployment"]
    enabled = deployment.get("local_endpoints", True)
    if type(enabled) is not bool:
        raise DeploymentError("deployment.local_endpoints must be a boolean")
    if not enabled:
        return result
    endpoints = _object(result.get("endpoints", {}), "endpoints")
    runtime = _object(_object(result.get("runtime"), "runtime").get("services"), "runtime.services")
    resolver = ReferenceResolver(document)
    claimed = set()
    for name in selected:
        spec = _object(resolver.resolve(deployment["services"][name]), f"deployment.services.{name}")
        endpoint = spec.get("endpoint", name if name in endpoints else None)
        if endpoint is None:
            continue
        if not isinstance(endpoint, str) or endpoint not in endpoints:
            raise DeploymentError(f"{name}.endpoint must name an entry in endpoints, or be null")
        if endpoint in claimed:
            raise DeploymentError(f"Multiple services claim endpoint: {endpoint}")
        claimed.add(endpoint)
        config = _object(resolver.resolve(runtime.get(name)), f"runtime.services.{name}")
        rest = _object(config.get("rest"), f"runtime.services.{name}.rest")
        port = _port(rest.get("port"), f"runtime.services.{name}.rest.port")
        host = _text(rest.get("host"), f"runtime.services.{name}.rest.host")
        if host == "localhost" or host == "::1" or host.startswith("127."):
            raise DeploymentError(f"{name}: local clients require a network-reachable rest.host")
        client = _object(resolver.resolve(endpoints[endpoint]), f"endpoints.{endpoint}")
        endpoints[endpoint] = {**client, "base_url": f"http://{name}:{port}"}
    if endpoints:
        result["endpoints"] = endpoints
    return result


def compose_application(bundles: list[Bundle]) -> dict:
    """Combine rendered services and sidecars into one Compose project."""
    if not bundles:
        raise DeploymentError("No services selected for deployment")
    application: dict[str, Any] = {"name": bundles[0].compose["name"], "services": {}}
    for bundle in bundles:
        for section in ("services", "volumes", "networks", "configs", "secrets"):
            incoming = _object(bundle.compose.get(section, {}), f"{bundle.service}.compose.{section}")
            if not incoming:
                continue
            combined = application.setdefault(section, {})
            for name, value in incoming.items():
                if name in combined and (section == "services" or combined[name] != value):
                    raise DeploymentError(f"Conflicting Compose {section} entry: {name}")
                combined[name] = copy.deepcopy(value)
    return application


def write_text(path: Path, content: str, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def json_text(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def environment_example(required: set[str], optional: set[str]) -> str:
    return ("# Copy to .env beside compose.yaml. Do not commit filled secrets.\n"
            "# Use single quotes for literal values containing $, #, or spaces.\n"
            "# Required for the selected services:\n"
            + "".join(f"{name}=''\n" for name in sorted(required))
            + "# Optional (the runtime JSON supplies defaults):\n"
            + "".join(f"# {name}=''\n" for name in sorted(optional)))


def bundle_readme(bundles: list[Bundle]) -> str:
    rows = []
    for bundle in bundles:
        app = bundle.compose["services"][bundle.service]
        ports = []
        for port in app.get("ports", []):
            host = port["host_ip"]
            ports.append(f"[{host}]:{port['published']}" if ":" in host else f"{host}:{port['published']}")
        rows.append(f"| `{bundle.service}` | `{app['image']}` | {', '.join(ports) or 'None'} |")
    target = "front" if any(bundle.service == "front" for bundle in bundles) else bundles[0].service
    return """# RTMF prepared deployment

This directory is a Compose application prepared for one machine. You need
Docker Engine and the Compose plugin; host Python is not required to run it.
The installed application services are:

| Service | Image | Published host address |
| --- | --- | --- |
""" + "\n".join(rows) + f"""

## Before starting

Backend API addresses and ports must be reachable only from the internal
network. The public template binds backend host ports to `127.0.0.1`; if an
operator changes an address or port for remote access, they must restrict it
to the internal network. Backend APIs rely on this network boundary for access
control.

1. Confirm the image release, host mount paths, endpoints, and external systems
   with the operator who prepared this bundle. Full installations use existing
   PostgreSQL, S3 storage, Keycloak, a simulator registry, and Slurm. They are
   not provisioned by this Compose application. Parser alone needs none of them.
2. If `.env` is absent, copy `.env.example` to `.env`. Fill its required entries
   using credentials supplied by your operator. Keep it private. Use simple
   single-quoted values such as `NAME='value'`; shell variables take precedence.
3. If application images are private, run `docker login <REGISTRY_HOST>` using
   your registry account. Simulator push/pull credentials in `.env` serve a
   separate purpose.

## Start and check

Run from this directory:

```sh
docker version
docker compose version
docker compose config --quiet
docker compose up -d --pull missing
docker compose ps -a
```

This uses images already present on the host and downloads missing images,
including BuildKit when selected. To refresh a tag, run `docker compose pull`
before `up`; locally built images should be rebuilt instead.
Application containers should stay running; BuildKit, when included, should
become healthy. Repeated restarts indicate a startup failure. Read the logs:

```sh
docker compose logs --tail 100 {target}
```

Missing required values must be filled in `.env`. Pull errors usually mean an
incorrect image/tag or missing registry login. Missing bind paths require the
operator to prepare the host or correct the source manifest. A running container
alone does not verify database access or Slurm submission. For the web frontend,
use the public HTTPS URL and Keycloak account provided by your operator; there
is no built-in administrator password.

## Daily operations

```sh
docker compose up -d --pull missing {target}
docker compose logs -f {target}
docker compose stop {target}
docker compose down  # Stop and remove this machine's application containers
```

Compose starts declared dependencies such as the simulator repository's
BuildKit sidecar. Starting one service does not start its other HTTP backends.
Local clients point to services included in this bundle; absent services use
remote URLs configured by the operator.

To change configuration or image tags, edit the original deployment manifest,
render again, then pull images and run `docker compose up -d`. Rendering keeps
your `.env`. Generated JSON and Compose files should not be edited directly.
Keep external database/storage backups separately. Container-local working
files are lost on recreation unless mounted; frontend sessions reset on restart.
"""


def write_bundles(bundles: list[Bundle], output_dir: Path) -> None:
    application = compose_application(bundles)
    required = set().union(*(bundle.required for bundle in bundles))
    optional = set().union(*(bundle.optional for bundle in bundles)) - required
    metadata = {"required": sorted(required), "optional": sorted(optional), "services": {
        bundle.service: {"required": sorted(bundle.required), "optional": sorted(bundle.optional)}
        for bundle in bundles
    }}
    # Remove only generated runtime files known from the previous render.
    # User-managed .env and additional assets are always preserved.
    previous = output_dir / "environment.json"
    stale = []
    if previous.is_file():
        try:
            old_services = json.loads(previous.read_text(encoding="utf-8")).get("services", {})
            stale = [name for name in old_services if _NAME.fullmatch(name) and name not in metadata["services"]]
        except (OSError, ValueError, AttributeError, TypeError):
            raise DeploymentError(f"Cannot read previous deployment metadata: {previous}") from None
    for bundle in bundles:
        directory = output_dir / "services" / bundle.service
        write_text(directory / "rtmf.main.json", json_text(bundle.runtime))
    write_text(output_dir / "compose.yaml", json_text(application))
    write_text(output_dir / "environment.json", json_text(metadata))
    write_text(output_dir / ".env.example", environment_example(required, optional), mode=0o600)
    write_text(output_dir / "README.md", bundle_readme(bundles))
    for name in stale:
        (output_dir / "services" / name / "rtmf.main.json").unlink(missing_ok=True)
