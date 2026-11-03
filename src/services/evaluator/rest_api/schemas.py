from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvaluateRequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulator_id: str
    kmax: int = 30
    epsilon: float = 1e-3
    batch_size: int = 1
    lhs_candidates: int = 1500
    random_state: int = 42


class EvaluateResponseSchema(BaseModel):
    evaluation_id: str


class EvaluationStatusResponseSchema(BaseModel):
    evaluation_id: str
    status: str


class EvaluationResultResponseSchema(BaseModel):
    evaluation_id: str
    status: str
    details: dict[str, Any] | None = None


class EvaluationSummarySchema(BaseModel):
    evaluation_id: str
    simulator_id: str
    status: str
    created_at: datetime | None = None


class EvaluationProgressResponseSchema(BaseModel):
    evaluation_id: str
    status: str
    stage: str | None = None
    iteration: int = 0
    kmax: int = 0
    best_params: dict[str, float | int] | None = None
    best_value: float | None = None
    important_parameters: list[str] | None = None
    ssbo_history: list[dict[str, Any]] = Field(default_factory=list)
    jobs_submitted: int = 0
    jobs_by_stage: dict[str, int] = Field(default_factory=dict)


class ListEvaluationsResponseSchema(BaseModel):
    evaluations: list[EvaluationSummarySchema]
