from __future__ import annotations

from dependency_injector import containers, providers

from adapters.matrix_generator_rest_adapter.config import MatrixGeneratorAdapterConfig
from adapters.matrix_generator_rest_adapter.matrix_generator_rest_adapter import MatrixGeneratorRestAdapter
from use_case_contracts.ports import MatrixGenerationPort


class MatrixGeneratorAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    matrix_generation_port = providers.Singleton(
        MatrixGeneratorRestAdapter,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        http_client=None,
        logger=None,
    )


def build_matrix_generation_port(
    config: MatrixGeneratorAdapterConfig,
) -> MatrixGenerationPort:
    container = MatrixGeneratorAdapterContainer()
    container.config.from_dict(
        {
            "base_url": config.base_url,
            "timeout_seconds": config.timeout_seconds,
        }
    )
    return container.matrix_generation_port()
