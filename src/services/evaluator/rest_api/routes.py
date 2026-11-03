from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from services.evaluator.core.errors import (
    EvaluationNotComplete,
    EvaluationNotFound,
    EvaluatorError,
)
from services.evaluator.core.ports import EvaluatorPort
from services.evaluator.rest_api.schemas import (
    EvaluateResponseSchema,
    EvaluationProgressResponseSchema,
    EvaluationResultResponseSchema,
    EvaluationStatusResponseSchema,
    EvaluationSummarySchema,
    ListEvaluationsResponseSchema,
)


def create_router(port: EvaluatorPort) -> APIRouter:
    router = APIRouter(prefix="/evaluations", tags=["evaluations"])

    @router.post("/", response_model=EvaluateResponseSchema)
    async def evaluate(
        simulator_id: str = Form(...),
        kmax: int = Form(30),
        epsilon: float = Form(1e-3),
        batch_size: int = Form(1),
        lhs_candidates: int = Form(1500),
        random_state: int = Form(42),
        number_of_repetitions: int = Form(128),
        aggregation: str | None = Form(None),
        config_file: UploadFile | None = File(None),
    ) -> EvaluateResponseSchema:
        problem = None
        if config_file is not None:
            content = await config_file.read()
            problem = json.loads(content)

        try:
            evaluation_id = port.evaluate(
                simulator_id,
                kmax=kmax,
                epsilon=epsilon,
                batch_size=batch_size,
                lhs_candidates=lhs_candidates,
                random_state=random_state,
                number_of_repetitions=number_of_repetitions,
                problem=problem,
                aggregation=aggregation,
            )
        except EvaluatorError as e:
            raise _to_http_exception(e)
        return EvaluateResponseSchema(evaluation_id=evaluation_id)

    @router.get("/", response_model=ListEvaluationsResponseSchema)
    def list_evaluations() -> ListEvaluationsResponseSchema:
        try:
            summaries = port.list_evaluations()
        except EvaluatorError as e:
            raise _to_http_exception(e)
        return ListEvaluationsResponseSchema(
            evaluations=[
                EvaluationSummarySchema(
                    evaluation_id=summary.evaluation_id,
                    simulator_id=summary.simulator_id,
                    status=summary.status,
                    created_at=summary.created_at,
                )
                for summary in summaries
            ]
        )

    @router.get(
        "/{evaluation_id}/status",
        response_model=EvaluationStatusResponseSchema,
    )
    def get_status(evaluation_id: str) -> EvaluationStatusResponseSchema:
        try:
            status_val = port.get_evaluation_status(evaluation_id)
        except EvaluatorError as e:
            raise _to_http_exception(e)
        return EvaluationStatusResponseSchema(
            evaluation_id=evaluation_id, status=status_val
        )

    @router.get(
        "/{evaluation_id}/progress",
        response_model=EvaluationProgressResponseSchema,
    )
    def get_progress(evaluation_id: str) -> EvaluationProgressResponseSchema:
        try:
            progress = port.get_evaluation_progress(evaluation_id)
        except EvaluatorError as e:
            raise _to_http_exception(e)
        return EvaluationProgressResponseSchema(
            evaluation_id=progress.evaluation_id,
            status=progress.status,
            stage=progress.stage,
            iteration=progress.iteration,
            kmax=progress.kmax,
            best_params=progress.best_params,
            best_value=progress.best_value,
            important_parameters=progress.important_parameters,
            ssbo_history=progress.ssbo_history,
            jobs_submitted=progress.jobs_submitted,
            jobs_by_stage=progress.jobs_by_stage,
        )

    @router.get(
        "/{evaluation_id}/results",
        response_model=EvaluationResultResponseSchema,
    )
    def get_results(
        evaluation_id: str,
    ) -> EvaluationResultResponseSchema:
        try:
            result = port.get_evaluation_results(evaluation_id)
        except EvaluatorError as e:
            raise _to_http_exception(e)
        return EvaluationResultResponseSchema(
            evaluation_id=result.evaluation_id,
            status=result.status,
            details=result.details,
        )

    return router


def _to_http_exception(error: EvaluatorError) -> HTTPException:
    if isinstance(error, EvaluationNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        )
    if isinstance(error, EvaluationNotComplete):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=str(error),
    )
