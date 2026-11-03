from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from typing import Any

import pytest

from services.use_case.handlers.evaluations import handle_get_evaluation_details
from services.use_case.utils.plot_mapping import PlotMapping
from use_case_contracts.dtos import (
    EvaluationProgress,
    EvaluationResult,
    EvaluationSummary,
)
from use_case_contracts.errors import (
    ConflictError,
    ExternalServiceError,
    NotFoundError,
)
from use_case_contracts.messages import GetEvaluationDetails


_HISTORY = [
    {
        "iteration": 0,
        "best_value": 0.9,
        "new_point": [0.1, 0.2],
        "new_value": 0.9,
        "skipped": False,
    },
    {
        "iteration": 1,
        "best_value": 0.5,
        "new_point": [0.3, 0.4],
        "new_value": 0.5,
        "skipped": False,
    },
    {
        "iteration": 2,
        "best_value": 0.25,
        "new_point": [0.5, 0.6],
        "new_value": 0.25,
        "skipped": False,
    },
]


class _FakeEvaluator:
    def __init__(
        self,
        *,
        status: str = "optimizing",
        progress: EvaluationProgress | None = None,
        result: EvaluationResult | None = None,
        progress_error: Exception | None = None,
    ) -> None:
        self._status = status
        self._progress = progress
        self._result = result
        self._progress_error = progress_error

    def evaluate(self, *args: object, **kwargs: object) -> str:
        raise AssertionError("not used")

    def get_evaluation_status(self, evaluation_id: str) -> str:
        return self._status

    def get_evaluation_progress(self, evaluation_id: str) -> EvaluationProgress:
        if self._progress_error is not None:
            raise self._progress_error
        assert self._progress is not None
        return self._progress

    def get_evaluation_results(self, evaluation_id: str) -> EvaluationResult:
        assert self._result is not None
        return self._result

    def list_evaluations(self) -> list[EvaluationSummary]:
        return [
            EvaluationSummary(
                evaluation_id="eval-1",
                simulator_id="7",
                status=self._status,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        ]


class _FakeVisualization:
    def __init__(self, status: str = "done", error: Exception | None = None) -> None:
        self._status = status
        self._error = error
        self.rendered: list[bytes] = []

    def supported_plot_types(self) -> list[str]:
        return ["Line", "Scatter"]

    def render_plot(self, zip_csv_bytes: bytes, plot_spec: Any) -> str:
        if self._error is not None:
            raise self._error
        self.rendered.append(zip_csv_bytes)
        return f"plot-{len(self.rendered)}"

    def get_plot_status(self, plot_id: str) -> str:
        return self._status

    def get_plot_html(self, plot_id: str) -> str:
        return f'<div id="plot">{plot_id}</div>'


def _csv_rows(zip_bytes: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        name = archive.namelist()[0]
        return [
            line.split(",")
            for line in archive.read(name).decode().strip().splitlines()
        ]


def _progress(**overrides: Any) -> EvaluationProgress:
    values = {
        "evaluation_id": "eval-1",
        "status": "optimizing",
        "stage": "optimizing",
        "iteration": 3,
        "kmax": 30,
        "best_params": {"x": 0.5},
        "best_value": 0.25,
        "important_parameters": ["x", "y"],
        "ssbo_history": _HISTORY,
        "jobs_submitted": 13,
        "jobs_by_stage": {"sensitivity": 1, "ssbo": 12},
    }
    values.update(overrides)
    return EvaluationProgress(**values)


def _details(evaluator: _FakeEvaluator, visualization: _FakeVisualization):
    return handle_get_evaluation_details(
        GetEvaluationDetails(evaluation_id="eval-1"),
        evaluator,  # type: ignore[arg-type]
        visualization,  # type: ignore[arg-type]
        PlotMapping(),
    )


class TestLiveEvaluationDetails:
    def test_running_evaluation_exposes_progress(self) -> None:
        details = _details(
            _FakeEvaluator(progress=_progress()), _FakeVisualization()
        )

        assert details.status == "optimizing"
        assert details.result is None
        assert details.progress is not None
        assert details.progress.iteration == 3
        assert details.progress.jobs_submitted == 13
        assert details.progress.jobs_by_stage == {"sensitivity": 1, "ssbo": 12}

    def test_running_evaluation_renders_convergence_plot(self) -> None:
        visualization = _FakeVisualization()

        details = _details(_FakeEvaluator(progress=_progress()), visualization)

        assert details.convergence_visualization.state.value == "ready"
        assert '<div id="plot">plot-1</div>' in (
            details.convergence_visualization.plot_html or ""
        )
        rows = _csv_rows(visualization.rendered[0])
        assert rows[0] == ["iteration", "best_value"]
        assert rows[1:] == [["0.0", "0.9"], ["1.0", "0.5"], ["2.0", "0.25"]]

    def test_running_evaluation_renders_exploration_scatter(self) -> None:
        visualization = _FakeVisualization()

        details = _details(_FakeEvaluator(progress=_progress()), visualization)

        assert details.exploration_visualization.state.value == "ready"
        rows = _csv_rows(visualization.rendered[1])
        # Two columns only: the scatter renderer treats the rest as extra series.
        assert rows[0] == ["x", "objective"]
        assert rows[1:] == [["0.1", "0.9"], ["0.3", "0.5"], ["0.5", "0.25"]]

    def test_exploration_skips_iterations_without_new_points(self) -> None:
        history = _HISTORY + [
            {"iteration": 3, "best_value": 0.25, "skipped": True},
        ]
        visualization = _FakeVisualization()

        _details(
            _FakeEvaluator(progress=_progress(ssbo_history=history)), visualization
        )

        rows = _csv_rows(visualization.rendered[1])
        assert len(rows) == 4  # header + three evaluated points

    def test_exploration_pairs_every_candidate_of_a_batch(self) -> None:
        # An SSBO iteration evaluates a batch, so the history stores parallel
        # point/value lists rather than a single pair.
        history = [
            {
                "iteration": 0,
                "best_value": 0.9,
                "new_points": [[0.1, 0.2], [0.3, 0.4]],
                "new_values": [0.9, 0.6],
                "skipped": False,
            }
        ]
        visualization = _FakeVisualization()

        _details(
            _FakeEvaluator(progress=_progress(ssbo_history=history)), visualization
        )

        rows = _csv_rows(visualization.rendered[1])
        assert rows[0] == ["x", "objective"]
        assert rows[1:] == [["0.1", "0.9"], ["0.3", "0.6"]]

    def test_exploration_reads_legacy_two_dimensional_record(self) -> None:
        # Rows written before parallel lists existed hold a 2-D batch plus a
        # single scalar belonging to the last candidate.
        history = [
            {
                "iteration": 0,
                "best_value": 0.9,
                "new_point": [[0.1, 0.2], [0.3, 0.4]],
                "new_value": 0.6,
                "skipped": False,
            }
        ]
        visualization = _FakeVisualization()

        _details(
            _FakeEvaluator(progress=_progress(ssbo_history=history)), visualization
        )

        rows = _csv_rows(visualization.rendered[1])
        assert rows[1:] == [["0.3", "0.6"]]

    def test_exploration_ignores_unusable_entries(self) -> None:
        history = [
            {"iteration": 0, "best_value": 0.9, "skipped": False},
            {"iteration": 1, "best_value": 0.8, "new_points": [], "new_values": [], "skipped": False},
            {"iteration": 2, "best_value": 0.7, "new_points": [[0.1]], "new_values": [], "skipped": False},
            {"iteration": 3, "best_value": 0.6, "new_points": [[0.2]], "new_values": [0.5], "skipped": False},
        ]
        visualization = _FakeVisualization()

        _details(
            _FakeEvaluator(progress=_progress(ssbo_history=history)), visualization
        )

        rows = _csv_rows(visualization.rendered[1])
        assert rows[1:] == [["0.2", "0.5"]]

    def test_no_plots_before_first_iteration(self) -> None:
        details = _details(
            _FakeEvaluator(
                progress=_progress(iteration=0, best_value=None, ssbo_history=[])
            ),
            _FakeVisualization(),
        )

        assert details.convergence_visualization.state.value == "not_ready"
        assert details.exploration_visualization.state.value == "not_ready"

    def test_growing_history_is_not_served_from_stale_cache(self) -> None:
        plots = PlotMapping()
        visualization = _FakeVisualization()
        evaluator = _FakeEvaluator(progress=_progress())

        first = handle_get_evaluation_details(
            GetEvaluationDetails(evaluation_id="eval-1"),
            evaluator,  # type: ignore[arg-type]
            visualization,  # type: ignore[arg-type]
            plots,
        )
        evaluator = _FakeEvaluator(
            progress=_progress(
                iteration=4,
                ssbo_history=_HISTORY + [
                    {
                        "iteration": 3,
                        "best_value": 0.1,
                        "new_point": [0.7, 0.8],
                        "new_value": 0.1,
                        "skipped": False,
                    }
                ],
            )
        )
        second = handle_get_evaluation_details(
            GetEvaluationDetails(evaluation_id="eval-1"),
            evaluator,  # type: ignore[arg-type]
            visualization,  # type: ignore[arg-type]
            plots,
        )

        assert first.convergence_visualization.plot_html != (
            second.convergence_visualization.plot_html
        )
        assert first.exploration_visualization.plot_html != (
            second.exploration_visualization.plot_html
        )


class TestTerminalEvaluationDetails:
    def test_successful_evaluation_falls_back_to_archived_history(self) -> None:
        result = EvaluationResult(
            evaluation_id="eval-1",
            status="success",
            details={
                "best_value": 0.25,
                "important_parameters": ["x"],
                "iterations": 3,
                "history": [
                    {"iteration": 0, "best_value": 0.9, "skipped": False},
                    {"iteration": 1, "best_value": 0.5, "skipped": False},
                    {"iteration": 2, "best_value": 0.25, "skipped": False},
                ],
            },
        )
        visualization = _FakeVisualization()

        details = _details(
            _FakeEvaluator(
                status="success",
                progress=_progress(status="success", ssbo_history=[]),
                result=result,
            ),
            visualization,
        )

        assert details.result is not None
        assert details.convergence_visualization.state.value == "ready"
        rows = _csv_rows(visualization.rendered[0])
        assert rows[1:] == [["0.0", "0.9"], ["1.0", "0.5"], ["2.0", "0.25"]]
        # The archived history carries no new_point, so no scatter is possible.
        assert details.exploration_visualization.state.value == "not_ready"

    def test_missing_progress_does_not_break_details(self) -> None:
        details = _details(
            _FakeEvaluator(
                progress_error=NotFoundError("no such evaluation"),
                result=EvaluationResult(
                    evaluation_id="eval-1",
                    status="success",
                    details={
                        "best_value": 0.1,
                        "important_parameters": ["x"],
                        "history": [{"iteration": 0, "best_value": 0.1}],
                    },
                ),
                status="success",
            ),
            _FakeVisualization(),
        )

        assert details.progress is None
        assert details.convergence_visualization.state.value == "ready"

    @pytest.mark.parametrize(
        "error",
        [
            ConflictError("busy"),
            ExternalServiceError("down"),
            RuntimeError("unexpected"),
        ],
    )
    def test_progress_lookup_failures_are_tolerated(self, error: Exception) -> None:
        details = _details(
            _FakeEvaluator(progress_error=error), _FakeVisualization()
        )

        assert details.progress is None
        assert details.status == "optimizing"

    def test_visualization_failure_degrades_to_unavailable(self) -> None:
        details = _details(
            _FakeEvaluator(progress=_progress()),
            _FakeVisualization(error=ExternalServiceError("no workers")),
        )

        assert details.convergence_visualization.state.value == "unavailable"
        assert details.exploration_visualization.state.value == "unavailable"

    def test_pending_plot_is_reported_with_waiting_message(self) -> None:
        details = _details(
            _FakeEvaluator(progress=_progress()), _FakeVisualization(status="queued")
        )

        assert details.convergence_visualization.state.value == "pending"
        assert "queued" in details.convergence_visualization.waiting_message

    def test_failed_evaluation_keeps_error_visible(self) -> None:
        details = _details(
            _FakeEvaluator(
                status="failed",
                progress=_progress(status="failed", iteration=1, ssbo_history=[]),
                result=EvaluationResult(
                    evaluation_id="eval-1",
                    status="failed",
                    details={"error": "boom"},
                ),
            ),
            _FakeVisualization(),
        )

        assert details.status == "failed"
        assert details.result is not None
        assert details.result.details == {"error": "boom"}
