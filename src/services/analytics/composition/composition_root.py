from __future__ import annotations

from dependency_injector import containers, providers

from adapters.aistor_results_repository.composition_root import AIStorAdapterContainer
from configuration import load_service_config_into_provider
from services.analytics.core.composition_root import CoreContainer
from services.analytics.rest_api.composition_root import (
    RESTAdapterContainer,
    RESTAdapterRoot,
)
from use_case_contracts.ports import AnalyticsPort


class ApplicationContainer(containers.DeclarativeContainer):
    config = providers.Configuration(strict=True)

    aistor_adapter = providers.Container(
        AIStorAdapterContainer,
        config=config.aistor,
    )

    core = providers.Container(
        CoreContainer,
        results_repository=aistor_adapter.results_repo,
        download_workers=config.core.download_workers.as_int(),
        jobs_inflight_ttl_seconds=config.core.jobs_inflight_ttl_seconds.as_int(),
    )

    rest_adapter = providers.Container(
        RESTAdapterContainer,
        config=config.rest,
        analytics_service=core.analytics_service,
    )

    analytics_service = core.analytics_service


class CompositionRoot:
    def __init__(self, container: ApplicationContainer) -> None:
        self._c = container

    def analytics_service(self) -> AnalyticsPort:
        return self._c.analytics_service()

    def rest_adapter(self) -> RESTAdapterRoot:
        return RESTAdapterRoot(self._c.rest_adapter)

    def run(self) -> None:
        self.rest_adapter().run()


def build_app() -> CompositionRoot:
    appContainer = ApplicationContainer()
    load_service_config_into_provider(appContainer.config, service_name="analytics")
    appRoot = CompositionRoot(appContainer)
    return appRoot
