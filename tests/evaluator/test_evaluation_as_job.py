"""Evaluation-as-one-big-job resolution and visualization listing."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from adapters.postgres_jobs_repository.composition_root import (
    PostgresJobsRepositoryContainer,
    PostgresJobsRepositoryRoot,
)
from adapters.postgres_jobs_repository.repository_reader import (
    PostgresJobsRepositoryReader,
)
from use_case_contracts.dtos import ResultRef
from use_case_contracts.errors import NotFoundError


class _FakeCursor:
    def __init__(self, connection) -> None:
        self._connection = connection
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._connection.closed = True

    def execute(self, sql: str, params=None) -> None:
        self._connection.executed.append((sql, params))
        self._rows = list(
            self._connection.results.get(len(self._connection.executed) - 1, [])
        )

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple]:
        rows, self._rows = self._rows, []
        return rows

    def close(self) -> None:
        self._connection.closed = True


class _FakeConnection:
    """One connection. ``results`` maps call index on *this* connection to rows."""

    def __init__(self, dsn: str, results: dict[int, list[tuple]]) -> None:
        self.dsn = dsn
        self.results = results
        self.executed: list[tuple] = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True

    def cursor(self):
        return _FakeCursor(self)


def _install(monkeypatch, per_connection: list[dict[int, list[tuple]]]):
    """Fake psycopg.connect, one canned result map per connection opened."""

    import adapters.postgres_jobs_repository.repository_reader as module

    created: list[_FakeConnection] = []
    remaining = list(per_connection)

    def _fake_connect(dsn: str, **kwargs):
        results = remaining.pop(0) if remaining else {}
        connection = _FakeConnection(dsn, results)
        created.append(connection)
        return connection

    monkeypatch.setattr(module.psycopg, "connect", _fake_connect)
    return created


class _StubEvaluationsStore:
    def __init__(
        self,
        results=None,
        simulator_id: str = "7",
        status: str = "success",
        statuses=None,
    ) -> None:
        self._results = results or {}
        self._simulator_id = simulator_id
        self._status = status
        self._statuses = statuses or {}
        self.requested: list[str] = []
        self.status_checked: list[str] = []

    def list_results_for_evaluation(self, evaluation_id: str):
        self.requested.append(evaluation_id)
        return self._results.get(evaluation_id, [])

    def simulator_id_for_evaluation(self, evaluation_id: str) -> str:
        if evaluation_id not in self._results:
            raise RuntimeError(f"Evaluation '{evaluation_id}' was not found.")
        return self._simulator_id

    def evaluation_status(self, evaluation_id: str) -> str | None:
        self.status_checked.append(evaluation_id)
        if evaluation_id in self._statuses:
            return self._statuses[evaluation_id]
        # An evaluation that produced results is assumed finished unless the
        # test says otherwise.
        return self._status if evaluation_id in self._results else None


class TestResolveVisualizationTargetJob:
    def test_numeric_id_resolves_as_a_job(self, monkeypatch) -> None:
        created = _install(
            monkeypatch,
            [
                {0: [(100, 7, "s3://root/100")]},
                {0: [(0, "s3://root/100/0.csv")]},
            ],
        )
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db")

        target = reader.resolve_visualization_target("100")

        assert target.id == "100"
        assert target.simulator_id == "7"
        assert target.job_root_url == "s3://root/100"
        assert target.is_evaluation is False
        assert [ref.url for ref in target.result_urls] == ["s3://root/100/0.csv"]
        assert len(created) == 2

    def test_missing_numeric_id_falls_through_to_evaluation(
        self, monkeypatch
    ) -> None:
        # A numeric id that is not a job row may still be an evaluation key.
        _install(monkeypatch, [{0: []}])
        store = _StubEvaluationsStore({"4242": [ResultRef("0", "s3://x/0.csv")]})
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db", store)

        target = reader.resolve_visualization_target("4242")

        assert target.is_evaluation is True
        assert [ref.url for ref in target.result_urls] == ["s3://x/0.csv"]


class TestResolveVisualizationTargetEvaluation:
    def test_text_id_resolves_as_evaluation(self, monkeypatch) -> None:
        # A TEXT evaluation id must not be forced through BIGINT parsing.
        _install(monkeypatch, [])
        store = _StubEvaluationsStore(
            {
                "eval-1": [
                    ResultRef("0", "s3://root/201/0.csv"),
                    ResultRef("0", "s3://root/202/0.csv"),
                ]
            }
        )
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db", store)

        target = reader.resolve_visualization_target("eval-1")

        assert target.is_evaluation is True
        assert target.simulator_id == "7"
        assert store.requested == ["eval-1"]

    def test_root_url_is_empty_because_it_is_never_fetched(
        self, monkeypatch
    ) -> None:
        _install(monkeypatch, [])
        store = _StubEvaluationsStore({"eval-1": [ResultRef("0", "s3://x/0.csv")]})
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db", store)

        target = reader.resolve_visualization_target("eval-1")

        # analytics carries it as metadata only, so a synthetic parent can
        # leave it blank instead of inventing a prefix.
        assert target.job_root_url == ""

    def test_sensitivity_and_ssbo_results_are_mixed(self, monkeypatch) -> None:
        _install(monkeypatch, [])
        store = _StubEvaluationsStore(
            {
                "eval-1": [
                    ResultRef("0", "s3://root/sens/0.csv"),
                    ResultRef("0", "s3://root/ssbo0/0.csv"),
                    ResultRef("0", "s3://root/ssbo1/0.csv"),
                    ResultRef("0", "s3://root/ssbo2/0.csv"),
                ]
            }
        )
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db", store)

        target = reader.resolve_visualization_target("eval-1")

        urls = [ref.url for ref in target.result_urls]
        assert len(urls) == 4
        assert "s3://root/sens/0.csv" in urls
        assert "s3://root/ssbo2/0.csv" in urls

    def test_evaluation_without_results_is_not_found(self, monkeypatch) -> None:
        _install(monkeypatch, [])
        store = _StubEvaluationsStore({}, statuses={"eval-empty": "success"})
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db", store)

        with pytest.raises(NotFoundError):
            reader.resolve_visualization_target("eval-empty")

    def test_unknown_id_without_store_raises_not_found(self, monkeypatch) -> None:
        _install(monkeypatch, [])
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db")

        with pytest.raises(NotFoundError):
            reader.resolve_visualization_target("eval-1")

    def test_unknown_numeric_id_raises_not_found(self, monkeypatch) -> None:
        _install(monkeypatch, [{0: []}])
        store = _StubEvaluationsStore({})
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db", store)

        with pytest.raises(NotFoundError):
            reader.resolve_visualization_target("123456")


class TestResolveVisualizationTargetCompletionGate:
    """An evaluation is only visualizable once it has finished.

    The list hides unfinished evaluations; the resolver refuses them too, so a
    bookmarked URL cannot open one. That matters because analytics caches the
    first result set it is handed for a job key, so merging a partial dataset
    would leave an incomplete view on screen after the run completes.
    """

    def test_running_evaluation_is_refused(self, monkeypatch) -> None:
        _install(monkeypatch, [])
        store = _StubEvaluationsStore(
            {"eval-running": ["s3://root/1.csv"]}, status="optimizing"
        )
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db", store)

        with pytest.raises(NotFoundError, match="not finished"):
            reader.resolve_visualization_target("eval-running")

    def test_failed_evaluation_is_refused(self, monkeypatch) -> None:
        # Terminal, but not finished: the user asked for successful only.
        _install(monkeypatch, [])
        store = _StubEvaluationsStore(
            {"eval-failed": ["s3://root/1.csv"]}, status="failed"
        )
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db", store)

        with pytest.raises(NotFoundError, match="status 'failed'"):
            reader.resolve_visualization_target("eval-failed")

    def test_refusal_names_the_status_for_debuggability(self, monkeypatch) -> None:
        _install(monkeypatch, [])
        store = _StubEvaluationsStore({"eval-q": ["s3://root/1.csv"]}, status="queued")
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db", store)

        with pytest.raises(NotFoundError, match="status 'queued'"):
            reader.resolve_visualization_target("eval-q")

    def test_missing_evaluation_reports_not_found(self, monkeypatch) -> None:
        _install(monkeypatch, [])
        store = _StubEvaluationsStore({})
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db", store)

        with pytest.raises(NotFoundError, match="not found"):
            reader.resolve_visualization_target("eval-ghost")

    def test_finished_evaluation_resolves(self, monkeypatch) -> None:
        _install(monkeypatch, [])
        store = _StubEvaluationsStore({"eval-done": ["s3://root/1.csv"]})
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db", store)

        target = reader.resolve_visualization_target("eval-done")

        assert target.is_evaluation is True
        assert target.result_urls == ["s3://root/1.csv"]

    def test_status_is_checked_before_reading_results(self, monkeypatch) -> None:
        # The status probe is a primary-key lookup; the results query is a
        # join. Rejecting on status first avoids that join for the many
        # evaluations a running evaluation list contains.
        _install(monkeypatch, [])
        store = _StubEvaluationsStore(
            {"eval-running": ["s3://root/1.csv"]}, status="optimizing"
        )
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db", store)

        with pytest.raises(NotFoundError):
            reader.resolve_visualization_target("eval-running")

        assert store.status_checked == ["eval-running"]
        assert store.requested == []


class TestVisualizationListing:
    def _row(self, target_id, kind, model="Model A"):
        return (
            target_id,
            model,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            kind,
        )

    def test_list_mixes_jobs_and_evaluations(self, monkeypatch) -> None:
        _install(
            monkeypatch,
            [
                {
                    0: [(2,)],
                    1: [
                        self._row("eval-1", "evaluation"),
                        self._row("100", "job"),
                    ],
                }
            ],
        )
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db")

        page = reader.list_jobs_for_visualization()

        assert page.total == 2
        by_id = {item.job_id: item.kind for item in page.jobs}
        assert by_id == {"eval-1": "evaluation", "100": "job"}

    def test_excludes_jobs_owned_by_an_evaluation(self, monkeypatch) -> None:
        # The SQL must filter evaluator-submitted jobs out, otherwise a
        # single evaluation floods this list with one row per SSBO point.
        created = _install(monkeypatch, [{0: [(1,)], 1: [self._row("100", "job")]}])
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db")

        reader.list_jobs_for_visualization()

        page_sql = created[0].executed[1][0]
        assert "NOT EXISTS" in page_sql
        assert "evaluations.evaluation_job" in page_sql
        assert "UNION ALL" in page_sql

    def test_only_finished_evaluations_with_results_are_listed(
        self, monkeypatch
    ) -> None:
        _install(
            monkeypatch,
            [{0: [(1,)], 1: [self._row("eval-1", "evaluation")]}],
        )
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db")

        page = reader.list_jobs_for_visualization()

        assert [item.job_id for item in page.jobs] == ["eval-1"]

    def test_evaluation_branch_requires_the_finished_status(
        self, monkeypatch
    ) -> None:
        # A running evaluation already has partial results, so "has results"
        # alone would list it as visualizable.
        created = _install(monkeypatch, [{0: [(0,)], 1: []}])
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db")

        reader.list_jobs_for_visualization()

        count_sql, count_params = created[0].executed[0]
        page_sql, page_params = created[0].executed[1]
        for sql, params in ((count_sql, count_params), (page_sql, page_params)):
            assert "e.status = %(evaluation_status)s" in sql
            assert "results.result" in sql
            assert params["evaluation_status"] == "success"

    def test_status_filter_is_shared_by_count_and_page(self, monkeypatch) -> None:
        # A filter on the page query only would make `total` disagree with the
        # rows actually returned.
        created = _install(
            monkeypatch,
            [{0: [(1,)], 1: [self._row("e1", "evaluation")]}],
        )
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db")

        page = reader.list_jobs_for_visualization()

        assert page.total == 1
        assert created[0].executed[0][1]["evaluation_status"] == "success"
        assert created[0].executed[1][1]["evaluation_status"] == "success"

    def test_pagination_parameters_are_named(self, monkeypatch) -> None:
        # The UNION body needs named placeholders because it is reused by both
        # the count and the page query.
        created = _install(monkeypatch, [{0: [(0,)], 1: []}])
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db")

        page = reader.list_jobs_for_visualization(page=3, per_page=5)

        _, params = created[0].executed[1]
        assert params["per_page"] == 5
        assert params["offset"] == 10
        assert page.page == 3
        assert page.per_page == 5


class TestJobsRepositoryContainerWiring:
    def test_container_wires_the_evaluations_store(self) -> None:
        container = PostgresJobsRepositoryContainer()
        container.config.from_dict({"dsn": "postgresql://localhost/db"})

        reader = PostgresJobsRepositoryRoot(container).jobs_repository_reader()

        assert reader._evaluations_store is not None
        assert hasattr(reader._evaluations_store, "list_results_for_evaluation")
        assert hasattr(reader._evaluations_store, "evaluation_status")

    def test_reader_works_without_an_evaluations_store(self) -> None:
        reader = PostgresJobsRepositoryReader("postgresql://localhost/db")
        assert reader._evaluations_store is None


class TestBeginJobVisualizationHandler:
    """The user-facing entry point: an evaluation id must just work."""

    def test_evaluation_id_is_handed_to_analytics_as_one_big_job(self) -> None:
        from services.use_case.handlers.visualizations import (
            handle_begin_job_visualization,
        )
        from use_case_contracts.dtos import (
            ParameterSpec,
            ParamType,
            SimulatorDetails,
        )
        from use_case_contracts.messages import BeginJobVisualization

        target = _target_for_evaluation()
        reader = _FakeJobsReader(target)
        analytics = _RecordingAnalytics()

        header = handle_begin_job_visualization(
            BeginJobVisualization(job_id="eval-1"),
            reader,
            _FakeSimulatorsRepo(),
            analytics,
            _StubVisualization(),
        )

        # Every sensitivity and SSBO artifact reaches analytics in one call.
        assert analytics.initialised == [
            ("eval-1", "", ["s3://root/sens/0.csv", "s3://root/ssbo/0.csv"])
        ]
        assert header.plot_types == ["Line", "Scatter"]

    def test_simulator_of_the_evaluation_supplies_the_parameters(self) -> None:
        from services.use_case.handlers.visualizations import (
            handle_begin_job_visualization,
        )
        from use_case_contracts.messages import BeginJobVisualization

        simulators = _FakeSimulatorsRepo()

        handle_begin_job_visualization(
            BeginJobVisualization(job_id="eval-1"),
            _FakeJobsReader(_target_for_evaluation()),
            simulators,
            _RecordingAnalytics(),
            _StubVisualization(),
        )

        # Resolved via the evaluation's simulator id, not a job's.
        assert simulators.requested == ["7"]


class _FakeJobsReader:
    def __init__(self, target) -> None:
        self._target = target

    def resolve_visualization_target(self, job_id: str):
        return self._target


class _FakeSimulatorsRepo:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def get(self, simulator_id: str):
        from use_case_contracts.dtos import ParameterSpec, ParamType, SimulatorDetails

        self.requested.append(simulator_id)
        return SimulatorDetails(
            model_name="Model A",
            version="v1",
            created_at="2026-01-01",
            bin_url="docker://model",
            input_params=[ParameterSpec(name="n", type=ParamType.INT)],
            output_params=[ParameterSpec(name="out", type=ParamType.FLOAT)],
        )


class _RecordingAnalytics:
    def __init__(self) -> None:
        self.initialised: list[tuple] = []

    def initialize_job(self, job_id, job_root_url, result_urls, i, o) -> None:
        self.initialised.append(
            (job_id, job_root_url, [ref.url for ref in result_urls])
        )

    def job_results_status(self, job_id: str) -> str:
        return "unknown"

    def input_parameters_values(self, job_id: str) -> list:
        return []

    def job_repetitions(self, job_id: str) -> list:
        return []


class _StubVisualization:
    def supported_plot_types(self) -> list[str]:
        return ["Line", "Scatter"]


def _target_for_evaluation():
    from use_case_contracts.dtos import VisualizationTarget

    return VisualizationTarget(
        id="eval-1",
        simulator_id="7",
        job_root_url="",
        result_urls=[
            ResultRef("0", "s3://root/sens/0.csv"),
            ResultRef("0", "s3://root/ssbo/0.csv"),
        ],
        is_evaluation=True,
    )
