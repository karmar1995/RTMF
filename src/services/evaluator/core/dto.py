from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class EvaluateResponse:
    evaluation_id: str


@dataclass(frozen=True, slots=True)
class EvaluationResultResponse:
    evaluation_id: str
    status: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    evaluation_id: str
    simulator_id: str
    status: str
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EvaluationProgress:
    """Live progress of an evaluation, valid while it is still running.

    Every field is optional because progress is derived from whatever the
    pipeline has reached so far; early stages report very little.
    """

    evaluation_id: str
    status: str
    stage: str | None = None
    iteration: int = 0
    kmax: int = 0
    best_params: dict[str, float | int] | None = None
    best_value: float | None = None
    important_parameters: list[str] | None = None
    ssbo_history: list[dict] = field(default_factory=list)
    jobs_submitted: int = 0
    jobs_by_stage: dict[str, int] = field(default_factory=dict)
