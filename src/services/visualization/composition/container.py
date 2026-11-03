from __future__ import annotations

from dependency_injector import containers, providers

from services.visualization.core.executor import VisualizationExecutor
from services.visualization.core.service import VisualizationService
from services.visualization.rest_api.app import create_app


class ApplicationContainer(containers.DeclarativeContainer):
    config = providers.Configuration(strict=True)

    executor = providers.Singleton(
        VisualizationExecutor,
        max_workers=config.executor.max_workers.as_int(),
        delete_after_return=config.executor.delete_after_return,
        cleanup_interval=config.executor.cleanup_interval.as_int(),
    )

    visualization_service = providers.Singleton(
        VisualizationService,
        executor=executor,
    )

    visualization_port = visualization_service

    app = providers.Factory(
        create_app,
        visualization=visualization_port,
    )
