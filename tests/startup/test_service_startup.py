from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from dependency_injector import providers

from services.simulators_repository.rest_api.details.rest_repository_service import (
    _required_config_value,
)


ROOT = Path(__file__).resolve().parents[2]
RUNNABLE_SERVICES = sorted(
    path.name
    for path in (ROOT / "src" / "services").iterdir()
    if path.is_dir() and (path / "__main__.py").is_file()
)


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _load_local_runner():
    spec = importlib.util.spec_from_file_location(
        "run_service_local",
        ROOT / "scripts" / "run_service_local.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_runnable_service_has_package_main() -> None:
    for service in RUNNABLE_SERVICES:
        assert (ROOT / "src" / "services" / service / "__main__.py").is_file()


def test_each_package_main_delegates_to_main_function() -> None:
    for service in RUNNABLE_SERVICES:
        source = _source(f"src/services/{service}/__main__.py")
        tree = ast.parse(source)
        assert any(
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith(f"services.{service}.")
            and any(alias.name == "main" for alias in node.names)
            for node in tree.body
        )
        assert "main()" in source


def test_service_startup_functions_are_importable() -> None:
    from services.analytics.composition.startup import main as analytics_main
    from services.evaluator.composition.startup import main as evaluator_main
    from services.front.composition.startup import main as front_main
    from services.jobs_scheduler.composition.startup import main as jobs_scheduler_main
    from services.matrix_generation.composition.startup import main as matrix_main
    from services.simulators_repository.composition.startup import main as simulators_main
    from services.use_case.composition.startup import main as use_case_main
    from services.visualization.composition.startup import main as visualization_main
    from services.system_discovery.composition.startup import main as system_discovery_main
    from services.job_executor.composition.entrypoints.cli import main as executor_main

    assert callable(front_main)
    assert callable(analytics_main)
    assert callable(evaluator_main)
    assert callable(jobs_scheduler_main)
    assert callable(matrix_main)
    assert callable(simulators_main)
    assert callable(use_case_main)
    assert callable(visualization_main)
    assert callable(executor_main)
    assert callable(system_discovery_main)


def test_system_discovery_app_imports_with_only_repository_src_on_pythonpath(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from services.system_discovery.app.main import app; "
            "assert '/api/v1/train' in app.openapi()['paths']; "
            "assert '/api/v1/simulate' in app.openapi()['paths']",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_system_discovery_uses_selected_json_settings(monkeypatch, tmp_path) -> None:
    import json
    from types import SimpleNamespace
    from services.system_discovery.composition import startup

    path = tmp_path / "rtmf.main.json"
    path.write_text(json.dumps({"services": {
        "system_discovery": {"rest": {"host": "127.0.0.1", "port": 9010}},
        "analytics": {"unused_secret": "${UNRELATED_MISSING_SECRET}"},
    }}), encoding="utf-8")
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", str(path))
    monkeypatch.setenv("RTMF_SYSTEM_DISCOVERY_PORT", "1234")
    monkeypatch.delenv("UNRELATED_MISSING_SECRET", raising=False)
    app = object()
    monkeypatch.setitem(sys.modules, "services.system_discovery.app.main", SimpleNamespace(app=app))
    calls = []
    monkeypatch.setattr(startup.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))

    startup.main()

    assert calls == [(app, {"host": "127.0.0.1", "port": 9010})]


def test_given_valid_service_when_building_command_then_module_execution_is_used() -> None:
    runner = _load_local_runner()

    command = runner.build_command("front", ["--debug"])

    assert command[:3] == [sys.executable, "-m", "services.front"]
    assert command[3:] == ["--debug"]


def test_given_existing_pythonpath_when_building_env_then_src_is_prepended() -> None:
    runner = _load_local_runner()

    pythonpath = runner.compose_pythonpath(f"/already{os.pathsep}/there")

    assert pythonpath.split(os.pathsep)[0] == str(ROOT / "src")
    assert pythonpath.endswith(f"/already{os.pathsep}/there")


def test_given_unknown_service_when_validating_then_error_is_actionable() -> None:
    runner = _load_local_runner()

    with pytest.raises(runner.LocalRunnerError, match="Unknown service"):
        runner.validate_service("does_not_exist")


def test_given_missing_requested_config_when_resolving_then_error_is_actionable(tmp_path) -> None:
    runner = _load_local_runner()

    with pytest.raises(runner.LocalRunnerError, match="Requested config file does not exist"):
        runner.resolve_config_path(str(tmp_path / "missing.json"), {})


def test_given_local_config_and_exported_main_config_when_resolving_then_local_config_wins(tmp_path, monkeypatch) -> None:
    runner = _load_local_runner()
    local_config = tmp_path / "config" / "rtmf.local.json"
    deployment_config = tmp_path / "config" / "rtmf.main.json"
    local_config.parent.mkdir()
    local_config.write_text("{}", encoding="utf-8")
    deployment_config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(runner, "DEFAULT_LOCAL_CONFIG", local_config)

    resolved = runner.resolve_config_path(
        None,
        {"RTMF_MAIN_CONFIGURATION_FILE": str(deployment_config)},
    )

    assert resolved == local_config


def test_given_non_runnable_service_when_validating_then_missing_entrypoint_is_reported(tmp_path, monkeypatch) -> None:
    runner = _load_local_runner()
    services_dir = tmp_path / "src" / "services"
    service_dir = services_dir / "not_runnable"
    service_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "SERVICES_DIR", services_dir)
    monkeypatch.setattr(runner, "ROOT_DIR", tmp_path)

    with pytest.raises(runner.LocalRunnerError, match="no runnable module entrypoint"):
        runner.validate_service("not_runnable")


def test_local_runner_source_does_not_invoke_docker_or_deployment_scripts() -> None:
    source = _source("scripts/run_service_local.py")

    assert "docker" not in source.lower()
    assert "deploy_service.sh" not in source
    assert "deploy_services.sh" not in source


def test_legacy_wrappers_delegate_to_package_modules() -> None:
    wrappers = {
        "scripts/run_front.py": "run_service_local",
        "src/services/analytics/run.sh": "services.analytics",
        "src/services/jobs_scheduler/run.sh": "services.jobs_scheduler",
        "src/services/matrix_generation/run.sh": "services.matrix_generation",
        "src/services/simulators_repository/run.sh": "services.simulators_repository",
    }
    for path, module in wrappers.items():
        source = _source(path)
        assert module in source


def test_run_front_wrapper_delegates_to_local_runner_for_front(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("run_front", ROOT / "scripts" / "run_front.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captured = {}

    def fake_runner(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(module, "run_service_local_main", fake_runner)

    assert module.main(["--config", "config/rtmf.local.json", "--", "--debug"]) == 0
    assert captured["argv"] == [
        "--config",
        "config/rtmf.local.json",
        "front",
        "--",
        "--debug",
    ]


def test_jobs_scheduler_startup_does_not_swallow_exceptions() -> None:
    source = _source("src/services/jobs_scheduler/composition/startup.py")
    assert "except Exception" not in source
    assert "print(str(" not in source


def test_simulators_repository_rest_config_is_required() -> None:
    config = providers.Configuration(strict=True)

    with pytest.raises(ValueError, match="host"):
        _required_config_value(config, "host", str)
