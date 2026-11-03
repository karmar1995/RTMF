from __future__ import annotations

import pytest
from dependency_injector import providers

from adapters.aistor_results_repository.composition_root import AIStorAdapterContainer
from adapters.system_discovery_aistor_adapter import (
    SystemDiscoveryAIStorConfigurationError,
    SystemDiscoveryAIStorAdapterContainer,
    SystemDiscoveryAIStorInvalidObjectKeyError,
)
from use_case_contracts.ports import SystemDiscoveryAIStorPort


class FakeMinio:
    def __init__(self) -> None:
        self.objects = {}
        self.bucket_checks = []
        self.puts = []
        self.gets = []

    def bucket_exists(self, bucket: str) -> bool:
        self.bucket_checks.append(bucket)
        return True

    def put_object(self, bucket, key, data, length, content_type):
        content = data.read()
        self.puts.append((bucket, key, content, length, content_type))
        self.objects[(bucket, key)] = content
        return object()

    def get_object(self, bucket, key):
        self.gets.append((bucket, key))
        return FakeResponse(self.objects[(bucket, key)])


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self.closed = False
        self.released = False

    def read(self) -> bytes:
        return self._content

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


def test_system_discovery_aistor_adapter_implements_dedicated_port() -> None:
    container, _fake = _container()

    port = container.system_discovery_aistor_port()

    assert isinstance(port, SystemDiscoveryAIStorPort)


def test_upload_and_download_use_dedicated_bucket_key_and_preserve_zip_bytes() -> None:
    container, fake = _container(bucket="sd-results")
    port = container.system_discovery_aistor_port()

    stored = port.upload_results_archive("sim-1", b"raw-zip")
    downloaded = port.download_results_archive("sim-1")

    assert stored.simulation_id == "sim-1"
    assert stored.storage_reference == "system-discovery/simulations/sim-1/results.zip"
    assert fake.puts == [
        (
            "sd-results",
            "system-discovery/simulations/sim-1/results.zip",
            b"raw-zip",
            len(b"raw-zip"),
            "application/zip",
        )
    ]
    assert fake.gets == [
        ("sd-results", "system-discovery/simulations/sim-1/results.zip")
    ]
    assert downloaded == b"raw-zip"


@pytest.mark.parametrize("simulation_id", ["../bad", "bad/id", "", "."])
def test_unsafe_simulation_ids_do_not_escape_object_namespace(simulation_id: str) -> None:
    container, _fake = _container()
    port = container.system_discovery_aistor_port()

    with pytest.raises(SystemDiscoveryAIStorInvalidObjectKeyError):
        port.upload_results_archive(simulation_id, b"raw-zip")


def test_generic_aistor_adapter_does_not_implement_system_discovery_port() -> None:
    generic = AIStorAdapterContainer()
    generic.config.from_dict(
        {
            "endpoint": "127.0.0.1:9000",
            "secure": False,
            "bucket": "jobs-results",
            "access_key": "minio",
            "secret_key": "password",
        }
    )
    generic.minio_client.override(providers.Object(FakeMinio()))

    repo = generic.results_repo()

    assert not isinstance(repo, SystemDiscoveryAIStorPort)


def test_missing_bucket_configuration_fails_clearly() -> None:
    fake = FakeMinio()
    container = SystemDiscoveryAIStorAdapterContainer()
    container.config.from_dict(
        {
            "endpoint": "127.0.0.1:9000",
            "secure": False,
            "access_key": "minio",
            "secret_key": "password",
        }
    )
    container.minio_client.override(providers.Object(fake))
    try:
        container.system_discovery_aistor_port()
    except SystemDiscoveryAIStorConfigurationError as exc:
        assert "bucket" in str(exc)
    else:
        raise AssertionError("Expected missing bucket configuration to fail")


def _container(bucket: str = "system-discovery"):
    fake = FakeMinio()
    container = SystemDiscoveryAIStorAdapterContainer()
    container.config.from_dict(
        {
            "endpoint": "127.0.0.1:9000",
            "secure": False,
            "bucket": bucket,
            "access_key": "minio",
            "secret_key": "password",
        }
    )
    container.minio_client.override(providers.Object(fake))
    return container, fake
