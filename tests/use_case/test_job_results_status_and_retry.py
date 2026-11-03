from __future__ import annotations

from services.use_case.handlers.visualizations import (
    handle_begin_job_visualization,
    handle_get_job_repetitions,
    handle_get_visualization_constant_params,
    handle_retry_job_results,
)
from use_case_contracts.dtos import (
    JobVisualizationConstants,
    ParameterSpec,
    ParameterValues,
    ParamType,
    ResultRef,
    SimulatorDetails,
    VisualizationTarget,
)
from use_case_contracts.errors import ExternalServiceError
from use_case_contracts.messages import (
    BeginJobVisualization,
    GetJobRepetitions,
    GetVisualizationConstantParams,
    RetryJobResults,
)

_RESULTS = [ResultRef("0", "s3://root/res.csv.zip")]


class _FakeJobsReader:
    def resolve_visualization_target(self, job_id: str):
        return VisualizationTarget(
            id=job_id,
            simulator_id="7",
            job_root_url="s3://root",
            result_urls=_RESULTS,
            is_evaluation=False,
        )


class _FakeSimulatorsRepo:
    def get(self, simulator_id: str):
        return SimulatorDetails(
            model_name="Model A",
            version="v1",
            created_at="2026-01-01",
            bin_url="docker://model",
            input_params=[ParameterSpec(name="K", type=ParamType.INT)],
            output_params=[ParameterSpec(name="out", type=ParamType.FLOAT)],
        )


class _StubVisualization:
    def supported_plot_types(self) -> list[str]:
        return ["Line", "Scatter"]


class _FakeAnalytics:
    def __init__(self, statuses: list[str] | None = None, error: str | None = None) -> None:
        # Consumed one per status call so a 'processing' wait can be simulated.
        self._statuses = list(statuses or ["ok"])
        self.error = error
        self.initialized: list[tuple] = []
        self.retried: list[tuple] = []

    def initialize_job(self, job_id, job_root_url, result_urls, i, o) -> None:
        self.initialized.append((job_id, job_root_url, [ref.url for ref in result_urls]))

    def retry_job_results(self, job_id, job_root_url, result_urls, i, o) -> None:
        self.retried.append((job_id, job_root_url, [ref.url for ref in result_urls]))

    def job_results_status(self, job_id: str) -> str:
        status = self._statuses.pop(0)
        if not self._statuses:
            self._statuses.append("ok")
        return status

    def job_results_error(self, job_id: str) -> str | None:
        return self.error

    def input_parameters_values(self, job_id: str) -> list[ParameterValues]:
        return [ParameterValues(name="K", value=[1, 2, 3])]

    def job_repetitions(self, job_id: str) -> list[int]:
        return [0, 1]


def _context() -> tuple[_FakeJobsReader, _FakeSimulatorsRepo, _StubVisualization]:
    return _FakeJobsReader(), _FakeSimulatorsRepo(), _StubVisualization()


def test_begin_job_visualization_reports_error_status() -> None:
    jobs, sims, viz = _context()
    analytics = _FakeAnalytics(statuses=["error"], error="download exploded")

    header = handle_begin_job_visualization(
        BeginJobVisualization(job_id="job-1"), jobs, sims, analytics, viz
    )

    assert header.results_status == "error"
    assert header.results_error == "download exploded"
    assert header.constants is None
    assert header.input_params == [("K", "int"), ("time", "float")]
    assert header.plot_types == ["Line", "Scatter"]


def test_begin_job_visualization_builds_constants_when_ok() -> None:
    jobs, sims, viz = _context()
    analytics = _FakeAnalytics(statuses=["ok"])

    header = handle_begin_job_visualization(
        BeginJobVisualization(job_id="job-1"), jobs, sims, analytics, viz
    )

    assert header.results_status == "ok"
    assert header.results_error is None
    assert isinstance(header.constants, JobVisualizationConstants)


def test_retry_job_visualization_forwards_resolved_target() -> None:
    jobs, sims, _ = _context()
    analytics = _FakeAnalytics()

    handle_retry_job_results(RetryJobResults(job_id="job-1"), jobs, sims, analytics)

    assert analytics.retried == [("job-1", "s3://root", ["s3://root/res.csv.zip"])]
    assert analytics.initialized == []


def test_job_repetitions_fail_fast_on_error_status() -> None:
    analytics = _FakeAnalytics(statuses=["error"], error="boom")

    try:
        handle_get_job_repetitions(GetJobRepetitions(job_id="job-1"), analytics)
    except ExternalServiceError as exc:
        assert "boom" in str(exc)
    else:
        raise AssertionError("expected ExternalServiceError")


def test_constant_params_fail_fast_on_error_status() -> None:
    analytics = _FakeAnalytics(statuses=["error"], error="boom")

    try:
        handle_get_visualization_constant_params(
            GetVisualizationConstantParams(job_id="job-1", selected_x="K"),
            analytics,
        )
    except ExternalServiceError as exc:
        assert "boom" in str(exc)
    else:
        raise AssertionError("expected ExternalServiceError")


def test_job_repetitions_waits_for_processing_to_finish() -> None:
    analytics = _FakeAnalytics(statuses=["processing", "ok"])

    repetitions = handle_get_job_repetitions(GetJobRepetitions(job_id="job-1"), analytics)

    assert repetitions == [0, 1]