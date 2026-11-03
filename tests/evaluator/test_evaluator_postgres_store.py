from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from dependency_injector import providers

from adapters.postgres_evaluations_store.composition_root import (
    PostgresEvaluationsStoreContainer,
)
from adapters.postgres_evaluations_store import evaluations_store as store_module
from adapters.postgres_evaluations_store.evaluations_store import (
    PostgresEvaluationsStore,
)


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection
        self._rows: list[tuple] = []
        self._index = 0

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._connection.closed = True

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._connection.executed.append((sql, params))
        self._rows = list(self._connection.results.get(len(self._connection.executed) - 1, []))
        self._index = 0

    def fetchone(self) -> tuple | None:
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self) -> list[tuple]:
        rows = self._rows[self._index :]
        self._index = len(self._rows)
        return rows

    def close(self) -> None:
        self._connection.closed = True


class _FakeConnection:
    def __init__(self, dsn: str, results: dict[int, list[tuple]]) -> None:
        self.dsn = dsn
        self.results = results
        self.executed: list[tuple[str, tuple]] = []
        self.closed = False

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


def _evaluation_row(**overrides: Any) -> tuple:
    row = {
        "simulator_id": 7,
        "created_at": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        "status": "optimizing",
        "stage": "optimizing",
        "iteration": 2,
        "kmax": 30,
        "best_value": 0.25,
        "best_params": {"x": 1.5},
        "important_parameters": ["x"],
        "output_column": "out",
        "aggregation": "mean",
        "problem": {"names": ["x"], "bounds": [[0.0, 1.0]], "output": "out"},
        "config": {"kmax": 30},
        "ssbo_history": [{"iteration": 1, "best_value": 0.5}],
        "final_result": None,
        "error": None,
    }
    row.update(overrides)
    return tuple(row.values())


@pytest.fixture
def connections(monkeypatch: pytest.MonkeyPatch) -> list[_FakeConnection]:
    return _install(monkeypatch, {})


def _queue(results: dict[int, list[tuple]]):
    """Build a psycopg.connect replacement returning pre-canned rows."""

    def _fake_connect(dsn: str, **kwargs: object):
        connection = _FakeConnection(dsn, results)
        _fake_connect.created.append(connection)  # type: ignore[attr-defined]
        return connection

    _fake_connect.created = []  # type: ignore[attr-defined]
    return _fake_connect


def _install(monkeypatch: pytest.MonkeyPatch, results: dict[int, list[tuple]]):
    fake = _queue(results)
    monkeypatch.setattr(store_module.psycopg, "connect", fake)
    return fake.created  # type: ignore[attr-defined]


def _install_failure(monkeypatch: pytest.MonkeyPatch, error: Exception):
    """Make psycopg.connect raise, to cover the error-wrapping paths."""

    def _fake_connect(dsn: str, **kwargs: object):
        raise error

    monkeypatch.setattr(store_module.psycopg, "connect", _fake_connect)


class TestPostgresEvaluationsStoreInit:
    def test_missing_dsn_is_rejected(self) -> None:
        with pytest.raises(RuntimeError, match="Missing PostgreSQL DSN"):
            PostgresEvaluationsStore("   ")


class TestPostgresEvaluationsStoreSave:
    def test_save_writes_status_and_terminal_marker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = _install(monkeypatch, {})

        PostgresEvaluationsStore("postgresql://localhost/db").save(
            "eval-1",
            {
                "status": "success",
                "simulator_id": "7",
                "iteration": 30,
                "kmax": 30,
                "best_value": 0.25,
                "ssbo_history": [{"iteration": 1}],
                "final_result": {"status": "success"},
                "config": {"kmax": 30},
            },
        )

        sql, params = created[0].executed[0]
        assert "INSERT INTO evaluations.evaluation" in sql
        assert params[0] == "eval-1"
        assert params[1] == 7
        assert params[2] is True
        assert params[3] == "success"
        assert params[-1] is True

    def test_save_treats_running_evaluation_as_not_finished(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = _install(monkeypatch, {})

        PostgresEvaluationsStore("postgresql://localhost/db").save(
            "eval-1",
            {"status": "optimizing", "simulator_id": "7"},
        )

        _, params = created[0].executed[0]
        assert params[2] is False
        assert params[-1] is False

    def test_save_writes_best_value_column(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = _install(monkeypatch, {})

        PostgresEvaluationsStore("postgresql://localhost/db").save(
            "eval-1",
            {
                "status": "optimizing",
                "simulator_id": "7",
                "best_value": 0.5,
            },
        )

        _, params = created[0].executed[0]
        assert params[7] == 0.5

    def test_save_rejects_non_numeric_simulator_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {})

        with pytest.raises(RuntimeError, match="Invalid simulator_id"):
            PostgresEvaluationsStore("postgresql://localhost/db").save(
                "eval-1", {"status": "queued", "simulator_id": "model-1"}
            )

    def test_save_serialises_numpy_arrays(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import numpy as np

        created = _install(monkeypatch, {})

        PostgresEvaluationsStore("postgresql://localhost/db").save(
            "eval-1",
            {
                "status": "optimizing",
                "simulator_id": "7",
                "ssbo_history": [{"new_point": np.array([1.0, 2.0])}],
            },
        )

        _, params = created[0].executed[0]
        stored = params[14].obj
        assert stored == [{"new_point": [1.0, 2.0]}]


class TestPostgresEvaluationsStoreLoad:
    def test_load_maps_row_to_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, {0: [_evaluation_row()]})

        state = PostgresEvaluationsStore("postgresql://localhost/db").load("eval-1")

        assert state is not None
        assert state["status"] == "optimizing"
        assert state["iteration"] == 2
        assert state["kmax"] == 30
        assert state["best_value"] == 0.25
        assert state["ssbo_history"] == [{"iteration": 1, "best_value": 0.5}]
        assert state["created_at"] > 0

    def test_load_returns_none_for_missing_evaluation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {0: []})

        assert (
            PostgresEvaluationsStore("postgresql://localhost/db").load("eval-1")
            is None
        )

    def test_load_synthesises_failure_result_from_error_column(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            {0: [_evaluation_row(status="failed", error="Interrupted by restart")]},
        )

        state = PostgresEvaluationsStore("postgresql://localhost/db").load("eval-1")

        assert state is not None
        assert state["final_result"]["details"]["error"] == "Interrupted by restart"

    def test_load_all_reads_every_listed_evaluation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            {
                0: [("eval-1",), ("eval-2",)],
                1: [_evaluation_row()],
                2: [_evaluation_row(status="success")],
            },
        )

        states = PostgresEvaluationsStore("postgresql://localhost/db").load_all()

        assert sorted(states) == ["eval-1", "eval-2"]
        assert states["eval-2"]["status"] == "success"

    def test_load_wraps_database_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(dsn: str, **kwargs: object):
            raise store_module.psycopg.OperationalError("connection refused")

        monkeypatch.setattr(store_module.psycopg, "connect", _boom)

        with pytest.raises(RuntimeError, match="Failed to load evaluation"):
            PostgresEvaluationsStore("postgresql://localhost/db").load("eval-1")


class TestPostgresEvaluationsStoreHotPath:
    def test_update_progress_targets_only_progress_columns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = _install(monkeypatch, {})

        PostgresEvaluationsStore("postgresql://localhost/db").update_progress(
            "eval-1",
            status="optimizing",
            stage="optimizing",
            iteration=3,
            best_value=0.1,
            ssbo_history=[{"iteration": 3}],
        )

        sql, params = created[0].executed[0]
        assert sql.strip().startswith("UPDATE evaluations.evaluation")
        assert "best_params" not in sql
        assert params[2] == 3
        assert params[3] == 0.1
        assert params[5] == "eval-1"

    def test_update_progress_serialises_numpy_arrays(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import numpy as np

        created = _install(monkeypatch, {})

        PostgresEvaluationsStore("postgresql://localhost/db").update_progress(
            "eval-1",
            status="optimizing",
            stage="optimizing",
            iteration=1,
            best_value=0.9,
            ssbo_history=[
                {
                    "new_point": np.array([0.1, 0.2]),
                    "new_value": np.array([0.9]),
                    "best_x": np.array([0.15]),
                }
            ],
        )

        # The SSBO loop hands over numpy arrays every iteration, so the hot
        # path must go through the numpy-aware JSONB wrapper.
        _, params = created[0].executed[0]
        assert params[4].obj == [
            {
                "new_point": [0.1, 0.2],
                "new_value": [0.9],
                "best_x": [0.15],
            }
        ]

    def test_update_progress_defaults_empty_history(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = _install(monkeypatch, {})

        PostgresEvaluationsStore("postgresql://localhost/db").update_progress(
            "eval-1",
            status="queued",
            stage=None,
            iteration=0,
            best_value=None,
            ssbo_history=[],
        )

        _, params = created[0].executed[0]
        assert params[4].obj == []

    def test_record_job_links_job_to_evaluation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = _install(monkeypatch, {})

        PostgresEvaluationsStore("postgresql://localhost/db").record_job(
            "eval-1", "4321", stage="ssbo", iteration=4
        )

        sql, params = created[0].executed[0]
        assert "INSERT INTO evaluations.evaluation_job" in sql
        assert "ON CONFLICT" in sql
        assert params == ("eval-1", 4321, "ssbo", 4)

    def test_record_job_defaults_iteration_to_zero_for_sensitivity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = _install(monkeypatch, {})

        PostgresEvaluationsStore("postgresql://localhost/db").record_job(
            "eval-1", "4321", stage="sensitivity"
        )

        _, params = created[0].executed[0]
        assert params == ("eval-1", 4321, "sensitivity", 0)

    def test_record_job_failure_is_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(dsn: str, **kwargs: object):
            raise store_module.psycopg.OperationalError("down")

        monkeypatch.setattr(store_module.psycopg, "connect", _boom)

        with pytest.raises(RuntimeError, match="Failed to record job"):
            PostgresEvaluationsStore("postgresql://localhost/db").record_job(
                "eval-1", "1", stage="ssbo"
            )

    def test_job_counts_groups_by_stage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {0: [("sensitivity", 1), ("ssbo", 27)]})

        counts = PostgresEvaluationsStore("postgresql://localhost/db").job_counts(
            "eval-1"
        )

        assert counts == {"sensitivity": 1, "ssbo": 27}


class TestPostgresEvaluationsStoreMonitorReads:
    def test_job_links_are_grouped_by_evaluation_as_strings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # job_id is BIGINT in SQL but the scheduler reports it as a string,
        # so the monitor's suppression depends on this normalisation.
        _install(
            monkeypatch,
            {0: [("eval-1", 101), ("eval-1", 102), ("eval-2", 103)]},
        )

        links = PostgresEvaluationsStore(
            "postgresql://localhost/db"
        ).list_evaluation_job_links()

        assert links == {"eval-1": {"101", "102"}, "eval-2": {"103"}}

    def test_job_links_are_empty_when_no_links(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {0: []})

        links = PostgresEvaluationsStore(
            "postgresql://localhost/db"
        ).list_evaluation_job_links()

        assert links == {}

    def test_job_links_failure_is_wrapped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(dsn: str, **kwargs: object):
            raise store_module.psycopg.Error("connection refused")

        monkeypatch.setattr(store_module.psycopg, "connect", _boom)

        with pytest.raises(RuntimeError, match="Failed to list jobs owned by evaluations"):
            PostgresEvaluationsStore(
                "postgresql://localhost/db"
            ).list_evaluation_job_links()

    def test_summaries_map_monitor_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            {
                0: [
                    (
                        "eval-1",
                        7,
                        "Model A",
                        datetime(2026, 1, 1, tzinfo=timezone.utc),
                        "optimizing",
                        "optimizing",
                        3,
                        12,
                        0.25,
                    )
                ]
            },
        )

        summaries = PostgresEvaluationsStore("postgresql://localhost/db").list_summaries()

        assert summaries == [
            {
                "evaluation_id": "eval-1",
                "simulator_id": "7",
                "model_name": "Model A",
                "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "status": "optimizing",
                "stage": "optimizing",
                "iteration": 3,
                "kmax": 12,
                "best_value": 0.25,
            }
        ]

    def test_summaries_omit_heavy_jsonb_columns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The monitor auto-refreshes, so the big JSONB blobs must not be read.
        created = _install(
            monkeypatch,
            {
                0: [
                    (
                        "eval-1",
                        7,
                        "Model A",
                        datetime(2026, 1, 1, tzinfo=timezone.utc),
                        "success",
                        None,
                        30,
                        30,
                        0.1,
                    )
                ]
            },
        )

        PostgresEvaluationsStore("postgresql://localhost/db").list_summaries()

        sql = created[0].executed[0][0]
        assert "ssbo_history" not in sql
        assert "final_result" not in sql
        assert "problem" not in sql

    def test_summaries_tolerate_nulls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            {0: [("eval-1", 7, None, None, "queued", None, None, None, None)]},
        )

        summaries = PostgresEvaluationsStore("postgresql://localhost/db").list_summaries()

        assert summaries[0]["model_name"] is None
        assert summaries[0]["created_at"] is None
        assert summaries[0]["iteration"] == 0
        assert summaries[0]["kmax"] == 0
        assert summaries[0]["best_value"] is None

    def test_summaries_failure_is_wrapped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(dsn: str, **kwargs: object):
            raise store_module.psycopg.Error("connection refused")

        monkeypatch.setattr(store_module.psycopg, "connect", _boom)

        with pytest.raises(RuntimeError, match="Failed to list evaluation summaries"):
            PostgresEvaluationsStore("postgresql://localhost/db").list_summaries()


class TestEvaluationsStoreComposition:
    def test_container_resolves_store_with_dsn(self) -> None:
        container = PostgresEvaluationsStoreContainer()
        container.config.from_dict({"dsn": "postgresql://localhost/db"})

        store = container.evaluations_store()

        assert isinstance(store, PostgresEvaluationsStore)
        assert store._dsn == "postgresql://localhost/db"

    def test_container_uses_configuration_override(self) -> None:
        config = providers.Configuration()
        config.from_dict({"dsn": "postgresql://other/db"})
        container = PostgresEvaluationsStoreContainer(config=config)

        assert container.evaluations_store()._dsn == "postgresql://other/db"


class TestSchemaAgreesWithCode:
    """The evaluations_job stage CHECK constraint must accept what we write.

    A mismatch here is silent: record_job failures are logged and swallowed so
    a database hiccup cannot abort an evaluation, which would also hide a
    constraint violation.
    """

    def test_record_job_stages_are_allowed_by_schema(self) -> None:
        import re
        from pathlib import Path

        schema = (
            Path(__file__).resolve().parents[2] / "db_mgmt" / "01_schema.sql"
        ).read_text()
        match = re.search(
            r"evaluation_job_stage_check.*?stage IN \((?P<stages>[^)]*)\)",
            schema,
            re.S,
        )
        assert match is not None, "evaluation_job stage CHECK constraint not found"
        allowed = set(re.findall(r"'([^']+)'", match.group("stages")))

        service_source = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "services"
            / "evaluator"
            / "core"
            / "evaluator_service.py"
        ).read_text()
        used = set(re.findall(r"_record_job\([^)]*stage=\"([a-z_]+)\"", service_source))

        assert used, "no _record_job call sites found"
        assert used <= allowed, f"stages not allowed by the schema: {used - allowed}"

    def test_evaluation_statuses_are_allowed_by_schema(self) -> None:
        import re
        from pathlib import Path

        schema = (
            Path(__file__).resolve().parents[2] / "db_mgmt" / "01_schema.sql"
        ).read_text()
        match = re.search(
            r"evaluation_status_check.*?status IN \((?P<statuses>[^)]*)\)", schema, re.S
        )
        assert match is not None, "evaluation status CHECK constraint not found"
        allowed = set(re.findall(r"'([^']+)'", match.group("statuses")))

        assert allowed == {
            "queued",
            "running",
            "simulating",
            "sensitivity_analysis",
            "optimizing",
            "success",
            "failed",
        }
        assert store_module.TERMINAL_STATUSES <= allowed


class TestPostgresEvaluationsStoreResultReads:
    def test_results_are_returned_as_a_flat_list_in_sql_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Flat, because the analytics service merges a list of result URLs into
        # one dataset; ordered by stage/iteration so the merge is deterministic.
        _install(
            monkeypatch,
            {0: [(0, "s3://root/201/0.csv"), (1, "s3://root/202/0.csv")]},
        )

        refs = PostgresEvaluationsStore(
            "postgresql://localhost/db"
        ).list_results_for_evaluation("eval-1")

        assert [ref.url for ref in refs] == [
            "s3://root/201/0.csv",
            "s3://root/202/0.csv",
        ]

    def test_sensitivity_and_ssbo_artifacts_are_mixed_without_a_stage_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = [
            (0, "s3://root/201/0.csv"),
            (0, "s3://root/202/0.csv"),
            (0, "s3://root/203/0.csv"),
            (0, "s3://root/204/0.csv"),
        ]
        _install(monkeypatch, {0: rows})

        refs = PostgresEvaluationsStore(
            "postgresql://localhost/db"
        ).list_results_for_evaluation("eval-1")

        assert len(refs) == 4

    def test_result_sub_job_id_is_normalised_to_a_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {0: [(201, "s3://root/201/0.csv")]})

        refs = PostgresEvaluationsStore(
            "postgresql://localhost/db"
        ).list_results_for_evaluation("eval-1")

        assert refs[0].sub_job_id == "201"
        assert not isinstance(refs[0].sub_job_id, int)

    def test_evaluation_without_results_yields_an_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {0: []})

        assert (
            PostgresEvaluationsStore(
                "postgresql://localhost/db"
            ).list_results_for_evaluation("eval-2")
            == []
        )

    def test_read_failure_is_reported_with_the_evaluation_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_failure(monkeypatch, store_module.psycopg.OperationalError("boom"))

        with pytest.raises(RuntimeError, match="eval-1"):
            PostgresEvaluationsStore(
                "postgresql://localhost/db"
            ).list_results_for_evaluation("eval-1")


class TestPostgresEvaluationsStoreSimulatorLookup:
    def test_simulator_id_is_returned_as_a_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {0: [(7,)]})

        assert (
            PostgresEvaluationsStore(
                "postgresql://localhost/db"
            ).simulator_id_for_evaluation("eval-1")
            == "7"
        )

    def test_lookup_is_a_single_row_read_not_a_full_summary_scan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The jobs reader calls this on the visualization hot path, so it must
        # not drag every evaluation's metadata across the wire.
        created = _install(monkeypatch, {0: [(7,)]})

        PostgresEvaluationsStore(
            "postgresql://localhost/db"
        ).simulator_id_for_evaluation("eval-1")

        sql = created[0].executed[0][0]
        assert "FROM evaluations.evaluation" in sql
        assert "e.evaluation_id" not in sql
        assert sql.count("SELECT") == 1

    def test_missing_evaluation_is_reported(self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, {0: []})

        with pytest.raises(RuntimeError, match="eval-gone"):
            PostgresEvaluationsStore(
                "postgresql://localhost/db"
            ).simulator_id_for_evaluation("eval-gone")


class TestPostgresEvaluationsStoreStatusLookup:
    def test_current_status_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, {0: [("optimizing",)]})

        assert (
            PostgresEvaluationsStore(
                "postgresql://localhost/db"
            ).evaluation_status("eval-1")
            == "optimizing"
        )

    def test_missing_evaluation_returns_none(self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Returns None rather than raising, so the reader can reject unknown
        # and unfinished evaluations through one branch.
        _install(monkeypatch, {0: []})

        assert (
            PostgresEvaluationsStore(
                "postgresql://localhost/db"
            ).evaluation_status("eval-gone")
            is None
        )

    def test_lookup_is_a_single_row_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The jobs reader calls this on the visualization hot path, so it must
        # not drag every evaluation's metadata across the wire.
        created = _install(monkeypatch, {0: [("success",)]})

        PostgresEvaluationsStore(
            "postgresql://localhost/db"
        ).evaluation_status("eval-1")

        sql = created[0].executed[0][0]
        assert "SELECT status FROM evaluations.evaluation" in sql
        assert sql.count("SELECT") == 1

    def test_connection_failure_is_wrapped(self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_failure(monkeypatch, store_module.psycopg.OperationalError("boom"))

        with pytest.raises(RuntimeError, match="eval-1"):
            PostgresEvaluationsStore(
                "postgresql://localhost/db"
            ).evaluation_status("eval-1")


class TestPostgresEvaluationsStoreTerminalStage:
    """A finished or failed run must persist its terminal stage verbatim."""

    @pytest.mark.parametrize("stage", ["finished", "failed"])
    def test_save_persists_the_terminal_stage(
        self, monkeypatch: pytest.MonkeyPatch, stage: str
    ) -> None:
        created = _install(monkeypatch, {})

        PostgresEvaluationsStore("postgresql://localhost/db").save(
            "eval-1",
            {
                "status": "success" if stage == "finished" else "failed",
                "simulator_id": "7",
                "stage": stage,
                "iteration": 30,
                "kmax": 30,
            },
        )

        _, params = created[0].executed[0]
        # save() sends stage as its own parameter, so it reaches
        # evaluations.evaluation.stage rather than being derived from status.
        assert params[4] == stage

    def test_terminal_stage_survives_a_round_trip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            {
                0: [
                    (
                        7,           # simulator_id
                        datetime(2026, 1, 1, tzinfo=timezone.utc),  # created_at
                        "success",   # status
                        "finished",  # stage
                        30,          # iteration
                        30,          # kmax
                        0.25,        # best_value
                        {"x": 1},    # best_params
                        ["x"],       # important_parameters
                        "out",       # output_column
                        "mean",      # aggregation
                        None,        # problem
                        {},          # config
                        [],          # ssbo_history
                        None,        # final_result
                        None,        # error
                    )
                ]
            },
        )

        state = PostgresEvaluationsStore("postgresql://localhost/db").load("eval-1")

        assert state is not None
        assert state["status"] == "success"
        assert state["stage"] == "finished"
