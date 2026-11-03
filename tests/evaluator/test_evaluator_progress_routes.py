from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.evaluator.core.dto import (
    EvaluationProgress,
    EvaluationResultResponse,
    EvaluationSummary,
)
from services.evaluator.core.errors import EvaluationNotComplete, EvaluationNotFound
from services.evaluator.rest_api.routes import create_router


class _FakePort:
    def __init__(self, *, progress: EvaluationProgress | None = None) -> None:
        self._progress = progress

    def evaluate(self, *args: Any, **kwargs: Any) -> str:
        return "e" * 16

    def get_evaluation_status(self, evaluation_id: str) -> str:
        return "optimizing"

    def get_evaluation_progress(self, evaluation_id: str) -> EvaluationProgress:
        if self._progress is None:
            raise EvaluationNotFound(f"Evaluation '{evaluation_id}' not found")
        return self._progress

    def get_evaluation_results(self, evaluation_id: str) -> EvaluationResultResponse:
        raise EvaluationNotComplete(
            f"Evaluation '{evaluation_id}' not yet complete"
        )

    def list_evaluations(self) -> list[EvaluationSummary]:
        return []


def _client(port: _FakePort) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(port))  # type: ignore[arg-type]
    return TestClient(app)


def _progress(**overrides: Any) -> EvaluationProgress:
    values = {
        "evaluation_id": "e" * 16,
        "status": "optimizing",
        "stage": "optimizing",
        "iteration": 4,
        "kmax": 30,
        "best_params": {"x": 0.5},
        "best_value": 0.25,
        "important_parameters": ["x"],
        "ssbo_history": [
            {
                "iteration": 0,
                "best_value": 0.9,
                "new_point": [0.1],
                "new_value": 0.9,
            }
        ],
        "jobs_submitted": 13,
        "jobs_by_stage": {"sensitivity": 1, "ssbo": 12},
    }
    values.update(overrides)
    return EvaluationProgress(**values)


class TestProgressEndpoint:
    def test_progress_is_served_while_running(self) -> None:
        response = _client(_FakePort(progress=_progress())).get(
            f"/evaluations/{'e' * 16}/progress"
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["evaluation_id"] == "e" * 16
        assert payload["status"] == "optimizing"
        assert payload["stage"] == "optimizing"
        assert payload["iteration"] == 4
        assert payload["kmax"] == 30
        assert payload["best_params"] == {"x": 0.5}
        assert payload["best_value"] == 0.25
        assert payload["important_parameters"] == ["x"]
        assert payload["ssbo_history"][0]["new_point"] == [0.1]
        assert payload["jobs_submitted"] == 13
        assert payload["jobs_by_stage"] == {"sensitivity": 1, "ssbo": 12}

    def test_early_progress_uses_defaults(self) -> None:
        response = _client(
            _FakePort(
                progress=_progress(
                    stage=None,
                    iteration=0,
                    best_value=None,
                    best_params=None,
                    important_parameters=None,
                    ssbo_history=[],
                    jobs_submitted=0,
                    jobs_by_stage={},
                )
            )
        ).get(f"/evaluations/{'e' * 16}/progress")

        payload = response.json()
        assert payload["stage"] is None
        assert payload["best_value"] is None
        assert payload["ssbo_history"] == []
        assert payload["jobs_by_stage"] == {}

    def test_unknown_evaluation_returns_404(self) -> None:
        response = _client(_FakePort()).get(f"/evaluations/{'e' * 16}/progress")

        assert response.status_code == 404

    def test_incomplete_results_still_return_409(self) -> None:
        response = _client(_FakePort(progress=_progress())).get(
            f"/evaluations/{'e' * 16}/results"
        )

        assert response.status_code == 409

    def test_progress_does_not_conflict_with_status_route(self) -> None:
        client = _client(_FakePort(progress=_progress()))

        status = client.get(f"/evaluations/{'e' * 16}/status")
        progress = client.get(f"/evaluations/{'e' * 16}/progress")

        assert status.json() == {"evaluation_id": "e" * 16, "status": "optimizing"}
        assert progress.status_code == 200

    def test_evaluation_ids_with_special_characters_are_routed(self) -> None:
        response = _client(_FakePort()).get("/evaluations/a%2Fb/progress")

        assert response.status_code == 404


@pytest.mark.parametrize("suffix", ["status", "progress", "results"])
def test_route_is_registered_in_openapi_schema(suffix: str) -> None:
    paths = _client(_FakePort()).get("/openapi.json").json()["paths"]

    assert f"/evaluations/{{evaluation_id}}/{suffix}" in paths
