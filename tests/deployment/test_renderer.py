from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.lib.deployment import (
    DeploymentError,
    ReferenceResolver,
    compose_application,
    environment_requirements,
    read_environment,
    read_manifest,
    render_bundles,
    validate_environment,
    write_bundles,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def manifest():
    return read_manifest(ROOT / "config/deployment.example.json")


def cli(*args, environment=None):
    # -S proves deployment tooling needs neither site-packages nor application imports.
    return subprocess.run(
        [sys.executable, "-S", str(ROOT / "scripts/deployment.py"), *map(str, args)],
        capture_output=True, text=True, cwd=ROOT,
        env=environment if environment is not None else {"PATH": os.environ["PATH"]},
    )


def save_manifest(tmp_path, manifest):
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_all_services_share_a_project_but_have_only_their_runtime_sections(manifest):
    bundles = render_bundles(manifest)
    assert len(bundles) == 9
    assert {bundle.compose["name"] for bundle in bundles} == {"rtmf"}
    assert len(compose_application(bundles)["services"]) == 10
    for bundle in bundles:
        assert set(bundle.runtime["services"]) == (
            {"front", "use_case"} if bundle.service == "front" else {bundle.service}
        )
        assert bundle.compose["services"][bundle.service]["image"].startswith("rtmf/")


def test_remote_clients_do_not_need_remote_server_sections(manifest):
    manifest["runtime"]["services"] = {
        key: value for key, value in manifest["runtime"]["services"].items()
        if key in {"front", "use_case"}
    }
    front, = render_bundles(manifest, ["front"])
    assert front.runtime["services"]["use_case"]["clients"]["analytics"]["base_url"] == "http://analytics.example:63100"


def test_backend_ports_are_private_by_default_without_breaking_container_networking(manifest):
    bundles = render_bundles(manifest)
    for bundle in bundles:
        if bundle.service == "front":
            continue
        app = bundle.compose["services"][bundle.service]
        assert all(port["host_ip"] == "127.0.0.1" for port in app["ports"])
        assert bundle.runtime["services"][bundle.service]["rest"]["host"] == "0.0.0.0"


def test_local_client_references_use_docker_names_and_application_ports(manifest):
    manifest["runtime"]["services"]["analytics"]["rest"]["port"] = 9001
    bundles = {bundle.service: bundle for bundle in render_bundles(manifest)}
    front_clients = bundles["front"].runtime["services"]["use_case"]["clients"]
    evaluator_clients = bundles["evaluator"].runtime["services"]["evaluator"]["clients"]
    assert front_clients["analytics"]["base_url"] == "http://analytics:9001"
    assert evaluator_clients["analytics"]["base_url"] == "http://analytics:9001"
    assert front_clients["matrix_generator"]["base_url"] == "http://matrix_generation:8000"
    assert "depends_on" not in bundles["front"].compose["services"]["front"]
    assert manifest["endpoints"]["analytics"]["base_url"] == "http://analytics.example:63100"


def test_partial_machine_routes_only_installed_services_locally(manifest):
    bundles = {bundle.service: bundle for bundle in render_bundles(manifest, ["front", "analytics"])}
    clients = bundles["front"].runtime["services"]["use_case"]["clients"]
    assert clients["analytics"]["base_url"] == "http://analytics:8000"
    assert clients["jobs_scheduler"]["base_url"] == "http://jobs-scheduler.example:63200"


@pytest.mark.parametrize("mode", ["global", "per_service", "client_override"])
def test_external_url_overrides_are_preserved_for_local_services(manifest, mode):
    if mode == "global":
        manifest["deployment"]["local_endpoints"] = False
    elif mode == "per_service":
        manifest["deployment"]["services"]["analytics"]["endpoint"] = None
    else:
        manifest["runtime"]["services"]["use_case"]["clients"]["analytics"]["base_url"] = "https://analytics.example:63100"
    front, _ = render_bundles(manifest, ["front", "analytics"])
    assert front.runtime["services"]["use_case"]["clients"]["analytics"]["base_url"].endswith("analytics.example:63100")


def test_sidecar_and_resource_collisions_fail_before_output(manifest):
    manifest["deployment"]["services"]["analytics"]["compose"] = {"services": {"buildkit": {"image": "custom:latest"}}}
    with pytest.raises(DeploymentError, match="Conflicting Compose services entry: buildkit"):
        render_bundles(manifest, ["analytics", "simulators_repository"])
    manifest["deployment"]["services"]["analytics"]["compose"] = {"networks": {"buildkit_network": {"internal": True}}}
    with pytest.raises(DeploymentError, match="Conflicting Compose networks"):
        render_bundles(manifest, ["analytics", "simulators_repository"])


def test_compose_fragments_can_share_matching_resource_declarations(manifest):
    manifest["deployment"]["services"]["analytics"]["compose"] = {"networks": {"buildkit_network": {}}}
    model = compose_application(render_bundles(manifest, ["analytics", "simulators_repository"]))
    assert model["networks"] == {"buildkit_network": {}}


def test_only_selected_services_are_resolved_or_require_secrets(manifest):
    manifest["runtime"]["services"]["front"] = {"$ref": "#/missing"}
    manifest["deployment"]["services"]["front"] = {"$ref": "#/missing"}
    analytics, = render_bundles(manifest, ["analytics"])
    assert analytics.required == {"RTMF_AISTOR_ACCESS_KEY", "RTMF_AISTOR_SECRET_KEY"}
    validate_environment([analytics], {name: "test" for name in analytics.required})


def test_resource_overrides_and_list_replacement_are_local(manifest):
    manifest["runtime"]["services"]["analytics"]["aistor"]["access_key"] = "${ANALYTICS_STORAGE_USER}"
    analytics, = render_bundles(manifest, ["analytics"])
    assert "ANALYTICS_STORAGE_USER" in analytics.required
    assert "RTMF_AISTOR_ACCESS_KEY" not in analytics.required
    assert manifest["resources"]["aistor"]["access_key"] == "${RTMF_AISTOR_ACCESS_KEY}"
    resolver = ReferenceResolver({"base": {"nested": {"a": 1}, "items": [1, 2]}})
    assert resolver.resolve({"$ref": "#/base", "nested": {"b": 2}, "items": [3]}) == {
        "nested": {"a": 1, "b": 2}, "items": [3],
    }


@pytest.mark.parametrize("pointer", ["#/missing", "https://example.com/config", "#/array/-1", "#/array/01", "#/a~2b"])
def test_invalid_references_fail_clearly(pointer):
    with pytest.raises(DeploymentError, match="reference|pointer"):
        ReferenceResolver({"array": [1], "a~2b": 2}).resolve({"$ref": pointer})


def test_pointer_escaping_and_cycles():
    assert ReferenceResolver({"a/b": {"~": [42]}}).resolve({"$ref": "#/a~1b/~0/0"}) == 42
    with pytest.raises(DeploymentError, match="Cyclic reference"):
        ReferenceResolver({"a": {"$ref": "#/b"}, "b": {"$ref": "#/a"}}).resolve({"$ref": "#/a"})


def test_missing_front_use_case_is_reported(manifest):
    del manifest["runtime"]["services"]["use_case"]
    with pytest.raises(DeploymentError, match="runtime.services.use_case"):
        render_bundles(manifest, ["front"])


@pytest.mark.parametrize("value", [0, 65536, True, "8000", None])
def test_invalid_application_ports_are_rejected(manifest, value):
    manifest["defaults"]["rest"]["port"] = value
    with pytest.raises(DeploymentError, match="integer between"):
        render_bundles(manifest, ["analytics"])


def test_container_and_publication_ports_are_independent(manifest):
    manifest["runtime"]["services"]["analytics"]["rest"]["port"] = 9001
    analytics, = render_bundles(manifest, ["analytics"])
    port, = analytics.compose["services"]["analytics"]["ports"]
    assert port == {"target": 9001, "published": "63100", "host_ip": "127.0.0.1", "protocol": "tcp"}
    assert analytics.runtime["services"]["analytics"]["rest"]["port"] == 9001
    assert analytics.runtime["services"]["analytics"]["aistor"]["bucket"] == "jobs-results"


def test_internal_only_service_needs_no_publication(manifest):
    del manifest["deployment"]["services"]["analytics"]["publish"]
    analytics, = render_bundles(manifest, ["analytics"])
    assert "ports" not in analytics.compose["services"]["analytics"]


def test_backend_can_be_published_on_an_operator_selected_internal_interface(manifest):
    manifest["deployment"]["services"]["analytics"]["publish"] = {
        "host": "10.20.0.5", "port": 64100
    }
    analytics, = render_bundles(manifest, ["analytics"])
    port, = analytics.compose["services"]["analytics"]["ports"]
    assert port == {
        "target": 8000, "published": "64100", "host_ip": "10.20.0.5", "protocol": "tcp"
    }


def test_conflicting_publications_and_unknown_service_fail(manifest):
    manifest["deployment"]["services"]["parser"]["publish"]["port"] = 63100
    with pytest.raises(DeploymentError, match="Conflicting published port"):
        render_bundles(manifest, ["analytics", "parser"])
    with pytest.raises(DeploymentError, match="Unknown deployment service"):
        render_bundles(manifest, ["../analytics"])


@pytest.mark.parametrize("change,error", [
    ("publication_typo", "Unknown deployment settings"),
    ("hostname_bind", "IPv4 or IPv6"),
    ("empty_repository", "repository prefix"),
    ("empty_project", "project name"),
])
def test_invalid_deployment_settings_fail_before_writing(manifest, change, error):
    overrides = {}
    if change == "publication_typo":
        manifest["deployment"]["services"]["analytics"]["publsih"] = {"port": 63100}
    elif change == "hostname_bind":
        manifest["deployment"]["services"]["analytics"]["publish"]["host"] = "analytics.example"
    elif change == "empty_repository":
        overrides["repository"] = "///"
    else:
        overrides["project_name"] = ""
    with pytest.raises(DeploymentError, match=error):
        render_bundles(manifest, ["analytics"], **overrides)


def test_image_and_project_selection(manifest):
    analytics, = render_bundles(manifest, ["analytics"], repository="ghcr.io/org/rtmf", tag="v1", project_name="research")
    assert analytics.compose["services"]["analytics"]["image"] == "ghcr.io/org/rtmf/analytics:v1"
    assert analytics.compose["name"] == "research"
    analytics, = render_bundles(manifest, ["analytics"], image="registry.example/analytics@sha256:abc")
    assert analytics.compose["services"]["analytics"]["image"].endswith("@sha256:abc")
    with pytest.raises(DeploymentError, match="exactly one"):
        render_bundles(manifest, ["analytics", "parser"], image="custom:latest")


def test_environment_requirements_track_required_and_optional_occurrences():
    required, optional = environment_requirements(["${REQUIRED}", "${OPTIONAL:}", "${DEFAULT:http://host:123}", "${REQUIRED:default}"])
    assert required == {"REQUIRED"}
    assert optional == {"OPTIONAL", "DEFAULT"}
    with pytest.raises(DeploymentError, match="Malformed"):
        environment_requirements("${MISSING")


@pytest.mark.parametrize("value", ["", " \t"])
def test_empty_secrets_fail_without_exposing_values(manifest, value):
    bundles = render_bundles(manifest, ["analytics"])
    with pytest.raises(DeploymentError, match="RTMF_AISTOR_SECRET_KEY") as error:
        validate_environment(bundles, {"RTMF_AISTOR_ACCESS_KEY": "sensitive-value", "RTMF_AISTOR_SECRET_KEY": value})
    assert "sensitive-value" not in str(error.value)


def test_secret_file_is_literal_and_shell_has_precedence(tmp_path):
    path = tmp_path / "secrets.env"
    path.write_text("# comment\nFIRST='a#b $HOME `whoami`'\nSECOND=from-file\nTHIRD=\" spaced value \"\n", encoding="utf-8")
    assert read_environment(path, {"SECOND": "from-shell"}) == {
        "FIRST": "a#b $HOME `whoami`", "SECOND": "from-shell", "THIRD": " spaced value ",
    }
    path.write_text("FIRST=one\nFIRST=two\n", encoding="utf-8")
    with pytest.raises(DeploymentError, match="duplicate"):
        read_environment(path, {})


def test_render_is_deterministic_and_does_not_embed_environment_secrets(manifest, tmp_path, monkeypatch):
    monkeypatch.setenv("RTMF_AISTOR_SECRET_KEY", "never-serialize-this")
    before = copy.deepcopy(manifest)
    bundles = render_bundles(manifest, ["analytics"])
    write_bundles(bundles, tmp_path)
    first = {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    write_bundles(render_bundles(manifest, ["analytics"]), tmp_path)
    assert first == {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert all(b"never-serialize-this" not in content for content in first.values())
    assert manifest == before
    assert json.loads(first["environment.json"])["required"] == sorted(bundles[0].required)


def test_rerender_preserves_user_env_and_assets_and_removes_obsolete_generated_configs(manifest, tmp_path):
    write_bundles(render_bundles(manifest, ["analytics", "parser"]), tmp_path)
    secret_file = tmp_path / ".env"
    secret_file.write_text("PRIVATE='keep-this'\n", encoding="utf-8")
    notes = tmp_path / "services/analytics/notes.txt"
    notes.write_text("user-managed", encoding="utf-8")
    write_bundles(render_bundles(manifest, ["parser"]), tmp_path)
    assert secret_file.read_text() == "PRIVATE='keep-this'\n"
    assert notes.read_text() == "user-managed"
    assert not (tmp_path / "services/analytics/rtmf.main.json").exists()
    assert set(json.loads((tmp_path / "compose.yaml").read_text())["services"]) == {"parser"}


def test_config_changes_change_compose_hash_for_recreation(manifest):
    first, = render_bundles(manifest, ["analytics"])
    manifest["runtime"]["services"]["analytics"]["core"]["download_workers"] = 8
    second, = render_bundles(manifest, ["analytics"])
    assert first.compose["services"]["analytics"]["labels"] != second.compose["services"]["analytics"]["labels"]


def test_sidecars_scheduler_mounts_and_healthcheck_are_preserved(manifest):
    scheduler, simulators = render_bundles(manifest, ["jobs_scheduler", "simulators_repository"])
    app = scheduler.compose["services"]["jobs_scheduler"]
    assert "/run/munge" in {volume["target"] for volume in app["volumes"]}
    assert "RTMF_MAIN_CONFIGURATION_FILE" in app["healthcheck"]["test"][-1]
    assert simulators.compose["services"]["simulators_repository"]["depends_on"] == {"buildkit": {"condition": "service_healthy"}}
    assert "ports" not in simulators.compose["services"]["buildkit"]
    assert "buildkit_state" in simulators.compose["volumes"]


@pytest.mark.parametrize("key,value", [("environment", {}), ("ports", []), ("image", "override")])
def test_fragments_cannot_override_generated_configuration(manifest, key, value):
    manifest["deployment"]["services"]["analytics"]["compose"] = {"services": {"analytics": {key: value}}}
    with pytest.raises(DeploymentError, match="managed by the renderer"):
        render_bundles(manifest, ["analytics"])


def test_no_files_are_written_when_validation_fails(manifest, tmp_path):
    path = save_manifest(tmp_path, manifest)
    output = tmp_path / "output"
    result = cli("render", "analytics", "--check-env", "--manifest", path, "--output-dir", output)
    assert result.returncode == 2
    assert "RTMF_AISTOR_SECRET_KEY" in result.stderr
    assert not output.exists()
    manifest["runtime"]["services"]["parser"]["rest"] = {"port": "bad"}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = cli("render", "analytics", "parser", "--manifest", path, "--output-dir", output)
    assert result.returncode == 2
    assert not output.exists()


def test_init_kit_uses_allowlist_and_runs_without_source_or_dependencies(tmp_path):
    target = tmp_path / "kit"
    result = cli("init", "--target-dir", target)
    assert result.returncode == 0, result.stderr
    assert not (target / "config/rtmf.local.json").exists()
    assert not (target / "scripts/local_vars.sh").exists()
    assert not (target / "src").exists()
    secrets = target / "dist/deployment/.env"
    assert secrets.stat().st_mode & 0o777 == 0o600
    secrets.write_text("USER_SETTING=preserved\n", encoding="utf-8")
    assert cli("init", "--target-dir", target).returncode == 0
    assert secrets.read_text() == "USER_SETTING=preserved\n"
    result = subprocess.run([sys.executable, "-S", str(target / "scripts/render_deployment.py"), "parser"], capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert (target / "dist/deployment/compose.yaml").is_file()
    assert secrets.read_text() == "USER_SETTING=preserved\n"


def test_inspect_and_stop_use_saved_bundles_without_manifest_or_secrets(manifest, tmp_path):
    write_bundles(render_bundles(manifest, ["analytics"]), tmp_path)
    for action in ("status", "logs", "stop"):
        result = cli(action, "analytics", "--output-dir", tmp_path, "--dry-run")
        assert result.returncode == 0, result.stderr
        assert "docker compose" in result.stdout


def test_deploy_uses_saved_model_and_requires_only_target_service_secrets(manifest, tmp_path):
    write_bundles(render_bundles(manifest), tmp_path)
    (tmp_path / ".env").write_text("RTMF_AISTOR_ACCESS_KEY=user\nRTMF_AISTOR_SECRET_KEY=password\n", encoding="utf-8")
    # A nonexistent Docker executable would fail after validation, proving unrelated secrets are ignored.
    result = cli("deploy", "analytics", "--output-dir", tmp_path, environment={"PATH": ""})
    assert result.returncode == 2
    assert "docker command is not available" in result.stderr
    assert "Missing or empty" not in result.stderr
    result = cli("deploy", "front", "--output-dir", tmp_path, environment={"PATH": ""})
    assert result.returncode == 2
    assert "RTMF_SECRET_KEY" in result.stderr


def test_operations_target_the_single_project_and_do_not_rerender(manifest, tmp_path):
    write_bundles(render_bundles(manifest), tmp_path)
    before = (tmp_path / "compose.yaml").read_bytes()
    result = cli("deploy", "front", "--output-dir", tmp_path, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("docker compose") == 3
    assert "up -d front" in result.stdout
    assert (tmp_path / "compose.yaml").read_bytes() == before
    result = cli("logs", "front", "analytics", "--follow", "--output-dir", tmp_path, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("docker compose") == 1
    assert "front analytics" in result.stdout
    result = cli("stop", "front", "--down", "--output-dir", tmp_path, "--dry-run")
    assert result.returncode == 2
    assert "whole application" in result.stderr
    result = cli("stop", "--down", "--output-dir", tmp_path, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith(" down")


def test_deploy_passes_only_named_secrets_to_compose_and_pulls_sidecars(manifest, tmp_path):
    path = save_manifest(tmp_path, manifest)
    log = tmp_path / "docker-calls.jsonl"
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\nimport json,os,sys\n"
        f"with open({str(log)!r}, 'a') as f: f.write(json.dumps({{'args': sys.argv[1:], 'secret': os.environ.get('RTMF_HARBOR_PASSWORD')}})+'\\n')\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    bundles = render_bundles(manifest, ["simulators_repository"])
    secrets = tmp_path / "secrets.env"
    secrets.write_text("\n".join(f"{name}=test-value" for name in bundles[0].required), encoding="utf-8")
    write_bundles(bundles, tmp_path / "output")
    result = cli("deploy", "simulators_repository", "--output-dir", tmp_path / "output", "--secrets-file", secrets,
                 environment={"PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]})
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [call["args"][-2:] for call in calls] == [["--include-deps", "simulators_repository"], ["-d", "simulators_repository"], ["ps", "simulators_repository"]]
    assert all(call["secret"] == "test-value" for call in calls)
    assert "test-value" not in result.stdout + result.stderr
    compose = json.loads((tmp_path / "output/compose.yaml").read_text())
    assert set(compose["services"]["simulators_repository"]["environment"]) == bundles[0].required | {"RTMF_MAIN_CONFIGURATION_FILE"}


def test_manifest_version_and_duplicate_keys(tmp_path):
    path = tmp_path / "deployment.json"
    for text in ('{"version": 2}', '{"version": 1, "version": 1}'):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(DeploymentError):
            read_manifest(path)


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose is not installed")
def test_compose_accepts_every_bundle_and_relocated_mounts(manifest, tmp_path):
    version = subprocess.run(["docker", "compose", "version"], capture_output=True)
    if version.returncode:
        pytest.skip("Docker Compose is not installed")
    bundles = render_bundles(manifest)
    output = tmp_path / "first"
    write_bundles(bundles, output)
    relocated = tmp_path / "relocated"
    output.rename(relocated)
    environment = {"PATH": os.environ["PATH"], **{name: "test-value" for bundle in bundles for name in bundle.required | bundle.optional}}
    compose_path = relocated / "compose.yaml"
    result = subprocess.run(["docker", "compose", "-f", str(compose_path), "config", "--format", "json"], capture_output=True, text=True, env=environment)
    assert result.returncode == 0, result.stderr
    model = json.loads(result.stdout)
    assert model["name"] == "rtmf"
    for bundle in bundles:
        app = model["services"][bundle.service]
        assert app["volumes"][0]["source"] == str(relocated / "services" / bundle.service / "rtmf.main.json")
        assert set(app["environment"]) == bundle.required | bundle.optional | {"RTMF_MAIN_CONFIGURATION_FILE"}
        assert "default" in app["networks"]


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose is not installed")
def test_native_compose_reads_user_env_and_selects_front_with_unrelated_empty_values(manifest, tmp_path):
    write_bundles(render_bundles(manifest), tmp_path)
    (tmp_path / ".env").write_text("RTMF_SECRET_KEY='literal $HOME # secret'\nRTMF_HARBOR_PASSWORD=''\n", encoding="utf-8")
    result = subprocess.run(["docker", "compose", "config", "--format", "json", "front"], cwd=tmp_path,
                            capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    if "not a docker command" in result.stderr:
        pytest.skip("Docker Compose is not installed")
    assert result.returncode == 0, result.stderr
    model = json.loads(result.stdout)
    assert set(model["services"]) == {"front"}
    # Compose's config renderer escapes dollar signs so the result can be reused.
    assert model["services"]["front"]["environment"]["RTMF_SECRET_KEY"].replace("$$", "$") == "literal $HOME # secret"
    raw_environment = subprocess.run(["docker", "compose", "config", "--environment"], cwd=tmp_path,
                                     capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    assert raw_environment.returncode == 0, raw_environment.stderr
    values = dict(line.split("=", 1) for line in raw_environment.stdout.splitlines() if "=" in line)
    assert values["RTMF_SECRET_KEY"] == "literal $HOME # secret"
    assert "RTMF_HARBOR_PASSWORD" not in model["services"]["front"]["environment"]
