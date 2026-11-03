from dependency_injector import providers
import uvicorn

from configuration import load_service_config_into_provider


def load_config() -> providers.Configuration:
    config = providers.Configuration(strict=True)
    load_service_config_into_provider(config, service_name="system_discovery")
    return config


def main() -> None:
    config = load_config()
    from services.system_discovery.app.main import app

    uvicorn.run(app, host=config.rest.host(), port=config.rest.port.as_int()())
