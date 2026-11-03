from __future__ import annotations

from fastapi import FastAPI

from configuration import load_service_config_into_provider
from services.jobs_scheduler.composition.container import Container


def create_container() -> Container:
    container = Container()
    load_service_config_into_provider(container.config, service_name="jobs_scheduler")
    return container


def create_app(container: Container | None = None) -> FastAPI:
    container = container or create_container()
    app = container.app()
    app.state.container = container
    return app
