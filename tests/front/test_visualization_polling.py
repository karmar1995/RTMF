from __future__ import annotations

from services.front.main import app
from use_case_contracts.dtos import JobVisualizationResult
from use_case_contracts.messages import (
    VisualizeDisasterStages,
    VisualizeJob,
)
from conftest import (
    _FakeResultsStatusUseCases,
    _FakeUseCases,
    _installed,
)


def test_generic_job_plot_state_route_reuses_plot_state_handler() -> None:
    """Non-Monte-Carlo plot pages share the same plot-state endpoint, keyed only on plot_id."""
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/plot-state/plot-1"
        )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.get_json()
    assert payload["plot_status"] == "done"
    assert payload["plot_html"] == "<div>plot-html</div>"


def test_time_series_plot_polls_in_place_while_pending() -> None:
    usecases = _FakeUseCases(
        result=JobVisualizationResult(
            plot_type="Line",
            plot_html=None,
            waiting_message="Plot is being generated.",
        )
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=single-time-series&series_0_x=A&series_0_y=B"
            "&series_0_stat=mean&series_1_x=A&series_1_y=B&series_1_stat=mean"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<meta http-equiv="refresh" content="5">' not in body
    assert "Still rendering, checking again in 5 s." in body
    assert 'data-poll-mode="page-content"' in body
    assert "visualization_polling.js" in body
    assert "data-refresh-region-selector=" in body


def test_time_series_plot_error_stops_polling() -> None:
    """A permanently failed plot must not reload or keep polling forever."""
    usecases = _FakeUseCases(
        result=JobVisualizationResult(
            plot_type="Line",
            plot_html=None,
            waiting_message="Plot rendering exploded.",
            plot_status="error",
        )
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=single-time-series&x=A&y=outcome&stat=mean&plot_type=Line"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<meta http-equiv="refresh" content="5">' not in body
    assert "Plot rendering exploded." in body
    assert 'data-poll-mode="page-content"' not in body
    assert "visualization_polling.js" not in body


def test_batch_visualization_page_polls_in_place() -> None:
    """The Batch config page (job_visualize.html) polls the status endpoint instead of reloading."""
    usecases = _FakeResultsStatusUseCases(results_status="processing")
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/batch"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<meta http-equiv="refresh" content="5">' not in body
    assert 'data-poll-mode="page-content"' in body
    assert 'data-state-url="/jobs/job-1/visualization/status"' in body
    assert "visualization_polling.js" in body


def test_parser_visualization_page_polls_in_place() -> None:
    """The Parser config page (shared single-time-series template) polls instead of reloading."""
    usecases = _FakeResultsStatusUseCases(
        results_status="processing",
        output_params=[("outcome", "float_ts")],
    )
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/parser"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<meta http-equiv="refresh" content="5">' not in body
    assert 'data-poll-mode="page-content"' in body
    assert 'data-state-url="/jobs/job-1/visualization/status"' in body
    assert "visualization_polling.js" in body


def test_parser_plot_polls_in_place_while_pending() -> None:
    """Parser mode renders the shared non-Monte-Carlo plot waiting state."""
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=parser&series_0_x=A&series_0_y=outcome&series_0_stat=mean"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert isinstance(usecases.messages[-1], VisualizeDisasterStages)
    assert '<meta http-equiv="refresh" content="5">' not in body
    assert "Still rendering, checking again in 5 s." in body
    assert 'data-poll-mode="page-content"' in body
    assert "visualization_polling.js" in body
    assert 'class="mcf-plot-target"' not in body


def test_batch_plot_polls_in_place_while_pending() -> None:
    """The Batch form omits `mode`, falling back to a plain VisualizeJob rendered
    through the shared non-Monte-Carlo waiting state."""
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&series_0_x=time&series_0_y=outcome&series_0_stat=mean"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    message = usecases.messages[-1]
    assert isinstance(message, VisualizeJob)
    assert len(message.series) == 1
    assert '<meta http-equiv="refresh" content="5">' not in body
    assert "Still rendering, checking again in 5 s." in body
    assert 'data-poll-mode="page-content"' in body
    assert "visualization_polling.js" in body
    assert 'class="mcf-plot-target"' not in body


def test_visualization_status_route_returns_results_status() -> None:
    usecases = _FakeResultsStatusUseCases(results_status="processing")
    with _installed(usecases):
        response = app.test_client().get("/jobs/job-1/visualization/status")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "results_status": "processing",
        "results_error": None,
    }