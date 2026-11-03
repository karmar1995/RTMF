from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from use_case_contracts.dtos import ParameterValues, ResultRef
from use_case_contracts.errors import JobsRepositoryError
from use_case_contracts.ports import AnalyticsPort
from services.analytics.rest_api.schemas import (
    ConstantParameter,
    EmptyResponse,
    ErrorResponse,
    InitializeJobRequest,
    JobResultsErrorResponse,
    MergeSeriesRequest,
    MonteCarloFilteringRequest,
    MonteCarloFilteringResponse,
    MonteCarloFilteringRunResponse,
    MonteCarloFilteringStatisticResponse,
    ParameterDefinition,
    ParameterValuesResponse,
    PrepareSeriesRequest,
    SensitivityAnalysisRequest,
    SensitivityAnalysisResponse,
    SeriesIdResponse,
    StatisticsResponse,
    StatusResponse,
)

T = TypeVar("T")


def create_app(analytics_port: AnalyticsPort) -> FastAPI:
    app = FastAPI(title="RTMF Analytics Service")
    register_routes(app, analytics_port)
    return app


def register_routes(app: FastAPI, analytics_port: AnalyticsPort) -> None:
    @app.post(
        "/jobs/{job_id}/initialize",
        response_model=EmptyResponse,
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def initialize_job(job_id: str, request: InitializeJobRequest) -> EmptyResponse:
        handle_request(
            lambda: analytics_port.initialize_job(
                job_id=job_id,
                job_root_url=request.job_root_url,
                results_urls=[
                    ResultRef(sub_job_id="", url=result_url)
                    for result_url in request.results_urls
                ],
                input_parameters=parameter_definitions_to_tuples(request.input_parameters),
                output_parameters=parameter_definitions_to_tuples(request.output_parameters),
            )
        )
        return EmptyResponse()

    @app.get(
        "/jobs/{job_id}/status",
        response_model=StatusResponse,
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def job_results_status(job_id: str) -> StatusResponse:
        status = handle_request(lambda: analytics_port.job_results_status(job_id))
        return StatusResponse(status=status)

    @app.get(
        "/jobs/{job_id}/results-error",
        response_model=JobResultsErrorResponse,
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def job_results_error(job_id: str) -> JobResultsErrorResponse:
        message = handle_request(lambda: analytics_port.job_results_error(job_id))
        return JobResultsErrorResponse(message=message)

    @app.post(
        "/jobs/{job_id}/retry",
        response_model=EmptyResponse,
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def retry_job_results(job_id: str, request: InitializeJobRequest) -> EmptyResponse:
        handle_request(
            lambda: analytics_port.retry_job_results(
                job_id=job_id,
                job_root_url=request.job_root_url,
                results_urls=[
                    ResultRef(sub_job_id="", url=result_url)
                    for result_url in request.results_urls
                ],
                input_parameters=parameter_definitions_to_tuples(request.input_parameters),
                output_parameters=parameter_definitions_to_tuples(request.output_parameters),
            )
        )
        return EmptyResponse()

    @app.get(
        "/jobs/{job_id}/input-parameters/values",
        response_model=list[ParameterValuesResponse] | None,
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def input_parameters_values(job_id: str) -> list[ParameterValuesResponse] | None:
        values = handle_request(lambda: analytics_port.input_parameters_values(job_id))
        if values is None:
            return None
        return parameter_values_to_response(values)

    @app.get(
        "/jobs/{job_id}/repetitions",
        response_model=list[int] | None,
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def repetitions(job_id: str) -> list[int] | None:
        return handle_request(lambda: analytics_port.job_repetitions(job_id))

    @app.post(
        "/series/prepare",
        response_model=SeriesIdResponse | None,
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def prepare_series(request: PrepareSeriesRequest) -> SeriesIdResponse | None:
        series_id = handle_request(
            lambda: analytics_port.prepare_series(
                job_id=request.job_id,
                x_param=request.x_param,
                y_param=request.y_param,
                constants=constant_parameters_to_tuples(request.constants),
                statistic=request.statistic,
            )
        )
        if series_id is None:
            return None
        return SeriesIdResponse(series_id=series_id)

    @app.post(
        "/multi-series/merge",
        response_model=SeriesIdResponse | None,
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def merge_series(request: MergeSeriesRequest) -> SeriesIdResponse | None:
        series_id = handle_request(
            lambda: analytics_port.merge_series(request.series_ids)
        )
        if series_id is None:
            return None
        return SeriesIdResponse(series_id=series_id)

    @app.get(
        "/series/{series_id}/status",
        response_model=StatusResponse,
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def series_status(series_id: str) -> StatusResponse:
        status = handle_request(lambda: analytics_port.get_series_status(series_id))
        return StatusResponse(status=status)

    @app.get(
        "/series/{series_id}/download",
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def download_series(series_id: str) -> Response:
        content = handle_request(lambda: analytics_port.download_series(series_id))
        headers = {
            "Content-Disposition": f'attachment; filename="{series_id}.bin"',
        }
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers=headers,
        )

    @app.post(
        "/sensitivity-analysis",
        response_model=SensitivityAnalysisResponse,
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def analyze_sensitivity(request: SensitivityAnalysisRequest) -> SensitivityAnalysisResponse:
        result = handle_request(
            lambda: analytics_port.analyze_sensitivity(
                csv_data=request.csv_data,
                problem=request.problem,
                n_real=request.n_real,
                output_names=request.output_names,
                results_urls=request.results_urls,
                aggregation=request.aggregation,
            )
        )
        return SensitivityAnalysisResponse(
            mean_data_csv=result.mean_data_csv,
            important_parameters=result.important_parameters,
            deterministic_indices_csv=result.deterministic_indices_csv,
            stochastic_indices_csv=result.stochastic_indices_csv,
        )

    @app.get(
        "/statistics",
        response_model=StatisticsResponse,
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def supported_statistics() -> StatisticsResponse:
        statistics = handle_request(analytics_port.supported_statistics)
        return StatisticsResponse(statistics=statistics)

    @app.post(
        "/monte-carlo-filtering",
        response_model=MonteCarloFilteringResponse,
        responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    def analyze_monte_carlo_filtering(
        request: MonteCarloFilteringRequest,
    ) -> MonteCarloFilteringResponse:
        result = handle_request(
            lambda: analytics_port.analyze_monte_carlo_filtering(
                csv_data=request.csv_data,
                problem=request.problem,
                output_column=request.output_column,
                threshold=request.threshold,
                direction=request.direction,
                results_urls=request.results_urls,
                aggregation=request.aggregation,
                alpha=request.alpha,
                output_aggregations=request.output_aggregations,
                run_output_columns=request.run_output_columns,
            )
        )
        return MonteCarloFilteringResponse(
            output_column=result.output_column,
            threshold=result.threshold,
            direction=result.direction,
            aggregation=result.aggregation,
            behavioural_count=result.behavioural_count,
            non_behavioural_count=result.non_behavioural_count,
            runs=[
                MonteCarloFilteringRunResponse(
                    index=run.index,
                    behavioural=run.behavioural,
                    parameters=run.parameters,
                    outputs=run.outputs,
                )
                for run in result.runs
            ],
            parameters=[
                MonteCarloFilteringStatisticResponse(
                    parameter=statistic.parameter,
                    d_statistic=statistic.d_statistic,
                    p_value=statistic.p_value,
                    reject_h0=statistic.reject_h0,
                    behavioural_samples=statistic.behavioural_samples,
                    non_behavioural_samples=statistic.non_behavioural_samples,
                    behavioural_ecdf_x=statistic.behavioural_ecdf_x,
                    behavioural_ecdf_y=statistic.behavioural_ecdf_y,
                    non_behavioural_ecdf_x=statistic.non_behavioural_ecdf_x,
                    non_behavioural_ecdf_y=statistic.non_behavioural_ecdf_y,
                )
                for statistic in result.parameters
            ],
        )


def handle_request(action: Callable[[], T]) -> T:
    try:
        return action()
    except (JobsRepositoryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc


def parameter_definitions_to_tuples(
    definitions: list[ParameterDefinition],
) -> list[tuple[str, str]]:
    return [(definition.name, definition.type) for definition in definitions]


def constant_parameters_to_tuples(
    parameters: list[ConstantParameter],
) -> list[tuple[str, str]]:
    return [(parameter.name, parameter.value) for parameter in parameters]


def parameter_values_to_response(
    values: list[ParameterValues],
) -> list[ParameterValuesResponse]:
    return [ParameterValuesResponse(name=value.name, value=value.value) for value in values]
