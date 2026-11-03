from __future__ import annotations

from contextlib import contextmanager

from services.front.main import app
from use_case_contracts.dtos import (
    JobVisualizationConstants,
    JobVisualizationHeader,
    JobVisualizationResult,
    JobVisualizationStatus,
    MonteCarloFilteringPlotState,
    MonteCarloFilteringStatistic,
    ParameterValues,
)
from use_case_contracts.messages import (
    BeginJobVisualization,
    GetJobVisualizationStatus,
    GetMonteCarloFilteringPlotState,
    RetryJobResults,
    VisualizeDisasterStages,
    VisualizeJob,
    VisualizeMonteCarloFiltering,
)


@contextmanager
def _installed(usecases):
    previous_usecases = app.extensions.get("usecases")
    previous_secret = app.config.get("SECRET_KEY")
    app.extensions["usecases"] = usecases
    app.config["SECRET_KEY"] = "test-secret"
    try:
        yield
    finally:
        app.config["SECRET_KEY"] = previous_secret
        if previous_usecases is None:
            app.extensions.pop("usecases", None)
        else:
            app.extensions["usecases"] = previous_usecases


def _statistic(name: str) -> MonteCarloFilteringStatistic:
    return MonteCarloFilteringStatistic(
        parameter=name,
        d_statistic=0.8,
        p_value=0.01,
        reject_h0=True,
        behavioural_samples=5,
        non_behavioural_samples=5,
    )


def _monte_carlo_result() -> JobVisualizationResult:
    return JobVisualizationResult(
        plot_type="ECDF",
        plot_html="<div>plot-html</div>",
        waiting_message="done",
        monte_carlo_statistics=[_statistic("A"), _statistic("B")],
        plot_id="plot-1",
        plot_status="done",
    )


class _FakeUseCases:
    """Superset fake for visualization page tests.

    All visualization test modules share this: the switch on message type plus the
    constructor knobs (constants/constants_ready, output_params, input_params,
    result, plot_state, results_status/results_error) cover every mode.
    """

    def __init__(
        self,
        constants: ParameterValues | None = None,
        output_params: list[tuple[str, str]] | None = None,
        input_params: list[tuple[str, str]] | None = None,
        result=None,
        plot_state: MonteCarloFilteringPlotState | None = None,
        results_status: str | None = None,
        results_error: str | None = None,
        constants_ready: bool = True,
    ) -> None:
        self.messages: list = []
        if constants is None:
            constants = ParameterValues(name="K", value=[1, 2, 3])
        if output_params is None:
            output_params = [("outcome", "float"), ("count", "float")]
        if input_params is None:
            input_params = [("K", "float"), ("time", "float")]
        self._constants = constants
        self._constants_ready = constants_ready
        self._output_params = output_params
        self._input_params = input_params
        self._result = result
        self._plot_state = plot_state or MonteCarloFilteringPlotState(
            plot_status="done",
            plot_html="<div>plot-html</div>",
            scatter_plot_status="done",
            scatter_plot_html="<div>scatter-plot-html</div>",
        )
        self._results_status = results_status
        self._results_error = results_error

    def handle(self, message):
        self.messages.append(message)
        if isinstance(message, RetryJobResults):
            return None
        if isinstance(message, BeginJobVisualization):
            return JobVisualizationHeader(
                warning="",
                input_params=self._input_params,
                output_params=self._output_params,
                constants=(
                    None
                    if (not self._constants_ready or self._results_status is not None)
                    else JobVisualizationConstants(constants=[self._constants])
                ),
                plot_types=["Line", "Boxplot", "Scatter"],
                results_status=self._results_status,
                results_error=self._results_error,
            )
        if isinstance(message, VisualizeMonteCarloFiltering):
            return self._result or _monte_carlo_result()
        if isinstance(message, VisualizeJob):
            return self._result or JobVisualizationResult(
                plot_type="Line",
                plot_html=None,
                waiting_message="Plot is being generated.",
            )
        if isinstance(message, VisualizeDisasterStages):
            return self._result or JobVisualizationResult(
                plot_type="Line",
                plot_html=None,
                waiting_message="Plot is being generated.",
            )
        if isinstance(message, GetMonteCarloFilteringPlotState):
            if not message.scatter_plot_id:
                return MonteCarloFilteringPlotState(
                    plot_status="done",
                    plot_html="<div>plot-html</div>",
                )
            return self._plot_state
        if isinstance(message, GetJobVisualizationStatus):
            return JobVisualizationStatus(
                results_status=self._results_status or "ok",
                results_error=self._results_error,
            )
        raise AssertionError(f"Unexpected message: {message!r}")


class _FakeNoConstantsUseCases(_FakeUseCases):
    """BeginJobVisualization returns a header without constants, as analytics
    does while it is still building job results."""

    def __init__(self, **kwargs) -> None:
        super().__init__(constants_ready=False, **kwargs)


class _FakeResultsStatusUseCases(_FakeUseCases):
    def __init__(
        self,
        results_status: str,
        results_error: str | None = None,
        output_params: list[tuple[str, str]] | None = None,
    ) -> None:
        super().__init__(
            constants_ready=False,
            output_params=output_params,
            results_status=results_status,
            results_error=results_error,
        )