from __future__ import annotations

from dependency_injector import containers, providers
from minio import Minio

from adapters.system_discovery_aistor_adapter.adapter import (
    SystemDiscoveryAIStorAdapter,
)
from adapters.system_discovery_aistor_adapter.client import SystemDiscoveryAIStorClient
from adapters.system_discovery_aistor_adapter.client.storage_client import _endpoint_host
from adapters.system_discovery_aistor_adapter.config import SystemDiscoveryAIStorConfig
from use_case_contracts.ports import SystemDiscoveryAIStorPort


class SystemDiscoveryAIStorAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    system_discovery_aistor_config = providers.Factory(
        SystemDiscoveryAIStorConfig,
        endpoint=config.endpoint,
        secure=config.secure,
        access_key=config.access_key,
        secret_key=config.secret_key,
        system_discovery_results_bucket=config.bucket,
    )

    endpoint_host = providers.Callable(_endpoint_host, config.endpoint)

    minio_client = providers.Singleton(
        Minio,
        endpoint_host,
        access_key=config.access_key,
        secret_key=config.secret_key,
        secure=config.secure,
    )

    system_discovery_aistor_client = providers.Singleton(
        SystemDiscoveryAIStorClient,
        config=system_discovery_aistor_config,
        client=minio_client,
    )

    system_discovery_aistor_port = providers.Singleton(
        SystemDiscoveryAIStorAdapter,
        client=system_discovery_aistor_client,
    )


class SystemDiscoveryAIStorAdapterRoot:
    def __init__(self, container: SystemDiscoveryAIStorAdapterContainer) -> None:
        self._c = container

    def system_discovery_aistor_port(self) -> SystemDiscoveryAIStorPort:
        return self._c.system_discovery_aistor_port()
