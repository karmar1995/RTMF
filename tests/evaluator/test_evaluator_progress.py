from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from services.evaluator.core.errors import EvaluationNotFound
from services.evaluator.core.evaluator_service import EvaluatorService


class _FakeStore:
    """In-memory stand-in for the PostgreSQL evaluations store."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.progress_updates: list[dict[str, Any]] = []
        self.jobs: list[tuple[str, str, str, int | None]] = []
        self.job_counts_result: dict[str, int] = {}
        self.fail_progress = False

    def load_all(self) -> dict[str, dict[str, Any]]:
        return {key: dict(value) for key, value in self.rows.items()}

    def load(self, evaluation_id: str) -> dict[str, Any] | None:
        row = self.rows.get(evaluation_id)
        return dict(row) if row is not None else None

    def save(self, evaluation_id: str, data: dict[str, Any]) -> None:
        merged = self.rows.get(evaluation_id, {})
        merged.update(data)
        merged.setdefault("created_at", 0.0)
        self.rows[evaluation_id] = merged

    def update_progress(
        self,
        evaluation_id: str,
        *,
        status: str,
        stage: str | None,
        iteration: int,
        best_value: float | None,
        ssbo_history: list[dict],
    ) -> None:
        self.progress_updates.append(
            {
                "evaluation_id": evaluation_id,
                "status": status,
                "stage": stage,
                "iteration": iteration,
                "best_value": best_value,
                "history_length": len(ssbo_history),
            }
        )
        if self.fail_progress:
            raise RuntimeError("database is down")
        row = self.rows.setdefault(evaluation_id, {})
        row["status"] = status
        row["stage"] = stage
        row["iteration"] = iteration
        row["best_value"] = best_value
        row["ssbo_history"] = list(ssbo_history)

    def record_job(
        self,
        evaluation_id: str,
        job_id: str,
        *,
        stage: str,
        iteration: int = 0,
    ) -> None:
        self.jobs.append((evaluation_id, job_id, stage, iteration))

    def job_counts(self, evaluation_id: str) -> dict[str, int]:
        return dict(self.job_counts_result)


def _service(
    store: _FakeStore | None, simulator_repository: Any | None = None
) -> EvaluatorService:
    return EvaluatorService(
        jobs_scheduler=None,  # type: ignore[arg-type]
        simulator_repository=simulator_repository,  # type: ignore[arg-type]
        jobs_repository=None,  # type: ignore[arg-type]
        results_repository=None,  # type: ignore[arg-type]
        analytics=None,  # type: ignore[arg-type]
        parser=None,  # type: ignore[arg-type]
        matrix_generator=None,  # type: ignore[arg-type]
        state_store=store,  # type: ignore[arg-type]
    )


def _running_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "status": "optimizing",
        "simulator_id": "7",
        "created_at": 1000.0,
        "stage": "optimizing",
        "iteration": 2,
        "kmax": 30,
        "best_value": 0.25,
        "best_params": {"x": 1.5},
        "important_parameters": ["x"],
        "ssbo_history": [
            {"iteration": 1, "best_value": 0.5, "new_point": [0.1], "new_value": 0.5},
            {"iteration": 2, "best_value": 0.25, "new_point": [0.2], "new_value": 0.25},
        ],
        "final_result": None,
        "error": None,
    }
    row.update(overrides)
    return row


class TestEvaluationStartup:
    def test_interrupted_evaluations_are_marked_failed_on_load(self) -> None:
        store = _FakeStore()
        store.rows["eval-1"] = _running_row()

        _service(store)

        row = store.rows["eval-1"]
        assert row["status"] == "failed"
        assert row["stage"] == "failed"
        assert row["error"] == "Interrupted by restart"
        assert row["final_result"]["details"]["error"] == "Interrupted by restart"
        # Progress recorded before the interruption is preserved.
        assert len(row["ssbo_history"]) == 2
        assert row["iteration"] == 2

    def test_successful_evaluations_are_left_untouched(self) -> None:
        store = _FakeStore()
        store.rows["eval-1"] = _running_row(
            status="success",
            final_result={"evaluation_id": "eval-1", "status": "success"},
        )

        _service(store)

        assert store.rows["eval-1"]["status"] == "success"
        assert store.rows["eval-1"]["error"] is None
        # Reconciliation must not overwrite a stage a finished run already set.
        assert store.rows["eval-1"]["stage"] == "optimizing"

    def test_failed_evaluations_are_not_reprocessed(self) -> None:
        store = _FakeStore()
        store.rows["eval-1"] = _running_row(status="failed", error="boom")

        _service(store)

        assert store.rows["eval-1"]["final_result"] is None


class TestEvaluationProgress:
    def test_progress_reports_live_state_from_store(self) -> None:
        store = _FakeStore()
        service = _service(store)
        store.rows["eval-1"] = _running_row()

        progress = service.get_evaluation_progress("eval-1")

        assert progress.evaluation_id == "eval-1"
        assert progress.status == "optimizing"
        assert progress.stage == "optimizing"
        assert progress.iteration == 2
        assert progress.kmax == 30
        assert progress.best_value == 0.25
        assert progress.important_parameters == ["x"]
        assert len(progress.ssbo_history) == 2

    def test_progress_includes_job_counts(self) -> None:
        store = _FakeStore()
        service = _service(store)
        store.rows["eval-1"] = _running_row()
        store.job_counts_result = {"sensitivity": 1, "ssbo": 12}

        progress = service.get_evaluation_progress("eval-1")

        assert progress.jobs_submitted == 13
        assert progress.jobs_by_stage == {"sensitivity": 1, "ssbo": 12}

    def test_progress_survives_failing_job_count_lookup(self) -> None:
        store = _FakeStore()
        service = _service(store)
        store.rows["eval-1"] = _running_row()

        def _boom(evaluation_id: str) -> dict[str, int]:
            raise RuntimeError("count query failed")

        store.job_counts = _boom  # type: ignore[assignment]

        progress = service.get_evaluation_progress("eval-1")

        assert progress.jobs_submitted == 0
        assert progress.iteration == 2

    def test_progress_for_early_stage_reports_no_iterations(self) -> None:
        store = _FakeStore()
        service = _service(store)
        store.rows["eval-1"] = {
            "status": "simulating",
            "simulator_id": "7",
            "created_at": 1.0,
            "stage": "simulating",
            "iteration": 0,
            "kmax": 30,
            "ssbo_history": [],
        }

        progress = service.get_evaluation_progress("eval-1")

        assert progress.status == "simulating"
        assert progress.iteration == 0
        assert progress.best_value is None
        assert progress.ssbo_history == []

    def test_progress_for_unknown_evaluation_raises(self) -> None:
        service = _service(_FakeStore())

        with pytest.raises(EvaluationNotFound):
            service.get_evaluation_progress("missing")

    def test_progress_falls_back_to_memory_without_store(self) -> None:
        # evaluate() runs the pipeline on a background thread, so hold it in
        # the simulator lookup: otherwise it can fail over to "failed" before
        # the assertion below reads the freshly queued state.
        release = threading.Event()
        service = _service(None, _BlockingSimulatorRepo(release))
        evaluation_id = service.evaluate("7", kmax=5)

        progress = service.get_evaluation_progress(evaluation_id)

        assert progress.status == "queued"
        assert progress.kmax == 5
        assert progress.iteration == 0
        assert progress.ssbo_history == []

        release.set()
        _await_terminal(service, evaluation_id)


class TestPublishProgress:
    def test_publish_progress_updates_store_and_derives_best_value(
        self,
    ) -> None:
        store = _FakeStore()
        service = _service(store)
        evaluation_id = service.evaluate("7", kmax=3)

        service._publish_progress(  # noqa: SLF001 - exercising the hot path
            evaluation_id,
            [
                {"iteration": 0, "best_value": 0.9},
                {"iteration": 1, "best_value": 0.4},
                {"iteration": 2, "best_value": 0.6},
            ],
        )

        update = store.progress_updates[-1]
        assert update["evaluation_id"] == evaluation_id
        assert update["iteration"] == 3
        # Best value is the minimum seen so far, not the latest one.
        assert update["best_value"] == 0.4
        assert update["history_length"] == 3
        assert store.rows[evaluation_id]["ssbo_history"][-1]["iteration"] == 2

    def test_publish_progress_survives_store_failure(self) -> None:
        store = _FakeStore()
        service = _service(store)
        evaluation_id = service.evaluate("7", kmax=3)
        store.fail_progress = True

        # A database hiccup must not abort the optimization.
        service._publish_progress(  # noqa: SLF001
            evaluation_id, [{"iteration": 0, "best_value": 0.5}]
        )
        assert store.progress_updates  # the attempt was made

        # Once the store recovers, the next flush persists the full history.
        store.fail_progress = False
        service._publish_progress(  # noqa: SLF001
            evaluation_id,
            [
                {"iteration": 0, "best_value": 0.5},
                {"iteration": 1, "best_value": 0.25},
            ],
        )
        progress = service.get_evaluation_progress(evaluation_id)
        assert len(progress.ssbo_history) == 2
        assert progress.iteration == 2
        assert progress.best_value == 0.25

    def test_publish_progress_ignores_unknown_evaluation(self) -> None:
        store = _FakeStore()
        service = _service(store)

        service._publish_progress("nope", [{"iteration": 0}])  # noqa: SLF001

        assert store.progress_updates == []

    def test_publish_progress_uses_store_state_when_not_owned(self) -> None:
        store = _FakeStore()
        service = _service(store)
        # A persisted row this instance does not hold in memory, e.g. an
        # evaluation whose pipeline outlived the owning process.
        store.rows["eval-1"] = _running_row()

        service._publish_progress(  # noqa: SLF001
            "eval-1",
            [
                {"iteration": 0, "best_value": 0.5},
                {"iteration": 1, "best_value": 0.25},
            ],
        )

        update = store.progress_updates[-1]
        assert update["status"] == "optimizing"
        assert update["stage"] == "optimizing"
        assert update["iteration"] == 2
        assert update["best_value"] == 0.25


class TestRecordJob:
    def test_record_job_is_never_fatal(self) -> None:
        store = _FakeStore()

        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("cannot insert job link")

        store.record_job = _boom  # type: ignore[assignment]
        service = _service(store)

        service._record_job("eval-1", "42", stage="ssbo", iteration=3)  # noqa: SLF001

    def test_record_job_without_store_is_a_noop(self) -> None:
        service = _service(None)

        service._record_job("eval-1", "42", stage="ssbo")  # noqa: SLF001


class _JobInfo:
    def __init__(self, status: str) -> None:
        self.status = status


class _FakeScheduler:
    def __init__(self, statuses: list[object]) -> None:
        self._statuses = list(statuses)
        self.calls = 0

    def get_job(self, job_id: str) -> object:
        self.calls += 1
        value = self._statuses.pop(0) if self._statuses else "successful"
        if isinstance(value, Exception):
            raise value
        return _JobInfo(str(value))


class TestAwaitJob:
    def _service_with_scheduler(self, statuses: list[object]):
        scheduler = _FakeScheduler(statuses)
        service = EvaluatorService(
            jobs_scheduler=scheduler,  # type: ignore[arg-type]
            simulator_repository=None,  # type: ignore[arg-type]
            jobs_repository=None,  # type: ignore[arg-type]
            results_repository=None,  # type: ignore[arg-type]
            analytics=None,  # type: ignore[arg-type]
            parser=None,  # type: ignore[arg-type]
            matrix_generator=None,  # type: ignore[arg-type]
            state_store=None,
        )
        return service, scheduler

    def test_returns_immediately_when_job_is_already_finished(self) -> None:
        service, scheduler = self._service_with_scheduler(["successful"])

        job_info = service._await_job("eval-1", "42", poll_interval=0)  # noqa: SLF001

        assert job_info.status == "successful"
        assert scheduler.calls == 1

    def test_polls_until_the_job_finishes(self) -> None:
        service, scheduler = self._service_with_scheduler(
            ["running", "pending", "success"]
        )

        job_info = service._await_job("eval-1", "42", poll_interval=0)  # noqa: SLF001

        assert job_info.status == "success"
        assert scheduler.calls == 3

    def test_transient_scheduler_error_is_retried(self) -> None:
        service, scheduler = self._service_with_scheduler(
            [RuntimeError("scheduler restarting"), "running", "successful"]
        )

        job_info = service._await_job("eval-1", "42", poll_interval=0)  # noqa: SLF001

        assert job_info.status == "successful"
        assert scheduler.calls == 3

    def test_failed_job_status_is_reported(self) -> None:
        service, _scheduler = self._service_with_scheduler(["failed"])

        job_info = service._await_job("eval-1", "42", poll_interval=0)  # noqa: SLF001

        assert job_info.status == "failed"


class TestTerminalStage:
    """`stage` must stop reporting an active phase once a run ends.

    Otherwise the detail page renders "optimizing" next to a finished or
    failed outcome badge, which reads as if work is still in flight.
    """

    def test_pipeline_failure_marks_stage_failed(self) -> None:
        store = _FakeStore()
        service = _service(store)

        # simulator_repository is None, so _run_pipeline raises on its first
        # statement and lands in the failure branch.
        evaluation_id = service.evaluate("7")

        _await_terminal(service, evaluation_id)
        row = store.rows[evaluation_id]

        assert row["status"] == "failed"
        assert row["stage"] == "failed"
        assert row["error"]

    def test_success_marks_stage_finished(self) -> None:
        store = _FakeStore()
        service = _pipeline_service(store)

        evaluation_id = service.evaluate("7", kmax=1)

        _await_terminal(service, evaluation_id)
        row = store.rows[evaluation_id]

        assert row["status"] == "success"
        # Not "optimizing": the run is over.
        assert row["stage"] == "finished"
        assert row["final_result"]["status"] == "success"

    def test_terminal_stage_never_regresses_to_a_running_phase(self) -> None:
        store = _FakeStore()
        service = _pipeline_service(store)

        evaluation_id = service.evaluate("7", kmax=1)
        _await_terminal(service, evaluation_id)

        # No later write may put the stage back to an in-flight value.
        assert store.rows[evaluation_id]["stage"] == "finished"


class TestJobIterations:
    """`evaluation_job.iteration` must be a real, zero-based optimizer iteration."""

    def test_ssbo_jobs_record_the_iteration_they_belong_to(self) -> None:
        store = _FakeStore()
        service = _pipeline_service(store)

        evaluation_id = service.evaluate("7", kmax=1)
        _await_terminal(service, evaluation_id)

        ssbo = [entry for entry in store.jobs if entry[2] == "ssbo"]
        sensitivity = [entry for entry in store.jobs if entry[2] == "sensitivity"]

        # The sensitivity phase has no iteration, so it records the neutral 0.
        assert sensitivity
        assert all(entry[3] == 0 for entry in sensitivity)

        iterations = [entry[3] for entry in ssbo]
        assert iterations, "no ssbo jobs recorded"
        # No -1 sentinel, within the optimizer's range, monotonically
        # non-decreasing, and the first batch is the real iteration 0.
        assert -1 not in iterations
        assert iterations == sorted(iterations)
        assert min(iterations) == 0
        assert max(iterations) <= 1


def _await_terminal(
    service: EvaluatorService, evaluation_id: str, timeout: float = 10.0
) -> str:
    """Poll until the background pipeline reaches a terminal status."""

    deadline = time.time() + timeout
    while time.time() < deadline:
        status = service.get_evaluation_status(evaluation_id)
        if status in {"success", "failed"}:
            return status
        time.sleep(0.01)
    raise AssertionError(
        f"Evaluation '{evaluation_id}' did not reach a terminal status; "
        f"last was '{service.get_evaluation_status(evaluation_id)}'"
    )


# --- Fakes for driving a whole evaluation to the success branch ----------


class _BlockingSimulatorRepo:
    """Holds the pipeline inside its first statement until released."""

    def __init__(self, release: threading.Event) -> None:
        self._release = release

    def get(self, simulator_id: str):
        self._release.wait(timeout=10)
        raise RuntimeError("released")


class _FakeSimulatorRepo:
    def get(self, simulator_id: str):
        from use_case_contracts.dtos import ParameterSpec, ParamType, SimulatorDetails

        return SimulatorDetails(
            model_name="Model A",
            version="v1",
            created_at="2026-01-01T00:00:00Z",
            bin_url="registry/model:1",
            input_params=[ParameterSpec(name="x", type=ParamType.INT)],
            output_params=[ParameterSpec(name="out", type=ParamType.FLOAT)],
        )


class _FakeMatrixGenerator:
    def generate_satelli_matrix_combinations(self, **kwargs):
        return type("_Matrix", (), {"matrix_url": "s3://m/satelli.csv"})()

    def upload_matrix(self, **kwargs):
        return type("_Matrix", (), {"matrix_url": "s3://m/point.csv"})()


class _SuccessScheduler:
    def __init__(self) -> None:
        self.submitted: list[int] = []

    def submit_simulation_batch(self, **kwargs):
        job_id = 1000 + len(self.submitted)
        self.submitted.append(job_id)
        return type("_Batch", (), {"job_id": str(job_id)})()

    def get_job(self, job_id: str):
        return type("_Job", (), {"status": "successful", "job_id": job_id})()


class _FakeJobsRepo:
    def list_results(self, job_id: str):
        from use_case_contracts.dtos import ResultRef

        return [ResultRef("0", f"s3://results/{job_id}/0.csv")]


class _FakeResultsRepo:
    def download(self, url: str) -> bytes:
        # A plain numeric cell: _extract_output_value returns it directly
        # without going down the time-series .csv/.zip path.
        return b"out\n0.25\n"


class _FakeAnalytics:
    def analyze_sensitivity(self, **kwargs):
        mean_data_csv = "x;out\n" + "".join(
            f"{i};{0.5 + i * 0.1}\n" for i in range(5)
        )
        return type(
            "_Sensitivity",
            (),
            {
                "important_parameters": {"out": ["x"]},
                "mean_data_csv": mean_data_csv,
            },
        )()


def _pipeline_service(store: _FakeStore) -> EvaluatorService:
    return EvaluatorService(
        jobs_scheduler=_SuccessScheduler(),  # type: ignore[arg-type]
        simulator_repository=_FakeSimulatorRepo(),  # type: ignore[arg-type]
        jobs_repository=_FakeJobsRepo(),  # type: ignore[arg-type]
        results_repository=_FakeResultsRepo(),  # type: ignore[arg-type]
        analytics=_FakeAnalytics(),  # type: ignore[arg-type]
        parser=None,  # type: ignore[arg-type]
        matrix_generator=_FakeMatrixGenerator(),  # type: ignore[arg-type]
        state_store=store,  # type: ignore[arg-type]
    )
