from __future__ import annotations

from dependency_injector import containers, providers

from services.analytics.core.details.analytics_service_controller import (
    AnalyticsServiceController,
    DEFAULT_DOWNLOAD_WORKERS,
    JOBS_INFLIGHT_TTL_SECONDS,
)
from use_case_contracts.ports import AnalyticsPort


class CoreContainer(containers.DeclarativeContainer):
    results_repository = providers.Dependency()
    download_workers = providers.Dependency(default=DEFAULT_DOWNLOAD_WORKERS)
    jobs_inflight_ttl_seconds = providers.Dependency(default=JOBS_INFLIGHT_TTL_SECONDS)

    analytics_service = providers.Singleton(
        AnalyticsServiceController,
        results_repository=results_repository,
        download_workers=download_workers,
        jobs_inflight_ttl_seconds=jobs_inflight_ttl_seconds,
    )


class CoreRoot:
    def __init__(self, container: CoreContainer) -> None:
        self._c = container

    def analytics_service(self) -> AnalyticsPort:
        return self._c.analytics_service()
