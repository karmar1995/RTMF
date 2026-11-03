from __future__ import annotations

from dependency_injector import containers, providers

from use_case_contracts.ports import VisualizationPort
from adapters.visualization_rest_adapter.config import VisualizationConfig
from adapters.visualization_rest_adapter.details.rest_visualization_adapter import (
    RestVisualizationAdapter,
)


class VisualizationRestAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    visualization_config = providers.Factory(
        VisualizationConfig,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        auth_token=config.auth_token,
    )

    visualization_port = providers.Singleton(
        RestVisualizationAdapter,
        config=visualization_config,
        http_client=None,
    )


class VisualizationRestAdapterRoot:
    def __init__(self, container: VisualizationRestAdapterContainer) -> None:
        self._c = container

    def visualization_port(self) -> VisualizationPort:
        return self._c.visualization_port()
