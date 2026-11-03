from __future__ import annotations

from fastapi import APIRouter

from services.jobs_scheduler.core.errors import NotFoundError
from services.jobs_scheduler.core.jobs_scheduler_service import JobsSchedulerService
from services.jobs_scheduler.rest_api.error_mapping import to_http_exception
from services.jobs_scheduler.rest_api.models import (
    ErrorResponse,
    HealthResponse,
    JobInfoResponse,
    JobSummaryResponse,
    ScheduledBatchInfoResponse,
    SubJobStderrResponse,
    SubmitSimulationBatchRequest,
    SubJobInfoResponse,
    SubJobStdoutResponse,
)


def create_router(controller: JobsSchedulerService) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @router.post(
        "/jobs/submit",
        response_model=ScheduledBatchInfoResponse,
        responses={
            400: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def submit_job(request: SubmitSimulationBatchRequest) -> ScheduledBatchInfoResponse:
        try:
            result = controller.submit_simulation_batch(
                simulator_uri=request.simulator_uri,
                matrix_uri=request.matrix_uri,
                combinations=request.combinations,
                simulator_id=request.simulator_id,
            )
        except Exception as error:
            raise to_http_exception(error) from error
        return ScheduledBatchInfoResponse.model_validate(result)

    @router.get(
        "/jobs/{job_id}",
        response_model=JobInfoResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def get_job(job_id: str) -> JobInfoResponse:
        try:
            result = controller.get_job(job_id)
            if result is None:
                raise NotFoundError(f"Job '{job_id}' was not found.")
        except Exception as error:
            raise to_http_exception(error) from error
        return JobInfoResponse.model_validate(result)

    @router.get(
        "/jobs",
        response_model=list[JobSummaryResponse],
        responses={
            500: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def list_jobs() -> list[JobSummaryResponse]:
        try:
            result = controller.list_jobs()
        except Exception as error:
            raise to_http_exception(error) from error
        return [JobSummaryResponse.model_validate(item) for item in result]

    @router.get(
        "/jobs/{job_id}/sub-jobs",
        response_model=list[SubJobInfoResponse],
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def get_job_sub_jobs(job_id: str) -> list[SubJobInfoResponse]:
        try:
            result = controller.get_job_sub_jobs(job_id)
        except Exception as error:
            raise to_http_exception(error) from error
        return [SubJobInfoResponse.model_validate(item) for item in result]

    @router.get(
        "/jobs/{job_id}/sub-jobs/{sub_job_id}/stdout",
        response_model=SubJobStdoutResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def get_sub_job_stdout(job_id: str, sub_job_id: str) -> SubJobStdoutResponse:
        try:
            result = controller.get_sub_job_stdout(job_id, sub_job_id)
        except Exception as error:
            raise to_http_exception(error) from error
        return SubJobStdoutResponse(content=result)

    @router.get(
        "/jobs/{job_id}/sub-jobs/{sub_job_id}/stderr",
        response_model=SubJobStderrResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def get_sub_job_stderr(job_id: str, sub_job_id: str) -> SubJobStderrResponse:
        try:
            result = controller.get_sub_job_stderr(job_id, sub_job_id)
        except Exception as error:
            raise to_http_exception(error) from error
        return SubJobStderrResponse(content=result)

    return router
