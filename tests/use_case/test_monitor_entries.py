from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.use_case.handlers.simulations import handle_list_monitor_entries
from use_case_contracts.dtos import JobSummary
from use_case_contracts.errors import ExternalServiceError
from use_case_contracts.messages import ListMonitorEntries


class _FakeScheduler:
    def __init__(self, job_ids: list[str], error: Exception | None = None) -> None:
        self._job_ids = job_ids
        self._error = error

    def list_jobs(self) -> list[JobSummary]:
        if self._error is not None:
            raise self._error
        return [JobSummary(job_id=job_id) for job_id in self._job_ids]


class _FakeStore:
    def __init__(
        self,
        links: dict[str, set[str]] | None = None,
        summaries: list[dict] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._links = links or {}
        self._summaries = summaries or []
        self._error = error

    def list_evaluation_job_links(self) -> dict[str, set[str]]:
        if self._error is not None:
            raise self._error
        return self._links

    def list_summaries(self) -> list[dict]:
        if self._error is not None:
            raise self._error
        return self._summaries


def _summary(**overrides) -> dict:
    base = {
        "evaluation_id": "eval-1",
        "model_name": "Model A",
        "status": "queued",
        "stage": None,
        "iteration": 0,
        "kmax": 30,
        "best_value": None,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def _handle(scheduler: _FakeScheduler, store: _FakeStore):
    return handle_list_monitor_entries(ListMonitorEntries(), scheduler, store)


class TestMonitorEntriesFiltering:
    def test_evaluation_owned_jobs_are_hidden_from_simulations(self) -> None:
        scheduler = _FakeScheduler(["1", "2", "3", "4"])
        store = _FakeStore(links={"eval-1": {"2", "3"}})

        entries = _handle(scheduler, store)

        # The two SSBO submissions must not flood the simulation column.
        assert entries.simulation_group_ids == ["1", "4"]

    def test_evaluation_ids_are_compared_as_strings(self) -> None:
        # The store hands back strings, the scheduler hands back strings, but
        # an integer id anywhere would break the comparison silently.
        scheduler = _FakeScheduler(["11", "12"])
        store = _FakeStore(links={"eval-1": {"11"}})

        entries = _handle(scheduler, store)

        assert entries.simulation_group_ids == ["12"]

    def test_simulation_jobs_survive_when_no_evaluations_exist(self) -> None:
        entries = _handle(_FakeScheduler(["1", "2"]), _FakeStore())

        assert entries.simulation_group_ids == ["1", "2"]
        assert entries.evaluations == []

    def test_every_live_evaluation_produces_exactly_one_entry(self) -> None:
        store = _FakeStore(
            links={
                f"eval-{index}": {str(index)} for index in range(100)
            },
            summaries=[
                _summary(evaluation_id=f"eval-{index}") for index in range(3)
            ],
        )

        entries = _handle(_FakeScheduler([str(i) for i in range(100)]), store)

        assert entries.simulation_group_ids == []
        assert [item.evaluation_id for item in entries.evaluations] == [
            "eval-0",
            "eval-1",
            "eval-2",
        ]


class TestMonitorEntriesLivenessFiltering:
    def test_finished_evaluation_drops_when_no_job_is_live(self) -> None:
        store = _FakeStore(
            links={"eval-1": {"2"}},
            summaries=[_summary(status="success")],
        )

        entries = _handle(_FakeScheduler([]), store)

        assert entries.evaluations == []

    def test_finished_evaluation_kept_while_its_job_is_live(self) -> None:
        store = _FakeStore(
            links={"eval-1": {"2"}},
            summaries=[_summary(status="success")],
        )

        entries = _handle(_FakeScheduler(["2"]), store)

        # The job is owned by the evaluation, so it is not listed separately.
        assert entries.simulation_group_ids == []
        assert [item.evaluation_id for item in entries.evaluations] == ["eval-1"]

    def test_finished_evaluation_needs_its_own_job_live(self) -> None:
        store = _FakeStore(
            links={"eval-1": {"2"}},
            summaries=[_summary(status="success")],
        )

        entries = _handle(_FakeScheduler(["3"]), store)

        assert entries.evaluations == []
        assert entries.simulation_group_ids == ["3"]

    def test_non_terminal_evaluation_kept_without_any_job(self) -> None:
        store = _FakeStore(summaries=[_summary(status="queued")])

        entries = _handle(_FakeScheduler([]), store)

        assert [item.evaluation_id for item in entries.evaluations] == ["eval-1"]

    def test_running_evaluation_kept_even_when_jobs_are_gone(self) -> None:
        store = _FakeStore(
            links={"eval-1": {"2"}},
            summaries=[_summary(status="simulating")],
        )

        entries = _handle(_FakeScheduler([]), store)

        assert [item.evaluation_id for item in entries.evaluations] == ["eval-1"]


class TestMonitorEntriesEvaluationStates:
    @pytest.mark.parametrize(
        "status,expected_state",
        [
            ("queued", "waiting"),
            ("running", "running"),
            ("simulating", "running"),
            ("sensitivity_analysis", "running"),
            ("optimizing", "running"),
            ("success", "finished"),
            ("failed", "finished"),
        ],
    )
    def test_status_maps_to_monitor_column(
        self, status: str, expected_state: str
    ) -> None:
        # A live job keeps even a terminal evaluation on the monitor.
        entries = _handle(
            _FakeScheduler(["1"]),
            _FakeStore(
                links={"eval-1": {"1"}},
                summaries=[_summary(status=status)],
            ),
        )

        assert entries.evaluations[0].state == expected_state

    def test_unknown_status_is_kept_visible_as_running(self) -> None:
        entries = _handle(
            _FakeScheduler([]), _FakeStore(summaries=[_summary(status="brand_new")])
        )

        entry = entries.evaluations[0]
        assert entry.state == "running"
        assert entry.status == "brand_new"

    def test_success_flag_only_set_for_terminal(self) -> None:
        entries = _handle(
            _FakeScheduler(["1", "2"]),
            _FakeStore(
                links={"ok": {"1"}, "bad": {"2"}},
                summaries=[
                    _summary(evaluation_id="ok", status="success"),
                    _summary(evaluation_id="bad", status="failed"),
                    _summary(evaluation_id="busy", status="optimizing"),
                ],
            ),
        )

        by_id = {item.evaluation_id: item for item in entries.evaluations}
        assert by_id["ok"].success is True
        assert by_id["bad"].success is False
        assert by_id["busy"].success is None

    def test_status_is_lower_cased(self) -> None:
        entries = _handle(
            _FakeScheduler(["1"]),
            _FakeStore(
                links={"eval-1": {"1"}},
                summaries=[_summary(status="SUCCESS")],
            ),
        )

        assert entries.evaluations[0].status == "success"
        assert entries.evaluations[0].state == "finished"


class TestMonitorEntriesProgress:
    def test_progress_is_iteration_over_kmax(self) -> None:
        entries = _handle(
            _FakeScheduler([]),
            _FakeStore(summaries=[_summary(iteration=3, kmax=12, status="optimizing")]),
        )

        assert entries.evaluations[0].progress == 25

    def test_progress_is_clamped_to_bounds(self) -> None:
        over = _handle(
            _FakeScheduler([]),
            _FakeStore(summaries=[_summary(iteration=50, kmax=10, status="optimizing")]),
        )
        under = _handle(
            _FakeScheduler([]),
            _FakeStore(summaries=[_summary(iteration=-5, kmax=10, status="optimizing")]),
        )

        assert over.evaluations[0].progress == 100
        assert under.evaluations[0].progress == 0

    def test_progress_is_absent_when_kmax_is_zero(self) -> None:
        entries = _handle(
            _FakeScheduler([]),
            _FakeStore(summaries=[_summary(iteration=5, kmax=0, status="optimizing")]),
        )

        assert entries.evaluations[0].progress is None

    def test_progress_is_absent_for_waiting_and_finished(self) -> None:
        entries = _handle(
            _FakeScheduler(["1"]),
            _FakeStore(
                links={"s": {"1"}},
                summaries=[
                    _summary(evaluation_id="q", status="queued", iteration=3),
                    _summary(evaluation_id="s", status="success", iteration=30),
                ],
            ),
        )

        by_id = {item.evaluation_id: item for item in entries.evaluations}
        assert by_id["q"].progress is None
        assert by_id["s"].progress is None

    def test_non_numeric_iteration_is_tolerated(self) -> None:
        entries = _handle(
            _FakeScheduler([]),
            _FakeStore(
                summaries=[
                    _summary(iteration=None, kmax=None, status="optimizing")
                ]
            ),
        )

        assert entries.evaluations[0].progress is None


class TestMonitorEntriesFailureHandling:
    def test_scheduler_failure_becomes_external_service_error(self) -> None:
        class SlurmProtocolError(Exception):
            pass

        scheduler = _FakeScheduler([], error=SlurmProtocolError("slurm down"))

        with pytest.raises(ExternalServiceError):
            _handle(scheduler, _FakeStore())

    def test_store_failure_becomes_external_service_error(self) -> None:
        # Showing every SSBO job separately would flood the monitor, so a
        # failure to read the link table must fail loudly.
        store = _FakeStore(error=RuntimeError("db down"))

        with pytest.raises(ExternalServiceError):
            _handle(_FakeScheduler(["1"]), store)

    def test_model_name_is_passed_through(self) -> None:
        entries = _handle(
            _FakeScheduler([]),
            _FakeStore(summaries=[_summary(model_name="Fluent Solver 2.1")]),
        )

        assert entries.evaluations[0].model_name == "Fluent Solver 2.1"

    def test_created_at_timestamp_is_passed_through(self) -> None:
        moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
        entries = _handle(
            _FakeScheduler([]), _FakeStore(summaries=[_summary(created_at=moment)])
        )

        assert entries.evaluations[0].created_at == moment.timestamp()
