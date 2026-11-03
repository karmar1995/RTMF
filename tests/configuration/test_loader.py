from __future__ import annotations

import json

import pytest
from dependency_injector import providers

from configuration import (
    ConfigurationError,
    load_config_files_into_provider,
    load_service_config_into_provider,
    normalize_service_name,
    service_configuration_env_var,
)


def _write_json(path, payload: dict) -> str:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_service_name_normalization() -> None:
    assert normalize_service_name("analytics") == "ANALYTICS"
    assert normalize_service_name("jobs_scheduler") == "JOBS_SCHEDULER"
    assert normalize_service_name("simulators-repository") == "SIMULATORS_REPOSITORY"
    assert service_configuration_env_var("use.case") == "RTMF_USE_CASE_CONFIGURATION_FILE"


def test_invalid_service_name_fails() -> None:
    with pytest.raises(ConfigurationError, match="service_name"):
        normalize_service_name("")


def test_invalid_loaded_service_name_fails() -> None:
    config = providers.Configuration(strict=True)

    with pytest.raises(ConfigurationError, match="Invalid service_name"):
        load_service_config_into_provider(config, service_name="not/a/service")


def test_missing_main_config_env_var_fails_clearly(monkeypatch) -> None:
    monkeypatch.delenv("RTMF_MAIN_CONFIGURATION_FILE", raising=False)
    config = providers.Configuration(strict=True)

    with pytest.raises(ConfigurationError, match="RTMF_MAIN_CONFIGURATION_FILE"):
        load_config_files_into_provider(config, service_name="analytics")


def test_main_config_loads(monkeypatch, tmp_path) -> None:
    main_path = _write_json(
        tmp_path / "main.json",
        {"services": {"analytics": {"rest": {"host": "0.0.0.0", "port": 9500}}}},
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", main_path)
    config = providers.Configuration(strict=True)

    load_service_config_into_provider(config, service_name="analytics")

    assert config.rest.host() == "0.0.0.0"
    assert config.rest.port() == 9500


def test_service_override_is_ignored_unless_explicitly_enabled(monkeypatch, tmp_path) -> None:
    main_path = _write_json(
        tmp_path / "main.json",
        {
            "services": {
                "analytics": {
                    "rest": {"host": "0.0.0.0", "port": 9500},
                    "aistor": {"bucket": "jobs-results"},
                }
            }
        },
    )
    override_path = _write_json(
        tmp_path / "analytics.json",
        {"services": {"analytics": {"rest": {"port": 9600}}}},
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", main_path)
    monkeypatch.setenv("RTMF_ANALYTICS_CONFIGURATION_FILE", override_path)
    config = providers.Configuration(strict=True)

    load_service_config_into_provider(config, service_name="analytics")

    assert config.rest.host() == "0.0.0.0"
    assert config.rest.port() == 9500
    assert config.aistor.bucket() == "jobs-results"


def test_explicit_service_override_recursively_overrides_main(monkeypatch, tmp_path) -> None:
    main_path = _write_json(
        tmp_path / "main.json",
        {
            "services": {
                "analytics": {
                    "rest": {"host": "0.0.0.0", "port": 9500},
                    "aistor": {"bucket": "jobs-results"},
                }
            }
        },
    )
    override_path = _write_json(
        tmp_path / "analytics.json",
        {"rest": {"port": 9600}},
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", main_path)
    monkeypatch.setenv("RTMF_ANALYTICS_CONFIGURATION_FILE", override_path)
    config = providers.Configuration(strict=True)

    load_service_config_into_provider(
        config,
        service_name="analytics",
        service_env_var="RTMF_ANALYTICS_CONFIGURATION_FILE",
    )

    assert config.rest.host() == "0.0.0.0"
    assert config.rest.port() == 9600
    assert config.aistor.bucket() == "jobs-results"


def test_loading_front_ignores_job_executor_env(monkeypatch, tmp_path) -> None:
    main_path = _write_json(
        tmp_path / "main.json",
        {
            "services": {
                "front": {"rest": {"host": "0.0.0.0", "port": 5000}},
                "job_executor": {"executor": {"user": "${JOB_EXECUTOR_USER}"}},
            }
        },
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", main_path)
    monkeypatch.delenv("JOB_EXECUTOR_USER", raising=False)
    config = providers.Configuration(strict=True)

    load_service_config_into_provider(config, service_name="front")

    assert config.rest.port() == 5000


def test_loading_job_executor_requires_own_env(monkeypatch, tmp_path) -> None:
    main_path = _write_json(
        tmp_path / "main.json",
        {
            "services": {
                "front": {"rest": {"host": "0.0.0.0", "port": 5000}},
                "job_executor": {"executor": {"user": "${JOB_EXECUTOR_USER}"}},
            }
        },
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", main_path)
    monkeypatch.delenv("JOB_EXECUTOR_USER", raising=False)
    config = providers.Configuration(strict=True)

    with pytest.raises(Exception, match="JOB_EXECUTOR_USER"):
        load_service_config_into_provider(config, service_name="job_executor")


def test_extra_service_sections_load_under_explicit_keys(monkeypatch, tmp_path) -> None:
    main_path = _write_json(
        tmp_path / "main.json",
        {
            "services": {
                "front": {"rest": {"port": 5000}},
                "use_case": {
                    "clients": {"analytics": {"base_url": "http://analytics"}}
                },
                "job_executor": {"executor": {"user": "${JOB_EXECUTOR_USER}"}},
            }
        },
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", main_path)
    monkeypatch.delenv("JOB_EXECUTOR_USER", raising=False)
    config = providers.Configuration(strict=True)

    load_service_config_into_provider(
        config,
        service_name="front",
        extra_service_sections=("use_case",),
    )

    assert config.front.rest.port() == 5000
    assert config.use_case.clients.analytics.base_url() == "http://analytics"


def test_use_case_loads_as_service_section(monkeypatch, tmp_path) -> None:
    main_path = _write_json(
        tmp_path / "main.json",
        {
            "services": {
                "use_case": {
                    "clients": {"analytics": {"base_url": "http://analytics"}}
                },
                "analytics": {"rest": {"port": "${UNRELATED_ANALYTICS_PORT}"}}
            },
        },
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", main_path)
    monkeypatch.delenv("UNRELATED_ANALYTICS_PORT", raising=False)
    config = providers.Configuration(strict=True)

    load_service_config_into_provider(config, service_name="use_case")

    assert config.clients.analytics.base_url() == "http://analytics"


def test_env_interpolation_works(monkeypatch, tmp_path) -> None:
    main_path = _write_json(
        tmp_path / "main.json",
        {"services": {"analytics": {"aistor": {"access_key": "${RTMF_AISTOR_ACCESS_KEY}"}}}},
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", main_path)
    monkeypatch.setenv("RTMF_AISTOR_ACCESS_KEY", "minio")
    config = providers.Configuration(strict=True)

    load_service_config_into_provider(config, service_name="analytics")

    assert config.aistor.access_key() == "minio"


def test_missing_interpolated_env_fails_when_required(monkeypatch, tmp_path) -> None:
    main_path = _write_json(
        tmp_path / "main.json",
        {"services": {"analytics": {"aistor": {"access_key": "${RTMF_AISTOR_ACCESS_KEY}"}}}},
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", main_path)
    monkeypatch.delenv("RTMF_AISTOR_ACCESS_KEY", raising=False)
    config = providers.Configuration(strict=True)

    with pytest.raises(Exception, match="RTMF_AISTOR_ACCESS_KEY"):
        load_service_config_into_provider(config, service_name="analytics")


@pytest.mark.parametrize("value", ["", " \t"])
def test_blank_required_env_from_compose_template_fails_before_composition(monkeypatch, tmp_path, value) -> None:
    path = _write_json(tmp_path / "main.json", {"services": {
        "analytics": {"aistor": {"access_key": "${STORAGE_USER}", "secret_key": "${STORAGE_PASSWORD}"}},
        "front": {"secret": "${UNRELATED_EMPTY_SECRET}"},
    }})
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", path)
    monkeypatch.setenv("STORAGE_USER", "do-not-print-this-value")
    monkeypatch.setenv("STORAGE_PASSWORD", value)
    monkeypatch.setenv("UNRELATED_EMPTY_SECRET", "")
    with pytest.raises(ConfigurationError, match="STORAGE_PASSWORD") as error:
        load_service_config_into_provider(providers.Configuration(strict=True), service_name="analytics")
    assert "do-not-print-this-value" not in str(error.value)
    assert "UNRELATED_EMPTY_SECRET" not in str(error.value)


def test_optional_empty_env_and_non_strict_interpolation_remain_supported(monkeypatch, tmp_path) -> None:
    path = _write_json(tmp_path / "main.json", {"services": {
        "analytics": {"token": "${OPTIONAL_TOKEN:}", "password": "${PASSWORD}"},
    }})
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", path)
    monkeypatch.setenv("OPTIONAL_TOKEN", "")
    monkeypatch.setenv("PASSWORD", "")
    config = providers.Configuration(strict=True)
    load_service_config_into_provider(config, service_name="analytics", envs_required=False)
    assert config.token() == ""


def test_interpolation_default_works(monkeypatch, tmp_path) -> None:
    main_path = _write_json(
        tmp_path / "main.json",
        {"services": {"front": {"flask": {"secret_key": "${RTMF_SECRET_KEY:dev}"}}}},
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", main_path)
    monkeypatch.delenv("RTMF_SECRET_KEY", raising=False)
    config = providers.Configuration(strict=True)

    load_service_config_into_provider(config, service_name="front")

    assert config.flask.secret_key() == "dev"


def test_service_override_env_var_is_optional(monkeypatch, tmp_path) -> None:
    main_path = _write_json(
        tmp_path / "main.json",
        {"services": {"analytics": {"rest": {"host": "0.0.0.0"}}}},
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", main_path)
    monkeypatch.delenv("RTMF_ANALYTICS_CONFIGURATION_FILE", raising=False)
    config = providers.Configuration(strict=True)

    load_service_config_into_provider(config, service_name="analytics")

    assert config.rest.host() == "0.0.0.0"


def test_missing_service_section_fails_clearly(monkeypatch, tmp_path) -> None:
    main_path = _write_json(tmp_path / "main.json", {"services": {}})
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", main_path)
    config = providers.Configuration(strict=True)

    with pytest.raises(ConfigurationError, match=r"services\.analytics"):
        load_service_config_into_provider(config, service_name="analytics")
