from __future__ import annotations

from dependency_injector import containers, providers
from minio import Minio

from adapters.aistor_results_repository.details.results_repository import (
    AIStorResultsRepository,
    _endpoint_host,
)
from use_case_contracts.ports import ResultsRepositoryPort


class AIStorAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    endpoint_host = providers.Callable(_endpoint_host, config.endpoint)

    minio_client = providers.Singleton(
        Minio,
        endpoint_host,
        access_key=config.access_key,
        secret_key=config.secret_key,
        secure=config.secure,
    )

    results_repo = providers.Singleton(
        AIStorResultsRepository,
        endpoint=config.endpoint,
        access_key=config.access_key,
        secret_key=config.secret_key,
        secure=config.secure,
        bucket=config.bucket,
        client=minio_client,
    )

class AIStorAdapterRoot:
    def __init__(self, container: AIStorAdapterContainer) -> None:
        self._c = container

    def results_repository(self) -> ResultsRepositoryPort:
        return self._c.results_repo()
