from __future__ import annotations

from dependency_injector import containers, providers

from adapters.system_discovery_rest_adapter.adapter import RestSystemDiscoveryAdapter
from adapters.system_discovery_rest_adapter.client import SystemDiscoveryRestClient
from adapters.system_discovery_rest_adapter.config import SystemDiscoveryConfig
from use_case_contracts.ports import SystemDiscoveryPort


class SystemDiscoveryRestAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    system_discovery_config = providers.Factory(
        SystemDiscoveryConfig,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        auth_token=config.auth_token,
    )

    system_discovery_rest_client = providers.Singleton(
        SystemDiscoveryRestClient,
        config=system_discovery_config,
        http_client=None,
    )

    system_discovery_port = providers.Singleton(
        RestSystemDiscoveryAdapter,
        client=system_discovery_rest_client,
    )


class SystemDiscoveryRestAdapterRoot:
    def __init__(self, container: SystemDiscoveryRestAdapterContainer) -> None:
        self._c = container

    def system_discovery_port(self) -> SystemDiscoveryPort:
        return self._c.system_discovery_port()
