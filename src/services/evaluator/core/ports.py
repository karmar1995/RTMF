from __future__ import annotations

from typing import Any, Protocol

from services.evaluator.core.dto import (
    EvaluationProgress,
    EvaluationResultResponse,
    EvaluationSummary,
    EvaluateResponse,
)


class EvaluatorPort(Protocol):
    def evaluate(
        self,
        simulator_id: str,
        *,
        kmax: int = 30,
        epsilon: float = 1e-3,
        batch_size: int = 1,
        lhs_candidates: int = 1500,
        random_state: int = 42,
        number_of_repetitions: int = 128,
        problem: dict | None = None,
        aggregation: str | None = None,
    ) -> str: ...

    def get_evaluation_status(self, evaluation_id: str) -> str: ...

    def get_evaluation_progress(self, evaluation_id: str) -> EvaluationProgress: ...

    def get_evaluation_results(
        self, evaluation_id: str
    ) -> EvaluationResultResponse: ...

    def list_evaluations(self) -> list[EvaluationSummary]: ...


class EvaluationsStorePort(Protocol):
    def load_all(self) -> dict[str, dict[str, Any]]: ...

    def save(self, evaluation_id: str, data: dict[str, Any]) -> None: ...

    def load(self, evaluation_id: str) -> dict[str, Any] | None: ...

    def update_progress(
        self,
        evaluation_id: str,
        *,
        status: str,
        stage: str | None,
        iteration: int,
        best_value: float | None,
        ssbo_history: list[dict],
    ) -> None: ...

    def record_job(
        self,
        evaluation_id: str,
        job_id: str,
        *,
        stage: str,
        iteration: int = 0,
    ) -> None: ...

    def job_counts(self, evaluation_id: str) -> dict[str, int]: ...
