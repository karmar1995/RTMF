from __future__ import annotations

import uvicorn
from dependency_injector import containers, providers
from fastapi import FastAPI

from services.analytics.rest_api.api import create_app


class RESTAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration()
    analytics_service = providers.Dependency()

    app = providers.Singleton(
        create_app,
        analytics_port=analytics_service,
    )


class RESTAdapterRoot:
    def __init__(self, container: RESTAdapterContainer) -> None:
        self._c = container

    def app(self) -> FastAPI:
        return self._c.app()

    def run(self) -> None:
        uvicorn.run(
            self.app(),
            host=self._c.config.host(),
            port=int(self._c.config.port()),
        )
