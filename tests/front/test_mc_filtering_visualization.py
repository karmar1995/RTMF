from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qs, urlparse

from services.front.main import app
from use_case_contracts.dtos import (
    MonteCarloFilteringPlotResult,
    MonteCarloFilteringPlotState,
)
from use_case_contracts.errors import ExternalServiceError
from use_case_contracts.messages import (
    GetMonteCarloFilteringPlotState,
    RetryJobResults,
    VisualizeMonteCarloFiltering,
)
from conftest import (
    _FakeNoConstantsUseCases,
    _FakeResultsStatusUseCases,
    _FakeUseCases,
    _installed,
    _monte_carlo_result,
    _statistic,
)


def test_monte_carlo_filtering_page_renders_config() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/monte-carlo-filtering"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Monte Carlo Filtering" in body
    assert 'name="y"' in body
    assert 'name="threshold"' in body
    assert 'name="direction"' in body
    assert 'value="greater"' in body
    assert 'value="less"' in body


def test_monte_carlo_filtering_page_shows_aggregation_for_timeseries() -> None:
    usecases = _FakeUseCases(output_params=[("outcome", "float_ts"), ("count", "float")])
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/monte-carlo-filtering"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'id="aggregation"' in body
    assert "Time-series aggregation" in body


def test_monte_carlo_filtering_page_never_meta_refreshes() -> None:
    """The config page drives its own flow: no constants needed, so it must not
    re-enqueue-and-reload every 5 seconds while analytics is still building."""
    usecases = _FakeNoConstantsUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/monte-carlo-filtering"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'http-equiv="refresh"' not in body
    assert 'name="y"' in body


def test_monte_carlo_filtering_page_error_status_renders_error_card() -> None:
    usecases = _FakeResultsStatusUseCases(results_status="error", results_error="boom")
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/monte-carlo-filtering"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Failed to load job results: boom" in body
    assert (
        'action="/simulation-groups/job-1/visualize/retry-results"' in body
    )
    assert "Retry loading job results" in body
    assert 'http-equiv="refresh"' not in body


def test_monte_carlo_filtering_page_has_no_preview_controls() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/monte-carlo-filtering"
            "?y=outcome&threshold=0.5&direction=greater"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Preview" not in body
    assert "data-preview-url" not in body
    assert "maxAttempts" not in body
    assert not any(
        isinstance(m, VisualizeMonteCarloFiltering) for m in usecases.messages
    )


def test_monte_carlo_filtering_preview_route_is_removed() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().post(
            "/simulation-groups/job-1/visualize/monte-carlo-filtering/preview",
            data={"y": "outcome", "threshold": "0.5", "direction": "greater"},
        )

    assert response.status_code == 404
    assert not any(
        isinstance(m, VisualizeMonteCarloFiltering) for m in usecases.messages
    )


def test_retry_results_route_forwards_message_and_redirects() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().post(
            "/simulation-groups/job-1/visualize/retry-results",
            data={"next": "/simulation-groups/job-1/visualize/monte-carlo-filtering"},
        )

    assert response.status_code == 302
    assert response.headers["Location"] == (
        "/simulation-groups/job-1/visualize/monte-carlo-filtering"
    )
    assert isinstance(usecases.messages[-1], RetryJobResults)
    assert usecases.messages[-1].job_id == "job-1"


def test_monte_carlo_filtering_plot_state_route_returns_status_only() -> None:
    usecases = _FakeUseCases(
        plot_state=MonteCarloFilteringPlotState(
            plot_status="running",
            plot_html=None,
            scatter_plot_status="running",
            scatter_plot_html=None,
        )
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/monte-carlo-filtering/plots"
            "/plot-1/plot-2"
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "plot_status": "running",
        "plot_html": None,
        "scatter_plot_status": "running",
        "scatter_plot_html": None,
    }
    assert not any(
        isinstance(m, VisualizeMonteCarloFiltering) for m in usecases.messages
    )


def test_monte_carlo_filtering_plot_state_route_returns_rendered_html() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/monte-carlo-filtering/plots/plot-1"
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["plot_status"] == "done"
    assert payload["plot_html"] == "<div>plot-html</div>"
    assert payload["scatter_plot_status"] is None


def test_monte_carlo_filtering_plot_state_reports_external_service_failure() -> None:
    class _FailingUseCases(_FakeUseCases):
        def handle(self, message):
            if isinstance(message, GetMonteCarloFilteringPlotState):
                self.messages.append(message)
                raise ExternalServiceError("visualization is down")
            return super().handle(message)

    usecases = _FailingUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/monte-carlo-filtering/plots/plot-1"
        )

    assert response.status_code == 502
    assert response.get_json() == {"error": "visualization is down"}


def test_monte_carlo_filtering_plot_submits_message() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=outcome&threshold=0.5&direction=greater"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200

    message = usecases.messages[-1]
    assert isinstance(message, VisualizeMonteCarloFiltering)
    assert message.job_id == "job-1"
    assert message.output_column == "outcome"
    assert message.threshold == 0.5
    assert message.direction == "greater"
    assert message.aggregation is None
    assert message.scatter_x is None
    assert message.scatter_y is None
    assert message.scatter_aggregation is None
    assert "plot-html" in body


def test_monte_carlo_filtering_plot_forwards_scatter_arguments() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=outcome&threshold=0.5&direction=greater"
            "&scatter_x=A&scatter_y=count&scatter_aggregation=mean"
        )

    assert response.status_code == 200

    message = usecases.messages[-1]
    assert isinstance(message, VisualizeMonteCarloFiltering)
    assert message.scatter_x == "A"
    assert message.scatter_y == "count"
    assert message.scatter_aggregation == "mean"


def _selected_scatter_aggregation(body: str) -> str | None:
    """Value of the selected option in the Y time-series aggregation select ('' means None)."""
    block = body.split('id="scatter_aggregation"', 1)[1].split("</select>", 1)[0]
    match = re.search(r'<option value="([^"]*)"\s+selected', block)
    return match.group(1) if match else None


_TS_OUTPUT_OPTIONS = [("queue_ts", "float_ts"), ("count", "float")]


def test_monte_carlo_filtering_plot_seeds_scatter_aggregation_from_form() -> None:
    """First arrival from the MCF form carries only `aggregation`, not `scatter_aggregation`."""
    usecases = _FakeUseCases(
        result=_scatter_result(scatter_y="queue_ts", output_options=_TS_OUTPUT_OPTIONS)
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=queue_ts&aggregation=mean&threshold=2.5&direction=greater"
        )

    assert response.status_code == 200
    assert _selected_scatter_aggregation(response.get_data(as_text=True)) == "mean"

    message = usecases.messages[-1]
    assert isinstance(message, VisualizeMonteCarloFiltering)
    assert message.aggregation == "mean"
    assert message.scatter_aggregation == "mean"


def test_monte_carlo_filtering_plot_keeps_explicit_no_scatter_aggregation() -> None:
    """An explicitly empty scatter_aggregation means the user picked None: do not re-seed."""
    usecases = _FakeUseCases(
        result=_scatter_result(scatter_y="queue_ts", output_options=_TS_OUTPUT_OPTIONS)
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=queue_ts&aggregation=mean&threshold=2.5&direction=greater"
            "&scatter_y=queue_ts&scatter_aggregation="
        )

    assert response.status_code == 200
    assert _selected_scatter_aggregation(response.get_data(as_text=True)) == ""

    message = usecases.messages[-1]
    assert isinstance(message, VisualizeMonteCarloFiltering)
    assert message.aggregation == "mean"
    assert message.scatter_aggregation is None


def test_monte_carlo_filtering_plot_prefers_explicit_scatter_aggregation() -> None:
    usecases = _FakeUseCases(
        result=_scatter_result(scatter_y="queue_ts", output_options=_TS_OUTPUT_OPTIONS)
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=queue_ts&aggregation=mean&threshold=2.5&direction=greater"
            "&scatter_y=queue_ts&scatter_aggregation=p95"
        )

    assert response.status_code == 200
    assert _selected_scatter_aggregation(response.get_data(as_text=True)) == "p95"

    message = usecases.messages[-1]
    assert isinstance(message, VisualizeMonteCarloFiltering)
    assert message.scatter_aggregation == "p95"


def test_monte_carlo_filtering_plot_does_not_seed_scalar_scatter_y() -> None:
    """A scalar Y has no aggregation; nothing is seeded even though the form sent one."""
    usecases = _FakeUseCases(result=_scatter_result(scatter_y="count"))
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=count&aggregation=mean&threshold=2.5&direction=greater"
            "&scatter_y=count"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Y time-series aggregation" in body
    assert _selected_scatter_aggregation(body) == ""


def test_monte_carlo_filtering_plot_requiring_threshold() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot?plot=1&mode=mcf&y=outcome&direction=greater"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Output, threshold and direction are required." in body
    assert not any(
        isinstance(m, VisualizeMonteCarloFiltering) for m in usecases.messages
    )


def test_monte_carlo_filtering_plot_rejects_bad_threshold() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot?plot=1&mode=mcf&y=outcome&threshold=abc&direction=greater"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Threshold must be a number." in body


def test_monte_carlo_filtering_plot_rejects_bad_direction() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot?plot=1&mode=mcf&y=outcome&threshold=0.5&direction=up"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "must be &#39;greater&#39; or &#39;less&#39;" in body


def test_monte_carlo_filtering_plot_renders_scatter_card() -> None:
    usecases = _FakeUseCases(result=_scatter_result())
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=outcome&threshold=0.5&direction=greater"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Runs — behavioural vs non-behavioural" in body
    assert 'id="mcf-scatter-form"' in body
    assert 'name="scatter_x"' in body
    assert 'name="scatter_y"' in body
    assert "scatter-plot-html" in body
    assert "Behavioural: 2, non-behavioural: 2." in body
    assert '<option value="A" selected>A</option>' in body
    assert '<option value="count"' in body
    assert '<input type="hidden" name="threshold" value="0.5">' in body
    assert '<input type="hidden" name="direction" value="greater">' in body
    assert '<input type="hidden" name="mode" value="mcf">' in body


def test_monte_carlo_filtering_scatter_hides_aggregation_for_scalar_output() -> None:
    usecases = _FakeUseCases(result=_scatter_result())
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=outcome&threshold=0.5&direction=greater"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<div class="col-lg-4 d-none" id="scatter-aggregation-row">' in body


def test_monte_carlo_filtering_scatter_shows_aggregation_for_timeseries_output() -> None:
    usecases = _FakeUseCases(
        result=_scatter_result(
            scatter_y="count_ts",
            output_options=[("count_ts", "float_ts")],
        )
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=outcome&threshold=0.5&direction=greater"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<div class="col-lg-4 " id="scatter-aggregation-row">' in body
    assert "Applied only to the scatter Y" in body


def test_monte_carlo_filtering_scatter_controls_share_one_aligned_row() -> None:
    """X, Y and Y-aggregation must sit on one level.

    The aggregation column carries an extra form-text, so bottom-aligning the row
    pushed the X and Y selects a line below it.
    """
    usecases = _FakeUseCases(
        result=_scatter_result(
            scatter_y="count_ts",
            output_options=[("count_ts", "float_ts")],
        )
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=outcome&threshold=0.5&direction=greater"
        )

    assert response.status_code == 200
    form = (
        response.get_data(as_text=True)
        .split('id="mcf-scatter-form"', 1)[1]
        .split("</form>", 1)[0]
    )
    assert 'class="row g-3 align-items-start"' in form
    assert "align-items-end" not in form
    assert form.count('class="col-lg-4') == 3
    assert '<div class="col-lg-4 " id="scatter-aggregation-row">' in form
    assert "Applied only to the scatter Y" in form


_SCATTER_FORM_URL = (
    "/simulation-groups/job-1/plot"
    "?plot=1&mode=mcf&y=queue_ts&threshold=2.5&direction=greater&aggregation=mean"
)


def _scatter_form(body: str) -> str:
    """The scatter form only, so page-wide 'disabled' checks stay scoped to its controls."""
    return body.split('id="mcf-scatter-form"', 1)[1].split("</form>", 1)[0]


def _locked_control_ids(form: str) -> set[str]:
    return set(re.findall(r'<(?:select|button)[^>]*\bid="([^"]+)"[^>]*\sdisabled', form))


def test_monte_carlo_filtering_scatter_form_is_locked_while_the_scatter_plot_runs() -> None:
    usecases = _FakeUseCases(
        result=_scatter_result(
            scatter_y="queue_ts",
            output_options=_TS_OUTPUT_OPTIONS,
            scatter_html=None,
            scatter_status="running",
        )
    )
    with _installed(usecases):
        response = app.test_client().get(_SCATTER_FORM_URL)

    assert response.status_code == 200
    form = _scatter_form(response.get_data(as_text=True))
    assert _locked_control_ids(form) == {
        "scatter_x",
        "scatter_y",
        "scatter_aggregation",
        "mcf-scatter-submit",
    }


def test_monte_carlo_filtering_scatter_form_is_locked_while_only_the_ecdf_runs() -> None:
    """A running ECDF alone must lock the form, even when the scatter is already rendered."""
    usecases = _FakeUseCases(
        result=_scatter_result(
            scatter_y="queue_ts",
            output_options=_TS_OUTPUT_OPTIONS,
            plot_html=None,
            plot_status="running",
        )
    )
    with _installed(usecases):
        response = app.test_client().get(_SCATTER_FORM_URL)

    assert response.status_code == 200
    form = _scatter_form(response.get_data(as_text=True))
    assert "mcf-scatter-submit" in _locked_control_ids(form)


def test_monte_carlo_filtering_scatter_form_is_unlocked_when_both_plots_finish() -> None:
    usecases = _FakeUseCases(
        result=_scatter_result(
            scatter_y="queue_ts",
            output_options=_TS_OUTPUT_OPTIONS,
        )
    )
    with _installed(usecases):
        response = app.test_client().get(_SCATTER_FORM_URL)

    assert response.status_code == 200
    form = _scatter_form(response.get_data(as_text=True))
    assert _locked_control_ids(form) == set()
    assert "disabled" not in form


def test_monte_carlo_filtering_scatter_form_is_unlocked_after_a_failure() -> None:
    """A failed render must not leave the form permanently dead; a retry has to be possible."""
    usecases = _FakeUseCases(
        result=_scatter_result(
            scatter_y="queue_ts",
            output_options=_TS_OUTPUT_OPTIONS,
            scatter_html=None,
            scatter_status="error",
        )
    )
    with _installed(usecases):
        response = app.test_client().get(_SCATTER_FORM_URL)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    form = _scatter_form(body)
    assert _locked_control_ids(form) == set()
    assert "Scatter plot generation failed." in body


def test_monte_carlo_filtering_generate_plot_button_disables_itself_on_submit() -> None:
    """The form page carries no plot state, so the guard has to be click-driven."""
    usecases = _FakeUseCases(output_params=[("queue_ts", "float_ts"), ("count", "float")])
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/monte-carlo-filtering"
            "?y=queue_ts&threshold=2.5&direction=greater&aggregation=mean"
        )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '<button type="submit" class="btn btn-primary" id="mcf-generate-plot">' in body
    # Rendered enabled: the visualization service has not been asked to render anything yet.
    assert re.search(r'id="mcf-generate-plot"[^>]*\sdisabled', body) is None
    assert 'form.addEventListener("submit"' in body
    # Back-navigation must not restore a dead button.
    assert 'window.addEventListener("pageshow"' in body
    assert "event.persisted" in body


def test_monte_carlo_filtering_update_scatter_button_disables_itself_on_submit() -> None:
    """Replicate the Generate Plot guard: the button greys the instant it is pressed.

    Only the button is disabled — it carries no value, so the selected axes still reach
    the GET. Disabling the selects themselves would drop them from the query string.
    """
    usecases = _FakeUseCases(result=_scatter_result())
    with _installed(usecases):
        response = app.test_client().get(_SCATTER_FORM_URL)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    form = _scatter_form(body)
    assert '<button type="submit" class="btn btn-outline-primary" id="mcf-scatter-submit">' in form
    assert re.search(r'id="mcf-scatter-submit"[^>]*\sdisabled', form) is None
    assert 'form.addEventListener("submit", function () {' in body
    assert "submitButton.disabled = true;" in body
    # Back-navigation must not restore the page with a dead button.
    assert "event.persisted" in body


def test_monte_carlo_filtering_scatter_uses_scroll_to_plot_anchor_fragment() -> None:
    """The Update-scatter form targets the plot anchor, so the reloaded page lands on
    the scatter plot out of the box. The fragment is only on this form: arrivals via
    Generate Plot keep starting at the top of the page.
    """
    usecases = _FakeUseCases(result=_scatter_result())
    with _installed(usecases):
        response = app.test_client().get(_SCATTER_FORM_URL)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '<div class="mt-3" id="mcf-scatter-plot-area">' in body
    assert 'id="mcf-scatter-form"' in body
    assert 'action="/simulation-groups/job-1/plot#mcf-scatter-plot-area"' in body
    assert "scrollIntoView" not in body


def test_monte_carlo_filtering_scatter_keeps_filter_inputs_hidden() -> None:
    usecases = _FakeUseCases(result=_scatter_result())
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=outcome&threshold=1.5&direction=less"
            "&aggregation=max"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<input type="hidden" name="threshold" value="1.5">' in body
    assert '<input type="hidden" name="direction" value="less">' in body
    assert '<input type="hidden" name="aggregation" value="max">' in body


def test_monte_carlo_filtering_plot_polls_instead_of_reloading() -> None:
    usecases = _FakeUseCases(
        result=_scatter_result(scatter_html=None, scatter_status="running")
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=outcome&threshold=0.5&direction=greater"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<meta http-equiv="refresh" content="5">' not in body
    assert "Scatter plot is being generated" in body
    assert 'id="mcf-scatter-target"' in body
    assert (
        "/simulation-groups/job-1/visualize/monte-carlo-filtering/plots"
        "/plot-1/plot-2"
    ) in body
    assert "visualization_polling.js" in body
    assert 'data-poll-mode="page-content"' not in body


def test_monte_carlo_filtering_plot_polls_each_target_with_its_own_url() -> None:
    """Both plots pending must not share one state URL.

    scatter_plot_id is a path segment, so the ECDF URL cannot report the scatter
    status. A single shared URL left the scatter stuck on "Still rendering".
    """
    usecases = _FakeUseCases(
        result=MonteCarloFilteringPlotResult(
            plot_type="ECDF",
            plot_html=None,
            waiting_message="Plot is being generated.",
            plot_id="plot-1",
            plot_status="running",
            scatter_plot_id="plot-2",
            scatter_plot_status="running",
            scatter_plot_html=None,
            scatter_x="A",
            scatter_y="count",
            scatter_input_options=[("A", "float")],
            scatter_output_options=[("count", "float")],
        )
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=count&threshold=0.5&direction=greater"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200

    found = re.findall(
        r'id="(mcf-[a-z]+-target)"[\s\S]*?data-status-key="([^"]*)"'
        r'[\s\S]*?data-html-key="([^"]*)"[\s\S]*?data-plot-state-url="([^"]*)"',
        body,
    )
    assert [(t, s, h) for t, s, h, _u in found] == [
        ("mcf-ecdf-target", "plot_status", "plot_html"),
        ("mcf-scatter-target", "scatter_plot_status", "scatter_plot_html"),
    ]

    urls = dict((target, url) for target, _s, _h, url in found)
    assert urls["mcf-ecdf-target"].endswith("/plots/plot-1")
    assert urls["mcf-scatter-target"].endswith("/plots/plot-1/plot-2")
    assert urls["mcf-ecdf-target"] != urls["mcf-scatter-target"]

    assert "visualization_polling.js" in body


def test_monte_carlo_filtering_ecdf_polling_target_is_rendered_when_pending() -> None:
    usecases = _FakeUseCases(
        result=MonteCarloFilteringPlotResult(
            plot_type="ECDF",
            plot_html=None,
            waiting_message="Plot is being generated.",
            plot_id="plot-1",
            plot_status="running",
            scatter_input_options=[("A", "float")],
            scatter_output_options=[("count", "float")],
        )
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=outcome&threshold=0.5&direction=greater"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<meta http-equiv="refresh" content="5">' not in body
    assert 'id="mcf-ecdf-target"' in body
    assert 'data-plot-status="running"' in body


def test_monte_carlo_filtering_plot_reports_scatter_failure() -> None:
    usecases = _FakeUseCases(
        result=_scatter_result(scatter_html=None, scatter_status="error")
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=outcome&threshold=0.5&direction=greater"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Scatter plot generation failed." in body
    assert '<meta http-equiv="refresh" content="5">' not in body


def test_monte_carlo_filtering_plot_without_scatter_options_omits_card() -> None:
    usecases = _FakeUseCases(result=_monte_carlo_result())
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=mcf&y=outcome&threshold=0.5&direction=greater"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "mcf-scatter-form" not in body


def _scatter_result(
    *,
    scatter_y: str = "count",
    output_options: list[tuple[str, str]] | None = None,
    scatter_html: str | None = "<div>scatter-plot-html</div>",
    scatter_status: str = "done",
    plot_html: str | None = "<div>plot-html</div>",
    plot_status: str = "done",
    simulator_id: str | None = None,
    evaluation_output: str | None = None,
    evaluation_aggregation: str | None = None,
    behavioural_input_ranges: dict[str, list[float]] | None = None,
) -> MonteCarloFilteringPlotResult:
    return MonteCarloFilteringPlotResult(
        plot_type="ECDF",
        plot_html=plot_html,
        waiting_message="Plot generated.",
        monte_carlo_statistics=[_statistic("A")],
        plot_id="plot-1",
        plot_status=plot_status,
        behavioural_count=2,
        non_behavioural_count=2,
        scatter_plot_id="plot-2",
        scatter_plot_status=scatter_status,
        scatter_plot_html=scatter_html,
        scatter_x="A",
        scatter_y=scatter_y,
        scatter_input_options=[("A", "float"), ("B", "float"), ("time", "float")],
        scatter_output_options=output_options
        or [("outcome", "float"), ("count", "float")],
        simulator_id=simulator_id,
        evaluation_output=evaluation_output,
        evaluation_aggregation=evaluation_aggregation,
        behavioural_input_ranges=behavioural_input_ranges,
    )


def test_monte_carlo_filtering_plot_links_to_evaluation_with_behavioural_ranges() -> None:
    usecases = _FakeUseCases(
        result=_scatter_result(
            simulator_id="model-1",
            evaluation_output="outcome",
            evaluation_aggregation="mean",
            behavioural_input_ranges={"A": [0.1, 0.2], "B": [1.5, 1.5]},
        )
    )
    with _installed(usecases):
        response = app.test_client().get(_SCATTER_FORM_URL)

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'id="mcf-open-evaluation"' in body

    match = re.search(
        r'id="mcf-open-evaluation"\s+href="([^"]+)"', body, re.DOTALL
    )
    assert match is not None
    link = urlparse(html.unescape(match.group(1)))
    assert link.path == "/evaluation/run"
    query = parse_qs(link.query)
    assert query["model"] == ["model-1"]
    assert query["output"] == ["outcome"]
    assert query["aggregation"] == ["mean"]
    assert json.loads(query["bounds"][0]) == {"A": [0.1, 0.2], "B": [1.5, 1.5]}


def test_monte_carlo_filtering_plot_hides_evaluation_link_without_ranges() -> None:
    usecases = _FakeUseCases(result=_scatter_result())
    with _installed(usecases):
        response = app.test_client().get(_SCATTER_FORM_URL)

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "mcf-open-evaluation" not in body

