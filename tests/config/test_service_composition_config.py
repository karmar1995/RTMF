from __future__ import annotations

import json
from pathlib import Path

import pytest
from dependency_injector import providers
from dependency_injector.errors import Error as DependencyInjectorError

from configuration import load_service_config_into_provider
from scripts.lib.deployment import ReferenceResolver, read_manifest
from adapters.postgres_evaluations_store.evaluations_store import (
    PostgresEvaluationsStore,
)
from adapters.system_discovery_aistor_adapter import SystemDiscoveryAIStorAdapter
from services.analytics.composition.composition_root import ApplicationContainer as AnalyticsContainer
from services.front.composition.build_front_app import load_front_config
from services.job_executor.composition.root import create_container as create_job_executor_container
from services.jobs_scheduler.composition.root import create_container as create_jobs_scheduler_container
from services.matrix_generation.composition.build_app import create_container as create_matrix_container
from services.simulators_repository.composition.container import RepositoryServiceContainer
from services.use_case.composition.build_usecases import UseCaseContainer
from use_case_contracts.ports import SystemDiscoveryAIStorPort, SystemDiscoveryPort


class FakeMinio:
    def bucket_exists(self, _bucket: str) -> bool:
        return True


def _set_keycloak_env(monkeypatch) -> None:
    monkeypatch.setenv("KEYCLOAK_HOST", "localhost")
    monkeypatch.setenv("KEYCLOAK_PORT", "8080")
    monkeypatch.setenv("RTMF_KEYCLOAK_CLIENT_ID", "rtmf-web")
    monkeypatch.setenv("RTMF_KEYCLOAK_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv(
        "RTMF_KEYCLOAK_TOKEN_ENCRYPTION_KEY",
        "eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg",
    )


def _write_main_config(tmp_path) -> str:
    path = tmp_path / "rtmf.main.json"
    path.write_text(
        json.dumps(
            {
                "services": {
                    "front": {
                        "rest": {"host": "127.0.0.1", "port": 5000, "debug": False},
                        "flask": {
                            "secret_key": "${RTMF_SECRET_KEY:dev}",
                            "simulation_models": "./sim_models/",
                            "simulation_runs": "./sim_workspace/",
                        },
                    },
                    "use_case": {
                        "clients": {
                            "jobs_scheduler": {"base_url": "http://jobs", "timeout_seconds": 10, "auth_token": ""},
                            "simulators_repository": {"base_url": "http://sims", "timeout_seconds": 10, "auth_token": ""},
                            "analytics": {"base_url": "http://analytics", "timeout_seconds": 10, "auth_token": ""},
                            "visualization": {"base_url": "http://viz", "timeout_seconds": 10, "auth_token": ""},
                            "parser": {"base_url": "http://parser", "timeout_seconds": 10, "auth_token": ""},
                            "matrix_generator": {"base_url": "http://matrix", "timeout_seconds": 10},
                            "system_discovery": {"base_url": "http://system-discovery", "timeout_seconds": 10, "auth_token": ""},
                        },
                        "aistor": {
                            "endpoint": "http://aistor",
                            "secure": False,
                            "access_key": "${RTMF_AISTOR_ACCESS_KEY}",
                            "secret_key": "${RTMF_AISTOR_SECRET_KEY}",
                        },
                        "adapters": {
                            "system_discovery_aistor": {
                                "endpoint": "http://aistor",
                                "secure": False,
                                "bucket": "system-discovery",
                                "access_key": "${RTMF_AISTOR_ACCESS_KEY}",
                                "secret_key": "${RTMF_AISTOR_SECRET_KEY}",
                            },
                        },
                        "postgres": {"jobs_repository": {"dsn": "${RTMF_JOBS_POSTGRES_DSN}"}},
                        "storage": {
                            "system_discovery_training_results": {
                                "endpoint": "http://aistor",
                                "secure": False,
                                "bucket": "system-discovery",
                                "access_key": "${RTMF_AISTOR_ACCESS_KEY}",
                                "secret_key": "${RTMF_AISTOR_SECRET_KEY}",
                            }
                        },
                    },
                    "analytics": {
                        "rest": {"host": "0.0.0.0", "port": 9500},
                        "aistor": {
                            "endpoint": "http://aistor",
                            "secure": False,
                            "bucket": "jobs-results",
                            "access_key": "${RTMF_AISTOR_ACCESS_KEY}",
                            "secret_key": "${RTMF_AISTOR_SECRET_KEY}",
                        },
                        "core": {
                            "download_workers": 12,
                            "jobs_inflight_ttl_seconds": 900,
                        },
                    },
                    "jobs_scheduler": {
                        "rest": {"host": "0.0.0.0", "port": 63200, "reload": False},
                        "slurm": {
                            "base_url": "http://slurm:6820",
                            "api_version": "v0.0.43",
                            "user_name": "${SLURM_USER_NAME}",
                            "partition": None,
                            "job_name_prefix": "simulation",
                            "working_directory": "/tmp/workspace",
                            "stdout": "/tmp/workspace/%A/%a/simulation.out",
                            "stderr": "/tmp/workspace/%A/%a/simulation.err",
                            "docker_username": "${APPTAINER_DOCKER_USERNAME}",
                            "docker_password": "${APPTAINER_DOCKER_PASSWORD}",
                            "minio_endpoint": "http://aistor",
                            "minio_user": "${RTMF_AISTOR_ACCESS_KEY}",
                            "minio_password": "${RTMF_AISTOR_SECRET_KEY}",
                            "job_executor_user": "${JOB_EXECUTOR_USER}",
                            "job_executor_group": "${JOB_EXECUTOR_GROUP}",
                            "postgres_dsn": "${RTMF_JOBS_POSTGRES_DSN}",
                        },
                        "postgres": {"jobs_repository": {"dsn": "${RTMF_JOBS_POSTGRES_DSN}"}},
                    },
                    "simulators_repository": {
                        "rest": {"host": "0.0.0.0", "port": 10000},
                        "build_worker": {
                            "harbor_registry": "registry:80",
                            "harbor_project": "simulators",
                            "harbor_username": "${RTMF_HARBOR_USERNAME}",
                            "harbor_password": "${RTMF_HARBOR_PASSWORD}",
                            "buildkit_addr": "unix:///tmp/buildkit.sock",
                            "buildkit_platform": "linux/amd64",
                            "workspace_root": "/tmp/rtmf/build_worker",
                            "base_python_image_prefix": "base/python",
                            "base_java_image_prefix": "base/java",
                            "base_native_image": "base/native",
                        },
                        "core": {
                            "concurrent_builds": 1,
                            "builds_poll_interval": 0.4,
                            "storage_poll_interval": 1.0,
                        },
                        "postgres": {"simulators_repository": {"dsn": "${RTMF_SIMULATORS_REPOSITORY_POSTGRES_DSN}"}},
                    },
                    "matrix_generation": {
                        "rest": {"host": "0.0.0.0", "port": 8700},
                        "logging": {"level": "INFO"},
                        "aistor": {
                            "endpoint": "http://aistor",
                            "bucket": "tmp",
                            "secure": False,
                            "access_key": "${RTMF_AISTOR_ACCESS_KEY}",
                            "secret_key": "${RTMF_AISTOR_SECRET_KEY}",
                        },
                        "matrix": {"output_prefix": "matrix"},
                    },
                    "job_executor": {
                        "aistor": {
                            "endpoint": "http://aistor",
                            "bucket": "jobs-results",
                            "secure": False,
                            "access_key": "${RTMF_AISTOR_ACCESS_KEY}",
                            "secret_key": "${RTMF_AISTOR_SECRET_KEY}",
                        },
                        "executor": {"user": "${JOB_EXECUTOR_USER}", "group": "${JOB_EXECUTOR_GROUP}"},
                        "postgres": {"jobs_repository": {"dsn": "${RTMF_JOBS_POSTGRES_DSN}"}},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def _write_config(tmp_path, payload: dict) -> str:
    path = tmp_path / "rtmf.main.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _front_section() -> dict:
    return {
        "rest": {"host": "127.0.0.1", "port": 5000, "debug": False},
        "flask": {
            "secret_key": "dev",
            "simulation_models": "./sim_models/",
            "simulation_runs": "./sim_workspace/",
        },
    }


def _use_case_section() -> dict:
    return {
        "clients": {
            "jobs_scheduler": {"base_url": "http://jobs", "timeout_seconds": 10, "auth_token": ""},
            "simulators_repository": {"base_url": "http://sims", "timeout_seconds": 10, "auth_token": ""},
            "analytics": {"base_url": "http://analytics", "timeout_seconds": 10, "auth_token": ""},
            "visualization": {"base_url": "http://viz", "timeout_seconds": 10, "auth_token": ""},
            "parser": {"base_url": "http://parser", "timeout_seconds": 10, "auth_token": ""},
            "matrix_generator": {"base_url": "http://matrix", "timeout_seconds": 10},
            "system_discovery": {"base_url": "http://system-discovery", "timeout_seconds": 10, "auth_token": ""},
        },
        "aistor": {
            "endpoint": "http://aistor",
            "secure": False,
            "access_key": "minio",
            "secret_key": "password",
        },
        "adapters": {
            "system_discovery_aistor": {
                "endpoint": "http://aistor",
                "secure": False,
                "bucket": "system-discovery",
                "access_key": "minio",
                "secret_key": "password",
            },
        },
        "postgres": {"jobs_repository": {"dsn": "postgresql://jobs"}},
        "storage": {
            "system_discovery_training_results": {
                "endpoint": "http://aistor",
                "secure": False,
                "bucket": "system-discovery",
                "access_key": "minio",
                "secret_key": "password",
            }
        },
    }


@pytest.fixture
def config_env(monkeypatch, tmp_path):
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", _write_main_config(tmp_path))
    monkeypatch.setenv("RTMF_AISTOR_ACCESS_KEY", "minio")
    monkeypatch.setenv("RTMF_AISTOR_SECRET_KEY", "password")
    monkeypatch.setenv("RTMF_JOBS_POSTGRES_DSN", "postgresql://jobs")
    monkeypatch.setenv("SLURM_USER_NAME", "slurm")
    monkeypatch.setenv("APPTAINER_DOCKER_USERNAME", "docker")
    monkeypatch.setenv("APPTAINER_DOCKER_PASSWORD", "docker-password")
    monkeypatch.setenv("JOB_EXECUTOR_USER", "1000")
    monkeypatch.setenv("JOB_EXECUTOR_GROUP", "1000")
    monkeypatch.setenv("RTMF_HARBOR_USERNAME", "harbor")
    monkeypatch.setenv("RTMF_HARBOR_PASSWORD", "harbor-password")
    monkeypatch.setenv("RTMF_SIMULATORS_REPOSITORY_POSTGRES_DSN", "postgresql://simulators")


def test_analytics_config_loads(config_env) -> None:
    container = AnalyticsContainer()
    load_service_config_into_provider(container.config, service_name="analytics")
    assert container.config.rest.port() == 9500
    assert container.config.aistor.access_key() == "minio"
    assert container.config.core.download_workers() == 12
    assert container.config.core.jobs_inflight_ttl_seconds() == 900


def test_front_loads_from_cut_down_deployment_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        "RTMF_MAIN_CONFIGURATION_FILE",
        _write_config(
            tmp_path,
            {
                "services": {
                    "front": _front_section(),
                    "use_case": _use_case_section(),
                    "analytics": {"rest": {"port": "${UNRELATED_ANALYTICS_PORT}"}},
                },
            },
        ),
    )
    monkeypatch.delenv("UNRELATED_ANALYTICS_PORT", raising=False)

    front_config = load_front_config()
    use_case_container = UseCaseContainer()
    load_service_config_into_provider(use_case_container.config, service_name="use_case")

    assert front_config.rest.port() == 5000
    assert use_case_container.config.clients.analytics.base_url() == "http://analytics"


def test_analytics_loads_from_cut_down_deployment_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        "RTMF_MAIN_CONFIGURATION_FILE",
        _write_config(
            tmp_path,
            {
                "services": {
                    "analytics": {
                        "rest": {"host": "0.0.0.0", "port": 9500},
                        "aistor": {
                            "endpoint": "http://aistor",
                            "secure": False,
                            "bucket": "jobs-results",
                            "access_key": "minio",
                            "secret_key": "password",
                        },
                    },
                    "jobs_scheduler": {"slurm": {"user_name": "${UNRELATED_SLURM_USER}"}},
                }
            },
        ),
    )
    monkeypatch.delenv("UNRELATED_SLURM_USER", raising=False)
    container = AnalyticsContainer()

    load_service_config_into_provider(container.config, service_name="analytics")

    assert container.config.rest.port() == 9500


def test_jobs_scheduler_loads_from_cut_down_deployment_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        "RTMF_MAIN_CONFIGURATION_FILE",
        _write_config(
            tmp_path,
            {
                "services": {
                    "jobs_scheduler": {
                        "rest": {"host": "0.0.0.0", "port": 63200, "reload": False},
                        "slurm": {
                            "base_url": "http://slurm:6820",
                            "api_version": "v0.0.43",
                            "user_name": "slurm",
                            "partition": None,
                            "job_name_prefix": "simulation",
                            "working_directory": "/tmp/workspace",
                            "stdout": "/tmp/workspace/%A/%a/simulation.out",
                            "stderr": "/tmp/workspace/%A/%a/simulation.err",
                            "docker_username": "docker",
                            "docker_password": "docker-password",
                            "minio_endpoint": "http://aistor",
                            "minio_user": "minio",
                            "minio_password": "password",
                            "job_executor_user": "1000",
                            "job_executor_group": "1000",
                            "postgres_dsn": "postgresql://jobs",
                            "request_timeout_seconds": 10.0,
                            "token_timeout_seconds": 3600,
                        },
                        "postgres": {"jobs_repository": {"dsn": "postgresql://jobs"}},
                    },
                    "analytics": {"rest": {"port": "${UNRELATED_ANALYTICS_PORT}"}},
                }
            },
        ),
    )
    monkeypatch.delenv("UNRELATED_ANALYTICS_PORT", raising=False)

    container = create_jobs_scheduler_container()
    settings = container.settings()
    app = container.app()

    assert container.config.rest.port() == 63200
    assert settings.service_name == "jobs_scheduler"
    assert settings.rest.host == "0.0.0.0"
    assert settings.rest.port == 63200
    assert settings.rest.reload is False
    assert container.config.slurm.base_url() == "http://slurm:6820"
    assert container.config.slurm.api_version() == "v0.0.43"
    assert container.config.slurm.user_name() == "slurm"
    assert container.config.slurm.partition() is None
    assert container.config.slurm.job_name_prefix() == "simulation"
    assert container.config.slurm.working_directory() == "/tmp/workspace"
    assert container.config.slurm.stdout() == "/tmp/workspace/%A/%a/simulation.out"
    assert container.config.slurm.stderr() == "/tmp/workspace/%A/%a/simulation.err"
    assert container.config.slurm.docker_username() == "docker"
    assert container.config.slurm.docker_password() == "docker-password"
    assert container.config.slurm.minio_endpoint() == "http://aistor"
    assert container.config.slurm.minio_user() == "minio"
    assert container.config.slurm.minio_password() == "password"
    assert container.config.slurm.job_executor_user() == "1000"
    assert container.config.slurm.job_executor_group() == "1000"
    assert container.config.slurm.postgres_dsn() == "postgresql://jobs"
    assert container.config.postgres.jobs_repository.dsn() == "postgresql://jobs"
    assert app.title == "RTMF Jobs Scheduler Service"


def test_matrix_generation_loads_from_cut_down_deployment_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        "RTMF_MAIN_CONFIGURATION_FILE",
        _write_config(
            tmp_path,
            {
                "services": {
                    "matrix_generation": {
                        "rest": {"host": "0.0.0.0", "port": 8700},
                        "logging": {"level": "INFO"},
                        "aistor": {
                            "endpoint": "http://aistor",
                            "bucket": "tmp",
                            "secure": False,
                            "access_key": "minio",
                            "secret_key": "password",
                        },
                        "matrix": {"output_prefix": "matrix"},
                    },
                    "analytics": {"rest": {"port": "${UNRELATED_ANALYTICS_PORT}"}},
                }
            },
        ),
    )
    monkeypatch.delenv("UNRELATED_ANALYTICS_PORT", raising=False)

    container = create_matrix_container()

    assert container.config.rest.port() == 8700


def test_simulators_repository_loads_from_cut_down_deployment_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        "RTMF_MAIN_CONFIGURATION_FILE",
        _write_config(
            tmp_path,
            {
                "services": {
                    "simulators_repository": {
                        "rest": {"host": "0.0.0.0", "port": 10000},
                        "build_worker": {
                            "harbor_registry": "registry:80",
                            "harbor_project": "simulators",
                            "harbor_username": "harbor",
                            "harbor_password": "harbor-password",
                            "buildkit_addr": "unix:///tmp/buildkit.sock",
                            "buildkit_platform": "linux/amd64",
                            "workspace_root": "/tmp/rtmf/build_worker",
                            "base_python_image_prefix": "base/python",
                            "base_java_image_prefix": "base/java",
                            "base_native_image": "base/native",
                        },
                        "core": {
                            "concurrent_builds": 1,
                            "builds_poll_interval": 0.4,
                            "storage_poll_interval": 1.0,
                        },
                        "postgres": {"simulators_repository": {"dsn": "postgresql://simulators"}},
                    },
                    "analytics": {"rest": {"port": "${UNRELATED_ANALYTICS_PORT}"}},
                }
            },
        ),
    )
    monkeypatch.delenv("UNRELATED_ANALYTICS_PORT", raising=False)
    container = RepositoryServiceContainer()

    container.initialize()

    assert container.config.rest.port() == 10000


def test_analytics_config_does_not_require_unrelated_service_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", _write_main_config(tmp_path))
    monkeypatch.setenv("RTMF_AISTOR_ACCESS_KEY", "minio")
    monkeypatch.setenv("RTMF_AISTOR_SECRET_KEY", "password")
    monkeypatch.delenv("SLURM_USER_NAME", raising=False)
    monkeypatch.delenv("RTMF_HARBOR_USERNAME", raising=False)
    monkeypatch.delenv("JOB_EXECUTOR_USER", raising=False)
    container = AnalyticsContainer()

    load_service_config_into_provider(container.config, service_name="analytics")

    assert container.config.aistor.secret_key() == "password"


def test_simulators_repository_config_loads(config_env) -> None:
    container = RepositoryServiceContainer()
    load_service_config_into_provider(container.config, service_name="simulators_repository")
    assert container.config.rest.port() == 10000
    assert container.config.build_worker.harbor_username() == "harbor"
    assert container.config.postgres.simulators_repository.dsn() == "postgresql://simulators"


def test_simulators_repository_config_does_not_require_minio(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", _write_main_config(tmp_path))
    monkeypatch.setenv("RTMF_HARBOR_USERNAME", "harbor")
    monkeypatch.setenv("RTMF_HARBOR_PASSWORD", "harbor-password")
    monkeypatch.setenv(
        "RTMF_SIMULATORS_REPOSITORY_POSTGRES_DSN",
        "postgresql://simulators",
    )
    monkeypatch.delenv("RTMF_AISTOR_ACCESS_KEY", raising=False)
    monkeypatch.delenv("RTMF_AISTOR_SECRET_KEY", raising=False)
    container = RepositoryServiceContainer()

    load_service_config_into_provider(container.config, service_name="simulators_repository")

    assert container.config.build_worker.harbor_username() == "harbor"


def test_front_and_use_case_configs_do_not_require_job_executor_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", _write_main_config(tmp_path))
    monkeypatch.setenv("RTMF_AISTOR_ACCESS_KEY", "minio")
    monkeypatch.setenv("RTMF_AISTOR_SECRET_KEY", "password")
    monkeypatch.setenv("RTMF_JOBS_POSTGRES_DSN", "postgresql://jobs")
    monkeypatch.delenv("JOB_EXECUTOR_USER", raising=False)
    monkeypatch.delenv("JOB_EXECUTOR_GROUP", raising=False)

    front_config = load_front_config()
    use_case_container = UseCaseContainer()
    load_service_config_into_provider(use_case_container.config, service_name="use_case")

    assert front_config.rest.port() == 5000
    assert use_case_container.config.aistor.access_key() == "minio"
    assert (
        use_case_container.config.adapters.system_discovery_aistor()[
            "bucket"
        ]
        == "system-discovery"
    )


def test_system_discovery_aistor_composition_resolves_dedicated_port_without_generic_aistor() -> None:
    container = UseCaseContainer()
    container.config.from_dict(
        {
            "adapters": {
                "system_discovery_aistor": {
                    "endpoint": "127.0.0.1:9000",
                    "secure": False,
                    "bucket": "system-discovery",
                    "access_key": "minio",
                    "secret_key": "password",
                }
            }
        }
    )
    container.system_discovery_aistor_adapter.minio_client.override(
        providers.Object(FakeMinio())
    )

    port = container.system_discovery_aistor()

    assert isinstance(port, SystemDiscoveryAIStorPort)
    assert isinstance(port, SystemDiscoveryAIStorAdapter)


def test_missing_dedicated_system_discovery_aistor_config_fails_clearly() -> None:
    container = UseCaseContainer()
    container.config.from_dict(
        {
            "aistor": {
                "endpoint": "127.0.0.1:9000",
                "secure": False,
                "access_key": "minio",
                "secret_key": "password",
            }
        }
    )

    with pytest.raises(DependencyInjectorError):
        container.system_discovery_aistor()


def test_no_system_discovery_settings_remain_under_generic_use_case_aistor() -> None:
    for filename in ("deployment.example.json", "rtmf.local.example.json"):
        payload = _shipped_config(filename)
        use_case_aistor = payload["services"]["use_case"]["aistor"]

        assert "system_discovery_simulations" not in use_case_aistor
        assert "bucket" not in use_case_aistor


def test_jobs_scheduler_container_config_loads(config_env) -> None:
    container = create_jobs_scheduler_container()
    assert container.config.rest.port() == 63200
    assert container.config.slurm.base_url() == "http://slurm:6820"
    assert container.config.slurm.postgres_dsn() == "postgresql://jobs"


def test_matrix_generation_container_config_loads(config_env) -> None:
    container = create_matrix_container()
    assert container.config.rest.port() == 8700
    assert container.config.matrix.output_prefix() == "matrix"


def test_job_executor_container_config_loads(config_env) -> None:
    container = create_job_executor_container()
    assert container.config.aistor.bucket() == "jobs-results"
    assert container.config.postgres.jobs_repository.dsn() == "postgresql://jobs"


def test_front_config_loads(config_env) -> None:
    config = load_front_config()
    assert config.rest.port() == 5000
    assert config.flask.secret_key() == "dev"


def test_local_development_config_template_loads_all_runnable_service_sections(monkeypatch) -> None:
    template = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "rtmf.local.example.json"
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", str(template))
    monkeypatch.setenv("RTMF_SESSION_TOKEN_PEPPER", "test-session-pepper")
    _set_keycloak_env(monkeypatch)

    for service_name in (
        "front",
        "use_case",
        "analytics",
        "jobs_scheduler",
        "matrix_generation",
        "simulators_repository",
        "visualization",
        "evaluator",
        "job_executor",
        "system_discovery",
    ):
        config = providers.Configuration(strict=True)
        load_service_config_into_provider(config, service_name=service_name)
        assert config() is not None


def test_local_development_config_supports_front_with_in_process_use_case(monkeypatch) -> None:
    template = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "rtmf.local.example.json"
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", str(template))
    monkeypatch.setenv("RTMF_SESSION_TOKEN_PEPPER", "test-session-pepper")
    _set_keycloak_env(monkeypatch)

    front_config = load_front_config()
    use_case_container = UseCaseContainer()
    load_service_config_into_provider(use_case_container.config, service_name="use_case")

    assert front_config.rest.host() == "127.0.0.1"
    assert front_config.rest.debug() is True
    assert use_case_container.config.clients.jobs_scheduler.base_url() == "http://127.0.0.1:63200"


def test_use_case_config_loads(config_env) -> None:
    container = UseCaseContainer()
    load_service_config_into_provider(container.config, service_name="use_case")
    assert container.config.clients.analytics.base_url() == "http://analytics"
    assert container.config.clients.system_discovery.base_url() == "http://system-discovery"
    assert isinstance(container.system_discovery(), SystemDiscoveryPort)
    assert container.config.postgres.jobs_repository.dsn() == "postgresql://jobs"
    assert (
        container.config.storage.system_discovery_training_results.bucket()
        == "system-discovery"
    )


def test_missing_required_secret_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", _write_main_config(tmp_path))
    monkeypatch.setenv("RTMF_AISTOR_SECRET_KEY", "password")
    monkeypatch.setenv("RTMF_JOBS_POSTGRES_DSN", "postgresql://jobs")
    monkeypatch.setenv("SLURM_USER_NAME", "slurm")
    monkeypatch.setenv("APPTAINER_DOCKER_USERNAME", "docker")
    monkeypatch.setenv("APPTAINER_DOCKER_PASSWORD", "docker-password")
    monkeypatch.setenv("JOB_EXECUTOR_USER", "1000")
    monkeypatch.setenv("JOB_EXECUTOR_GROUP", "1000")
    monkeypatch.setenv("RTMF_HARBOR_USERNAME", "harbor")
    monkeypatch.setenv("RTMF_HARBOR_PASSWORD", "harbor-password")
    monkeypatch.setenv("RTMF_SIMULATORS_REPOSITORY_POSTGRES_DSN", "postgresql://simulators")
    monkeypatch.delenv("RTMF_AISTOR_ACCESS_KEY", raising=False)
    container = AnalyticsContainer()

    with pytest.raises(Exception, match="RTMF_AISTOR_ACCESS_KEY"):
        load_service_config_into_provider(container.config, service_name="analytics")


def _evaluator_env(monkeypatch) -> None:
    monkeypatch.setenv("RTMF_EVALUATOR_PORT", "63000")
    monkeypatch.setenv("RTMF_JOBS_SCHEDULER_BASE_URL", "http://jobs")
    monkeypatch.setenv("RTMF_JOBS_SCHEDULER_AUTH_TOKEN", "token")
    monkeypatch.setenv(
        "RTMF_SIMULATORS_REPOSITORY_BASE_URL", "http://sims"
    )
    monkeypatch.setenv("RTMF_SIMULATORS_REPOSITORY_AUTH_TOKEN", "token")
    monkeypatch.setenv("RTMF_ANALYTICS_BASE_URL", "http://analytics")
    monkeypatch.setenv("RTMF_ANALYTICS_AUTH_TOKEN", "token")
    monkeypatch.setenv("RTMF_PARSER_BASE_URL", "http://parser")
    monkeypatch.setenv("RTMF_PARSER_AUTH_TOKEN", "token")
    monkeypatch.setenv("RTMF_MATRIX_GENERATION_BASE_URL", "http://matrix")
    monkeypatch.setenv("RTMF_AISTOR_ENDPOINT", "http://aistor")
    monkeypatch.setenv("RTMF_AISTOR_ACCESS_KEY", "minio")
    monkeypatch.setenv("RTMF_AISTOR_SECRET_KEY", "password")
    monkeypatch.setenv("RTMF_JOBS_POSTGRES_DSN", "postgresql://jobs")


def _shipped_config(filename: str) -> dict:
    path = Path(__file__).resolve().parents[2] / "config" / filename
    if filename == "deployment.example.json":
        document = read_manifest(path)
        return ReferenceResolver(document).resolve(document["runtime"])
    return json.loads(path.read_text(encoding="utf-8"))


def _use_shipped_default_config(monkeypatch, tmp_path) -> None:
    """Load the canonical deployment manifest through its reference resolver."""
    path = tmp_path / "rtmf.main.json"
    path.write_text(json.dumps(_shipped_config("deployment.example.json")), encoding="utf-8")
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", str(path))
    _evaluator_env(monkeypatch)


def test_evaluator_container_wires_postgres_evaluations_store(
    config_env, monkeypatch, tmp_path
) -> None:
    from services.evaluator.composition.container import (
        ApplicationContainer as EvaluatorContainer,
    )

    _use_shipped_default_config(monkeypatch, tmp_path)
    container = EvaluatorContainer()
    load_service_config_into_provider(container.config, service_name="evaluator")

    store = container.evaluations_store_adapter.evaluations_store()

    assert isinstance(store, PostgresEvaluationsStore)
    assert store._dsn == "postgresql://jobs"


@pytest.mark.parametrize(
    "filename", ["deployment.example.json", "rtmf.local.example.json"]
)
def test_shipped_evaluator_config_uses_postgres_store(filename) -> None:
    config = _shipped_config(filename)
    evaluator = config["services"]["evaluator"]

    assert "aistor_evaluations" not in evaluator["clients"]
    assert evaluator["postgres"]["evaluations_store"]["dsn"]


@pytest.mark.parametrize(
    "filename", ["deployment.example.json", "rtmf.local.example.json"]
)
def test_shipped_use_case_config_wires_monitor_evaluations_store(filename) -> None:
    # The monitor needs its own handle on the evaluations store, so the
    # use_case section must carry the DSN too, not just the evaluator section.
    config = _shipped_config(filename)
    use_case = config["services"]["use_case"]

    assert use_case["postgres"]["evaluations_store"]["dsn"]


def test_use_case_container_wires_monitor_evaluations_store(
    config_env, monkeypatch, tmp_path
) -> None:
    from services.use_case.composition.build_usecases import UseCaseContainer

    _use_shipped_default_config(monkeypatch, tmp_path)
    _set_keycloak_env(monkeypatch)
    # Satisfy every env placeholder the shipped use_case config requires.
    for name in (
        "RTMF_AISTOR_ACCESS_KEY",
        "RTMF_AISTOR_ENDPOINT",
        "RTMF_AISTOR_SECRET_KEY",
        "RTMF_ANALYTICS_AUTH_TOKEN",
        "RTMF_ANALYTICS_BASE_URL",
        "RTMF_EVALUATOR_BASE_URL",
        "RTMF_JOBS_SCHEDULER_AUTH_TOKEN",
        "RTMF_JOBS_SCHEDULER_BASE_URL",
        "RTMF_MATRIX_GENERATION_BASE_URL",
        "RTMF_PARSER_AUTH_TOKEN",
        "RTMF_PARSER_BASE_URL",
        "RTMF_SESSION_TOKEN_PEPPER",
        "RTMF_SIMULATORS_REPOSITORY_AUTH_TOKEN",
        "RTMF_SIMULATORS_REPOSITORY_BASE_URL",
        "RTMF_SYSTEM_DISCOVERY_AUTH_TOKEN",
        "RTMF_SYSTEM_DISCOVERY_BASE_URL",
        "RTMF_VISUALIZATION_AUTH_TOKEN",
        "RTMF_VISUALIZATION_BASE_URL",
    ):
        monkeypatch.setenv(name, "test-value")
    container = UseCaseContainer()
    load_service_config_into_provider(container.config, service_name="use_case")

    store = container.evaluations_store()

    assert isinstance(store, PostgresEvaluationsStore)
    assert store._dsn == "postgresql://jobs"
