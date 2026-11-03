from __future__ import annotations

from fastapi import FastAPI

from configuration import load_service_config_into_provider
from services.matrix_generation.composition.container import ApplicationContainer


def create_container() -> ApplicationContainer:
    container = ApplicationContainer()
    load_service_config_into_provider(container.config, service_name="matrix_generation")
    return container


def build_app() -> FastAPI:
    container = create_container()
    return container.app()
