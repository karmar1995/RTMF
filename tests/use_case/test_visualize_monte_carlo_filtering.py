from __future__ import annotations

import csv
import inspect
import io
import zipfile

from services.use_case.handlers.visualizations import (
    handle_get_monte_carlo_filtering_plot_state,
    handle_visualize_monte_carlo_filtering,
)
from use_case_contracts.dtos import (
    MonteCarloFilteringResult,
    MonteCarloFilteringRun,
    MonteCarloFilteringStatistic,
    ParameterSpec,
    ParamType,
    ResultRef,
    SimulatorDetails,
    VisualizationTarget,
)
from use_case_contracts.messages import (
    GetMonteCarloFilteringPlotState,
    VisualizeMonteCarloFiltering,
)


def _statistic(name: str) -> MonteCarloFilteringStatistic:
    return MonteCarloFilteringStatistic(
        parameter=name,
        d_statistic=0.8,
        p_value=0.01,
        reject_h0=True,
        behavioural_samples=5,
        non_behavioural_samples=5,
        behavioural_ecdf_x=[0.1, 0.2, 0.3, 0.4, 0.5],
        behavioural_ecdf_y=[0.2, 0.4, 0.6, 0.8, 1.0],
        non_behavioural_ecdf_x=[2.0, 2.1, 2.2, 2.3],
        non_behavioural_ecdf_y=[0.25, 0.5, 0.75, 1.0],
    )


def _result() -> MonteCarloFilteringResult:
    return MonteCarloFilteringResult(
        output_column="outcome",
        threshold=0.5,
        direction="greater",
        aggregation=None,
        behavioural_count=2,
        non_behavioural_count=2,
        runs=[
            MonteCarloFilteringRun(
                index=0,
                behavioural=True,
                parameters={"A": 0.1, "B": 1.5},
                outputs={"outcome": 2.5},
            ),
            MonteCarloFilteringRun(
                index=1,
                behavioural=True,
                parameters={"A": 0.2, "B": 1.5},
                outputs={"outcome": 2.8},
            ),
            MonteCarloFilteringRun(
                index=2,
                behavioural=False,
                parameters={"A": 0.8, "B": 1.5},
                outputs={"outcome": 0.5},
            ),
            MonteCarloFilteringRun(
                index=3,
                behavioural=False,
                parameters={"A": 0.9, "B": 1.5},
                outputs={"outcome": 0.4},
            ),
        ],
        parameters=[_statistic("A"), _statistic("B")],
    )


class _FakeJobsRepo:
    def resolve_visualization_target(self, target_id):
        return VisualizationTarget(
            id=target_id,
            simulator_id="t1",
            job_root_url="https://host/job",
            result_urls=[
                ResultRef(sub_job_id="r0", url="https://host/results/0.zip"),
                ResultRef(sub_job_id="r1", url="https://host/results/1.zip"),
            ],
            is_evaluation=False,
        )


class _FakeSimulatorsRepo:
    def get(self, simulator_id):
        return SimulatorDetails(
            model_name="TestModel",
            version="1.0.0",
            created_at="2026-05-28T14:10:00",
            bin_url="rtmf/test-model:1.0.0",
            input_params=[
                ParameterSpec("A", ParamType.FLOAT),
                ParameterSpec("B", ParamType.FLOAT),
            ],
            output_params=[ParameterSpec("outcome", ParamType.FLOAT)],
        )


class _FakeAnalytics:
    def __init__(self) -> None:
        self.last_kwargs = None
        self.result = _result()
        self.error: Exception | None = None

    def analyze_monte_carlo_filtering(self, **kwargs):
        self.last_kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.result


class _FakeVisualization:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, object]] = []

    def render_plot(self, zip_csv_bytes: bytes, plot_spec):
        self.calls.append((zip_csv_bytes, plot_spec))
        return f"plot-{len(self.calls)}"

    def get_plot_status(self, plot_id):
        return "done"

    def get_plot_html(self, plot_id):
        return f"<div>{plot_id}</div>"


def _read_csv_rows(zip_bytes: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = [name for name in zf.namelist() if not name.endswith("/")]
        assert len(names) == 1
        content = zf.read(names[0]).decode("utf-8")
    return list(csv.reader(io.StringIO(content)))


def test_handler_analyzes_and_renders_ecdf_and_scatter_plots() -> None:
    analytics = _FakeAnalytics()
    visualization = _FakeVisualization()

    message = VisualizeMonteCarloFiltering(
        job_id="job-1",
        output_column="outcome",
        threshold=0.5,
        direction="greater",
        aggregation=None,
    )

    result = handle_visualize_monte_carlo_filtering(
        jobs_repo=_FakeJobsRepo(),
        simulators_repo=_FakeSimulatorsRepo(),
        analytics=analytics,
        visualization=visualization,
        message=message,
    )

    kwargs = analytics.last_kwargs
    assert kwargs["results_urls"] == [
        "https://host/results/0.zip",
        "https://host/results/1.zip",
    ]
    assert kwargs["problem"] == {"names": ["A", "B"]}
    assert kwargs["output_column"] == "outcome"
    assert kwargs["threshold"] == 0.5
    assert kwargs["direction"] == "greater"
    assert kwargs["aggregation"] is None
    assert kwargs["output_aggregations"] is None
    assert kwargs["run_output_columns"] == ["outcome"]

    assert len(visualization.calls) == 2
    ecdf_bytes, ecdf_spec = visualization.calls[0]
    scatter_bytes, scatter_spec = visualization.calls[1]

    assert ecdf_spec.plot_type == "ECDF"
    rows = _read_csv_rows(ecdf_bytes)
    assert rows[0] == ["parameter", "group", "x", "cdf", "d_statistic", "reject_h0"]
    assert len(rows) == 1 + 2 * (5 + 4)
    groups = {row[1] for row in rows[1:]}
    assert groups == {"behavioural", "non_behavioural"}

    assert scatter_spec.plot_type == "Scatter"
    assert scatter_spec.xaxis_title == "A"
    assert scatter_spec.yaxis_title == "outcome"
    assert scatter_spec.series_hover_templates == {
        "Behavioural": (
            "<b>Behavioural</b><br>A: %{x:.2f}<br>outcome: %{y:.2f}"
            "<extra></extra>"
        ),
        "Non-behavioural": (
            "<b>Non-behavioural</b><br>A: %{x:.2f}<br>outcome: %{y:.2f}"
            "<extra></extra>"
        ),
    }
    assert scatter_spec.series_styles == {
        "Behavioural": {
            "name": "Behavioural",
            "color": "#2563eb",
            "opacity": 0.7,
        },
        "Non-behavioural": {
            "name": "Non-behavioural",
            "color": "#dc2626",
            "opacity": 0.7,
        },
    }
    scatter_rows = _read_csv_rows(scatter_bytes)
    # Behavioural is deliberately the last column: the plot service draws traces in
    # column order, so blue behavioural points end up over the red ones.
    assert scatter_rows[0] == ["A", "Non-behavioural", "Behavioural"]
    assert scatter_rows[1] == ["0.1", "", "2.5"]
    assert scatter_rows[2] == ["0.2", "", "2.8"]
    assert scatter_rows[3] == ["0.8", "0.5", ""]
    assert scatter_rows[4] == ["0.9", "0.4", ""]

    assert result.plot_type == "ECDF"
    assert result.plot_html == "<div>plot-1</div>"
    assert result.plot_id == "plot-1"
    assert result.plot_status == "done"
    assert len(result.monte_carlo_statistics) == 2
    assert result.waiting_message == "Plot generated."
    assert result.behavioural_count == 2
    assert result.non_behavioural_count == 2

    assert result.scatter_plot_id == "plot-2"
    assert result.scatter_plot_status == "done"
    assert result.scatter_plot_html == "<div>plot-2</div>"
    assert result.scatter_x == "A"
    assert result.scatter_y == "outcome"
    assert result.scatter_input_options == [("A", "float"), ("B", "float")]
    assert result.scatter_output_options == [("outcome", "float")]

    assert result.simulator_id == "t1"
    assert result.evaluation_output == "outcome"
    assert result.evaluation_aggregation is None
    assert result.behavioural_input_ranges == {"A": [0.1, 0.2], "B": [1.5, 1.5]}


def test_handler_uses_requested_scatter_axes_and_aggregation() -> None:
    analytics = _FakeAnalytics()
    visualization = _FakeVisualization()

    result = handle_visualize_monte_carlo_filtering(
        jobs_repo=_FakeJobsRepo(),
        simulators_repo=_FakeSimulatorsRepo(),
        analytics=analytics,
        visualization=visualization,
        message=VisualizeMonteCarloFiltering(
            job_id="job-1",
            output_column="outcome",
            threshold=0.5,
            direction="less",
            aggregation="max",
            scatter_x="B",
            scatter_y="outcome",
            scatter_aggregation="mean",
        ),
    )

    assert analytics.last_kwargs["aggregation"] == "max"
    assert analytics.last_kwargs["direction"] == "less"
    assert analytics.last_kwargs["output_aggregations"] == {"outcome": "mean"}
    assert analytics.last_kwargs["run_output_columns"] == ["outcome"]
    assert result.evaluation_aggregation == "max"

    _, scatter_spec = visualization.calls[1]
    assert scatter_spec.xaxis_title == "B"
    assert scatter_spec.yaxis_title == "outcome"


def test_handler_rejects_unknown_output() -> None:
    analytics = _FakeAnalytics()
    result = handle_visualize_monte_carlo_filtering(
        jobs_repo=_FakeJobsRepo(),
        simulators_repo=_FakeSimulatorsRepo(),
        analytics=analytics,
        visualization=_FakeVisualization(),
        message=VisualizeMonteCarloFiltering(
            job_id="job-1",
            output_column="missing",
            threshold=0.5,
            direction="greater",
        ),
    )

    assert result.plot_html is None
    assert "not an output parameter" in result.waiting_message
    assert analytics.last_kwargs is None


def test_handler_rejects_unknown_scatter_x() -> None:
    analytics = _FakeAnalytics()
    result = handle_visualize_monte_carlo_filtering(
        jobs_repo=_FakeJobsRepo(),
        simulators_repo=_FakeSimulatorsRepo(),
        analytics=analytics,
        visualization=_FakeVisualization(),
        message=VisualizeMonteCarloFiltering(
            job_id="job-1",
            output_column="outcome",
            threshold=0.5,
            direction="greater",
            scatter_x="not_an_input",
        ),
    )

    assert result.plot_html is None
    assert "Scatter X" in result.waiting_message
    assert analytics.last_kwargs is None


def test_handler_returns_waiting_message_when_analytics_fails() -> None:
    from use_case_contracts.errors import ExternalServiceError

    analytics = _FakeAnalytics()
    analytics.error = ExternalServiceError("No behavioural samples found")

    result = handle_visualize_monte_carlo_filtering(
        jobs_repo=_FakeJobsRepo(),
        simulators_repo=_FakeSimulatorsRepo(),
        analytics=analytics,
        visualization=_FakeVisualization(),
        message=VisualizeMonteCarloFiltering(
            job_id="job-1",
            output_column="outcome",
            threshold=0.5,
            direction="greater",
        ),
    )

    assert result.plot_html is None
    assert result.waiting_message == "No behavioural samples found"


class _RunningVisualization(_FakeVisualization):
    def get_plot_status(self, plot_id):
        return "running"


def test_handler_reports_running_scatter_without_html() -> None:
    result = handle_visualize_monte_carlo_filtering(
        jobs_repo=_FakeJobsRepo(),
        simulators_repo=_FakeSimulatorsRepo(),
        analytics=_FakeAnalytics(),
        visualization=_RunningVisualization(),
        message=VisualizeMonteCarloFiltering(
            job_id="job-1",
            output_column="outcome",
            threshold=0.5,
            direction="greater",
        ),
    )

    assert result.plot_status == "running"
    assert result.plot_html is None
    assert result.scatter_plot_id == "plot-2"
    assert result.scatter_plot_status == "running"
    assert result.scatter_plot_html is None
    assert result.waiting_message == "Waiting for the plot, current status: running"


class _StatusOnlyVisualization:
    def __init__(self, statuses: dict[str, str]) -> None:
        self.statuses = statuses
        self.status_calls: list[str] = []
        self.html_calls: list[str] = []

    def get_plot_status(self, plot_id):
        self.status_calls.append(plot_id)
        return self.statuses[plot_id]

    def get_plot_html(self, plot_id):
        self.html_calls.append(plot_id)
        return f"<div>{plot_id}</div>"


def test_plot_state_handler_reports_both_plots_without_analytics() -> None:
    visualization = _StatusOnlyVisualization(
        {"plot-1": "done", "plot-2": "running"}
    )

    state = handle_get_monte_carlo_filtering_plot_state(
        GetMonteCarloFilteringPlotState(
            job_id="job-1",
            plot_id="plot-1",
            scatter_plot_id="plot-2",
        ),
        visualization=visualization,
    )

    assert state.plot_status == "done"
    assert state.plot_html == "<div>plot-1</div>"
    assert state.scatter_plot_status == "running"
    assert state.scatter_plot_html is None
    assert sorted(visualization.status_calls) == ["plot-1", "plot-2"]
    assert visualization.html_calls == ["plot-1"]


def test_plot_state_handler_fetches_html_only_for_finished_plots() -> None:
    visualization = _StatusOnlyVisualization({"plot-1": "done", "plot-2": "done"})

    state = handle_get_monte_carlo_filtering_plot_state(
        GetMonteCarloFilteringPlotState(
            job_id="job-1",
            plot_id="plot-1",
            scatter_plot_id="plot-2",
        ),
        visualization=visualization,
    )

    assert state.plot_html == "<div>plot-1</div>"
    assert state.scatter_plot_html == "<div>plot-2</div>"
    assert sorted(visualization.html_calls) == ["plot-1", "plot-2"]


def test_plot_state_handler_omits_scatter_plot_when_not_requested() -> None:
    visualization = _StatusOnlyVisualization({"plot-1": "running"})

    state = handle_get_monte_carlo_filtering_plot_state(
        GetMonteCarloFilteringPlotState(job_id="job-1", plot_id="plot-1"),
        visualization=visualization,
    )

    assert state.plot_status == "running"
    assert state.plot_html is None
    assert state.scatter_plot_status is None
    assert state.scatter_plot_html is None
    assert visualization.status_calls == ["plot-1"]


def test_plot_state_handler_reports_error_without_html() -> None:
    visualization = _StatusOnlyVisualization(
        {"plot-1": "error", "plot-2": "error"}
    )

    state = handle_get_monte_carlo_filtering_plot_state(
        GetMonteCarloFilteringPlotState(
            job_id="job-1",
            plot_id="plot-1",
            scatter_plot_id="plot-2",
        ),
        visualization=visualization,
    )

    assert state.plot_status == "error"
    assert state.plot_html is None
    assert state.scatter_plot_status == "error"
    assert state.scatter_plot_html is None
    assert visualization.html_calls == []


def test_plot_state_handler_requires_only_the_visualization_port() -> None:
    parameters = inspect.signature(
        handle_get_monte_carlo_filtering_plot_state
    ).parameters

    assert set(parameters) == {"message", "visualization"}
