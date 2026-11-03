from __future__ import annotations

from services.front.main import app
from use_case_contracts.dtos import (
    EvaluationMonitorEntry,
    MonitorEntries,
    SubJobInfo,
)
from use_case_contracts.messages import GetJobSubJobs, ListMonitorEntries
from conftest import _installed


class _FakeUseCases:
    """Stubs the monitor query, with a few simulations and evaluations."""

    def __init__(
        self,
        *,
        group_ids: list[str] | None = None,
        evaluations: list[EvaluationMonitorEntry] | None = None,
    ) -> None:
        self._group_ids = group_ids if group_ids is not None else ["sim-1", "sim-2"]
        self._evaluations = evaluations or []
        self.requested_messages: list[object] = []

    def handle(self, message):
        self.requested_messages.append(message)
        if isinstance(message, ListMonitorEntries):
            return MonitorEntries(
                simulation_group_ids=self._group_ids,
                evaluations=self._evaluations,
            )
        if isinstance(message, GetJobSubJobs):
            return [
                SubJobInfo(
                    sub_job_id="sub-1",
                    job_id=message.job_id,
                    status="running",
                    params=[],
                    repetition=0,
                )
            ]
        raise AssertionError(f"Unexpected message: {message!r}")


def _evaluation(**overrides) -> EvaluationMonitorEntry:
    base = {
        "evaluation_id": "eval-1",
        "model_name": "Model A",
        "state": "running",
        "status": "optimizing",
        "success": None,
        "progress": 25,
        "created_at": 1.0,
    }
    base.update(overrides)
    return EvaluationMonitorEntry(**base)


def test_monitor_shows_one_card_per_evaluation():
    usecases = _FakeUseCases(evaluations=[_evaluation()])
    with _installed(usecases):
        response = app.test_client().get("/simulation_monitor")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    # A single card, whatever the number of SSBO jobs behind it.
    assert body.count("Evaluation eval-1") == 1
    assert "Model A" in body


def test_monitor_links_evaluation_card_to_evaluation_detail():
    usecases = _FakeUseCases(evaluations=[_evaluation()])
    with _installed(usecases):
        response = app.test_client().get("/simulation_monitor")

    body = response.get_data(as_text=True)
    assert "/evaluations/eval-1" in body


def test_monitor_shows_evaluation_progress_in_running_column():
    usecases = _FakeUseCases(evaluations=[_evaluation(progress=42)])
    with _installed(usecases):
        response = app.test_client().get("/simulation_monitor")

    assert "42%" in response.get_data(as_text=True)


def test_monitor_places_evaluations_in_the_right_columns():
    usecases = _FakeUseCases(
        evaluations=[
            _evaluation(evaluation_id="queued-eval", state="waiting", status="queued", progress=None),
            _evaluation(evaluation_id="running-eval", state="running", progress=10),
            _evaluation(
                evaluation_id="done-eval",
                state="finished",
                status="success",
                success=True,
                progress=None,
            ),
            _evaluation(
                evaluation_id="failed-eval",
                state="finished",
                status="failed",
                success=False,
                progress=None,
            ),
        ]
    )
    with _installed(usecases):
        response = app.test_client().get("/simulation_monitor")

    body = response.get_data(as_text=True)
    # Assert each card lands in the column its state implies, not merely that
    # it is rendered somewhere.
    waiting = _column_body(body, "Waiting")
    running = _column_body(body, "Running")
    finished = _column_body(body, "Finished")
    assert "Evaluation queued-eval" in waiting
    assert "Evaluation running-eval" in running
    assert "10%" in running
    assert "Evaluation done-eval" in finished
    assert "Evaluation failed-eval" in finished
    # Terminal evaluations render as badges, not as their raw status.
    assert "Success" in finished and "Error" in finished
    # Nothing leaks into the wrong column.
    assert "Evaluation queued-eval" not in running
    assert "Evaluation running-eval" not in waiting


def _column_body(body: str, heading: str) -> str:
    start = body.index(f"<!-- {heading} -->")
    tail = body[start:]
    for other in ("Waiting", "Running", "Finished"):
        marker = f"<!-- {other} -->"
        if other != heading and marker in tail:
            tail = tail[: tail.index(marker)]
            break
    return tail


def test_monitor_keeps_simulations_alongside_evaluations():
    usecases = _FakeUseCases(
        group_ids=["sim-1"], evaluations=[_evaluation(evaluation_id="eval-1")]
    )
    with _installed(usecases):
        response = app.test_client().get("/simulation_monitor")

    body = response.get_data(as_text=True)
    assert "Simulation job sim-1" in body
    assert "Evaluation eval-1" in body


def test_monitor_does_not_query_raw_job_list():
    # The monitor must go through the combined query so evaluation jobs get
    # filtered out at the boundary.
    usecases = _FakeUseCases(evaluations=[_evaluation()])
    with _installed(usecases):
        app.test_client().get("/simulation_monitor")

    assert any(isinstance(m, ListMonitorEntries) for m in usecases.requested_messages)


def test_monitor_handles_empty_evaluation_list():
    usecases = _FakeUseCases(evaluations=[])
    with _installed(usecases):
        response = app.test_client().get("/simulation_monitor")

    assert response.status_code == 200
    assert "Simulation job sim-1" in response.get_data(as_text=True)
