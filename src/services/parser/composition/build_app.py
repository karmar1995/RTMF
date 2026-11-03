from fastapi import FastAPI
from configuration.loader import load_service_config_into_provider
from services.parser.composition.container import ApplicationContainer
from services.parser.rest_api.app import create_app

def create_container() -> ApplicationContainer:
    container = ApplicationContainer()
    load_service_config_into_provider(
        container.config,
        service_name="parser",
    )
    return container

def build_app() -> FastAPI:
    container = create_container()
    app = create_app(parser_service=container.parser_service())
    # Let me fix the kwarg name here directly
    return app
