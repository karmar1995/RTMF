from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from services.matrix_generation.core.dto import (
    GenerateLinearCombinationsRequest,
    GenerateSensitivityAnalysisRequest,
    MatrixParameterDefinition,
    SensitivityAnalysisParameter,
    UploadMatrixRequest,
)
from services.matrix_generation.core.errors import (
    InvalidMatrixGenerationRequest,
    MatrixGenerationError,
    MatrixUploadFailed,
    SatelliCombinationsGenerationFailed,
    SensitivityAnalysisGenerationNotImplemented,
)
from services.matrix_generation.core.ports import MatrixGenerationPort
from services.matrix_generation.rest_api.schemas import (
    GenerateLinearCombinationsRequestSchema,
    GenerateSensitivityAnalysisRequestSchema,
    GeneratedMatrixFileResponseSchema,
    UploadMatrixRequestSchema,
)


def create_router(matrix_generation: MatrixGenerationPort) -> APIRouter:
    router = APIRouter(prefix="/matrices", tags=["matrices"])

    @router.post(
        "/linear-combinations",
        response_model=GeneratedMatrixFileResponseSchema,
    )
    def generate_linear_combinations(
        request: GenerateLinearCombinationsRequestSchema,
    ) -> GeneratedMatrixFileResponseSchema:
        core_request = GenerateLinearCombinationsRequest(
            matrix_id=request.matrix_id,
            repetitions=request.repetitions,
            parameter_definitions=[
                MatrixParameterDefinition(
                    name=parameter.name,
                    type=parameter.type,
                )
                for parameter in request.parameter_definitions
            ],
            fixed_params=request.fixed_params,
            sweep_params=request.sweep_params,
        )

        try:
            result = matrix_generation.generate_linear_combinations(core_request)
        except MatrixGenerationError as error:
            raise _to_http_exception(error)

        return GeneratedMatrixFileResponseSchema(matrix_url=result.matrix_url)

    @router.post(
        "/sensitivity-analysis",
        response_model=GeneratedMatrixFileResponseSchema,
    )
    def generate_sensitivity_analysis(
        request: GenerateSensitivityAnalysisRequestSchema,
    ) -> GeneratedMatrixFileResponseSchema:
        core_request = GenerateSensitivityAnalysisRequest(
            matrix_id=request.matrix_id,
            sample_size=request.sample_size,
            calc_second_order=request.calc_second_order,
            round_to_int=request.round_to_int,
            parameters=[
                SensitivityAnalysisParameter(
                    name=parameter.name,
                    lower_bound=parameter.lower_bound,
                    upper_bound=parameter.upper_bound,
                )
                for parameter in request.parameters
            ],
        )

        try:
            result = matrix_generation.generate_sensitivity_analysis(core_request)
        except MatrixGenerationError as error:
            raise _to_http_exception(error)

        return GeneratedMatrixFileResponseSchema(matrix_url=result.matrix_url)

    @router.post(
        "/satelli-combinations",
        response_model=GeneratedMatrixFileResponseSchema,
    )
    def generate_satelli_matrix_combinations(
        request: GenerateLinearCombinationsRequestSchema,
    ) -> GeneratedMatrixFileResponseSchema:
        core_request = GenerateLinearCombinationsRequest(
            matrix_id=request.matrix_id,
            repetitions=request.repetitions,
            parameter_definitions=[
                MatrixParameterDefinition(
                    name=parameter.name,
                    type=parameter.type,
                )
                for parameter in request.parameter_definitions
            ],
            fixed_params=request.fixed_params,
            sweep_params=request.sweep_params,
            sample_size=request.sample_size,
            seed=request.seed,
        )

        try:
            result = matrix_generation.generate_satelli_matrix_combinations(core_request)
        except MatrixGenerationError as error:
            raise _to_http_exception(error)

        return GeneratedMatrixFileResponseSchema(matrix_url=result.matrix_url)

    @router.post(
        "/upload",
        response_model=GeneratedMatrixFileResponseSchema,
    )
    def upload_matrix(
        request: UploadMatrixRequestSchema,
    ) -> GeneratedMatrixFileResponseSchema:
        core_request = UploadMatrixRequest(
            matrix_id=request.matrix_id,
            matrix_text=request.matrix_text,
        )

        try:
            result = matrix_generation.upload_matrix(core_request)
        except MatrixGenerationError as error:
            raise _to_http_exception(error)

        return GeneratedMatrixFileResponseSchema(matrix_url=result.matrix_url)

    return router

def _to_http_exception(error: MatrixGenerationError) -> HTTPException:
    if isinstance(error, InvalidMatrixGenerationRequest):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        )

    if isinstance(error, MatrixUploadFailed):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        )

    if isinstance(error, SensitivityAnalysisGenerationNotImplemented):
        return HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(error),
        )

    if isinstance(error, SatelliCombinationsGenerationFailed):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        )

    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=str(error),
    )