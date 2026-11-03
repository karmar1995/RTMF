from __future__ import annotations

from dependency_injector import containers, providers

from adapters.aistor_matrix_uploader.matrix_uploader import AIStorMatrixUploader
from services.matrix_generation.core.matrix_generation_service import MatrixGenerationService
from services.matrix_generation.rest_api.app import create_app


class ApplicationContainer(containers.DeclarativeContainer):
    config = providers.Configuration(strict=True)

    matrix_uploader = providers.Singleton(
        AIStorMatrixUploader,
        endpoint=config.aistor.endpoint,
        access_key=config.aistor.access_key,
        secret_key=config.aistor.secret_key,
        secure=config.aistor.secure,
    )

    matrix_generation_service = providers.Singleton(
        MatrixGenerationService,
        matrix_uploader=matrix_uploader,
        matrix_bucket=config.aistor.bucket,
        matrix_output_prefix=config.matrix.output_prefix,
    )
    matrix_generation_port = matrix_generation_service

    app = providers.Factory(
        create_app,
        matrix_generation=matrix_generation_port,
    )
