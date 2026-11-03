from __future__ import annotations

from typing import Any

from use_case_contracts.dtos import (
    EvaluationProgress,
    EvaluationResult,
    EvaluationSummary,
)
from use_case_contracts.errors import ExternalServiceError


def parse_evaluation_id(payload: Any) -> str:
    if isinstance(payload, dict):
        value = payload.get("evaluation_id")
        if value:
            return str(value)
    raise ExternalServiceError("Evaluator service returned invalid evaluation submission payload")


def parse_status(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        value = payload.get("status")
        if value is not None:
            return str(value)
    raise ExternalServiceError("Evaluator service returned invalid status payload")


def parse_evaluation_result(payload: Any) -> EvaluationResult:
    if not isinstance(payload, dict):
        raise ExternalServiceError("Evaluator service returned invalid results payload")
    evaluation_id = payload.get("evaluation_id")
    if not evaluation_id:
        raise ExternalServiceError("Evaluator service results payload missing evaluation_id")
    details = payload.get("details")
    if details is not None and not isinstance(details, dict):
        raise ExternalServiceError("Evaluator service results payload has invalid details field")
    return EvaluationResult(
        evaluation_id=str(evaluation_id),
        status=str(payload.get("status", "")),
        details=details,
    )


def parse_evaluation_summaries(payload: Any) -> list[EvaluationSummary]:
    if not isinstance(payload, dict):
        raise ExternalServiceError("Evaluator service returned invalid evaluations list payload")
    evaluations = payload.get("evaluations")
    if not isinstance(evaluations, list):
        raise ExternalServiceError("Evaluator service evaluations list payload missing evaluations")
    summaries: list[EvaluationSummary] = []
    for item in evaluations:
        if not isinstance(item, dict):
            raise ExternalServiceError("Evaluator service evaluations list contains an invalid item")
        evaluation_id = item.get("evaluation_id")
        simulator_id = item.get("simulator_id", "")
        if not evaluation_id:
            raise ExternalServiceError("Evaluator service evaluation item missing evaluation_id")
        summaries.append(
            EvaluationSummary(
                evaluation_id=str(evaluation_id),
                simulator_id=str(simulator_id or ""),
                status=str(item.get("status", "")),
                created_at=_parse_datetime(item.get("created_at")),
            )
        )
    return summaries


def parse_evaluation_progress(payload: Any) -> EvaluationProgress:
    if not isinstance(payload, dict):
        raise ExternalServiceError("Evaluator service returned invalid progress payload")
    evaluation_id = payload.get("evaluation_id")
    if not evaluation_id:
        raise ExternalServiceError("Evaluator service progress payload missing evaluation_id")
    history = payload.get("ssbo_history")
    if history is None:
        history = []
    if not isinstance(history, list):
        raise ExternalServiceError("Evaluator service progress payload has invalid ssbo_history field")
    jobs_by_stage = payload.get("jobs_by_stage")
    if jobs_by_stage is None:
        jobs_by_stage = {}
    if not isinstance(jobs_by_stage, dict):
        raise ExternalServiceError("Evaluator service progress payload has invalid jobs_by_stage field")
    return EvaluationProgress(
        evaluation_id=str(evaluation_id),
        status=str(payload.get("status", "")),
        stage=payload.get("stage"),
        iteration=_parse_int(payload.get("iteration")),
        kmax=_parse_int(payload.get("kmax")),
        best_params=payload.get("best_params"),
        best_value=_parse_float(payload.get("best_value")),
        important_parameters=payload.get("important_parameters"),
        ssbo_history=history,
        jobs_submitted=_parse_int(payload.get("jobs_submitted")),
        jobs_by_stage={str(k): _parse_int(v) for k, v in jobs_by_stage.items()},
    )


def _parse_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            from datetime import datetime

            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value
