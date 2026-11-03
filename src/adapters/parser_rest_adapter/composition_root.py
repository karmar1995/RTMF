from __future__ import annotations

from dependency_injector import containers, providers

from adapters.parser_rest_adapter.config import ParserConfig
from adapters.parser_rest_adapter.parser_rest_adapter import RestParserAdapter
from adapters.parser_rest_adapter.rest_client import ParserRestClient
from use_case_contracts.ports import ParserPort


class ParserRestAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    parser_config = providers.Factory(
        ParserConfig,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        auth_token=config.auth_token,
    )

    parser_rest_client = providers.Singleton(
        ParserRestClient,
        config=parser_config,
        http_client=None,
    )

    parser_port = providers.Singleton(
        RestParserAdapter,
        client=parser_rest_client,
    )


class ParserRestAdapterRoot:
    def __init__(self, container: ParserRestAdapterContainer) -> None:
        self._c = container

    def parser_port(self) -> ParserPort:
        return self._c.parser_port()
