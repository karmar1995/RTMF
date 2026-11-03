from __future__ import annotations

from dependency_injector import containers, providers
from minio import Minio

from adapters.aistor_matrix_uploader.matrix_uploader import AIStorMatrixUploader, _endpoint_host
from services.matrix_generation.core.ports import MatrixUploader


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

    matrix_uploader = providers.Singleton(
        AIStorMatrixUploader,
        endpoint=config.endpoint,
        access_key=config.access_key,
        secret_key=config.secret_key,
        secure=config.secure,
        client=minio_client,
    )


class AIStorAdapterRoot:
    def __init__(self, container: AIStorAdapterContainer) -> None:
        self._c = container

    def matrix_uploader(self) -> MatrixUploader:
        return self._c.matrix_uploader()
