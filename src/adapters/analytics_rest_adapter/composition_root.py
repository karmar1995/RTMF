from __future__ import annotations

from dependency_injector import containers, providers

from adapters.analytics_rest_adapter.config import AnalyticsConfig
from adapters.analytics_rest_adapter.rest_adapter import RestAnalyticsAdapter
from use_case_contracts.ports import AnalyticsPort


class AnalyticsRestAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    analytics_config = providers.Factory(
        AnalyticsConfig,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        auth_token=config.auth_token,
    )

    analytics_port = providers.Singleton(
        RestAnalyticsAdapter,
        config=analytics_config,
        http_client=None,
    )


class AnalyticsRestAdapterRoot:
    def __init__(self, container: AnalyticsRestAdapterContainer) -> None:
        self._c = container

    def analytics_port(self) -> AnalyticsPort:
        return self._c.analytics_port()
