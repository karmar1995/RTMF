from __future__ import annotations

from werkzeug.datastructures import MultiDict

from services.front.main import app
from services.front.endpoints.visualization.details.visualize_job_impl import (
    _expand_range_series,
)
from use_case_contracts.dtos import ParameterValues
from use_case_contracts.messages import VisualizeJob
from conftest import (
    _FakeResultsStatusUseCases,
    _FakeUseCases,
    _installed,
)


def test_multiple_time_series_page_renders_with_range_controls() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-time-series"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Multiple Time Series Visualization" in body
    assert "Range" in body
    assert 'name="constant_K"' in body
    assert "Min" in body
    assert "Max" in body
    assert "Step" in body


def test_multiple_time_series_page_renders_range_inputs() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-time-series"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Range" in body
    assert 'data-role="range-min"' in body
    assert 'data-role="range-max"' in body
    assert 'data-role="range-step"' in body
    assert 'name="range_min_K"' not in body
    assert 'name="range_max_K"' not in body
    assert 'name="range_step_K"' not in body


def test_multiple_time_series_step_input_is_readonly() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-time-series"
        )

    body = response.get_data(as_text=True)
    assert 'data-role="range-step"' in body
    assert 'type="text"' in body
    assert "readonly" in body


def test_multiple_time_series_no_range_checkbox_for_single_value() -> None:
    usecases = _FakeUseCases(constants=ParameterValues(name="K", value=[7]))
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-time-series"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-role="range-toggle"' not in body


def test_multiple_time_series_page_renders_repetition_range_controls() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-time-series"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-role="repetition-range-toggle"' in body
    assert 'data-role="repetition-range-min"' in body
    assert 'data-role="repetition-range-max"' in body
    assert 'data-role="repetition-range-step"' in body
    assert 'name="range_min_repetition"' not in body
    assert 'name="range_max_repetition"' not in body
    assert 'name="range_step_repetition"' not in body


def test_multiple_time_series_restores_range_bounds_from_url() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-time-series"
            "?constant_K=1&range_K=1&range_K=2&range_K=3"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<option value="1" selected>' in body
    assert '<option value="3" selected>' in body
    assert '<option value="2" selected>' not in body


def test_multiple_time_series_plot_expands_ranges_into_series() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=multiple-time-series&x=time&y=outcome&stat=none"
            "&plot_type=Line&repetition=0&constant_K=2"
            "&range_K=1&range_K=2&range_K=3"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200

    message = usecases.messages[-1]
    assert isinstance(message, VisualizeJob)
    assert message.plot_type == "Line"
    assert [series.y for series in message.series] == ["outcome"] * 3
    assert [series.constants["constant_K"] for series in message.series] == ["1", "2", "3"]
    for series in message.series:
        assert series.x == "time"
        assert series.statistic == "none"
        assert series.constants["constant_repetition"] == "0"


def test_multiple_time_series_plot_expands_repetition_ranges_into_series() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=multiple-time-series&x=time&y=outcome&stat=none"
            "&plot_type=Line&constant_K=2"
            "&range_repetition=0&range_repetition=1&range_repetition=2"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200

    message = usecases.messages[-1]
    assert isinstance(message, VisualizeJob)
    assert message.plot_type == "Line"
    assert len(message.series) == 3
    assert [series.constants["constant_repetition"] for series in message.series] == ["0", "1", "2"]
    for series in message.series:
        assert series.x == "time"
        assert series.y == "outcome"
        assert series.statistic == "none"
        assert series.constants["constant_K"] == "2"


def test_multiple_time_series_plot_without_ranges_falls_back_to_single_series() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/plot"
            "?plot=1&mode=multiple-time-series&x=time&y=outcome&stat=none"
            "&plot_type=Line&repetition=0&constant_K=2"
        )

    assert response.status_code == 200
    message = usecases.messages[-1]
    assert isinstance(message, VisualizeJob)
    assert len(message.series) == 1
    assert message.series[0].constants["constant_K"] == "2"


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


def test_multiple_time_series_error_status_renders_error_card_and_no_refresh() -> None:
    usecases = _FakeResultsStatusUseCases(results_status="error", results_error="boom")
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-time-series"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Failed to load job results: boom" in body
    assert (
        'action="/simulation-groups/job-1/visualize/retry-results"' in body
    )
    assert "Retry loading job results" in body
    assert 'http-equiv="refresh"' not in body


def test_multiple_time_series_processing_status_polls_in_place() -> None:
    usecases = _FakeResultsStatusUseCases(results_status="processing")
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation-groups/job-1/visualize/multiple-time-series"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'http-equiv="refresh"' not in body
    assert "Failed to load job results" not in body
    assert 'data-poll-mode="page-content"' in body
    assert "visualization_polling.js" in body
    assert 'data-state-url="/jobs/job-1/visualization/status"' in body
    assert 'data-terminal-statuses="ok,error"' in body


def _base_series(constants: dict | None = None):
    from use_case_contracts.messages import VisualizationSeries

    return VisualizationSeries(
        x="time",
        y="outcome",
        statistic="none",
        constants=constants or {"constant_repetition": "0", "constant_K": "2"},
    )


def test_expand_range_series_returns_base_when_no_ranges() -> None:
    base = _base_series()
    result = _expand_range_series(base, MultiDict({"x": "time"}))
    assert len(result) == 1
    assert result[0] is base


def test_expand_range_series_returns_empty_when_no_base() -> None:
    assert _expand_range_series(None, MultiDict()) == []


def test_expand_range_series_combines_all_swept_params() -> None:
    base = _base_series({"constant_repetition": "0", "constant_K": "2", "constant_A": "5"})
    args = MultiDict([
        ("range_K", "1"),
        ("range_K", "2"),
        ("range_A", "x"),
        ("range_A", "y"),
    ])

    result = _expand_range_series(base, args)

    assert len(result) == 4
    expected = {
        (("constant_A", "x"), ("constant_K", "1"), ("constant_repetition", "0")),
        (("constant_A", "x"), ("constant_K", "2"), ("constant_repetition", "0")),
        (("constant_A", "y"), ("constant_K", "1"), ("constant_repetition", "0")),
        (("constant_A", "y"), ("constant_K", "2"), ("constant_repetition", "0")),
    }
    actual = {tuple(sorted(s.constants.items())) for s in result}
    assert actual == expected


def test_expand_range_series_deduplicates_identical_constants() -> None:
    base = _base_series({"constant_repetition": "0", "constant_K": "2"})
    args = MultiDict([("range_K", "2"), ("range_K", "2")])

    result = _expand_range_series(base, args)

    assert len(result) == 1
    assert result[0].constants["constant_K"] == "2"


def test_expand_range_series_preserves_base_when_no_matching_range_values() -> None:
    base = _base_series()
    args = MultiDict([("range_K", "100")])

    result = _expand_range_series(base, args)

    assert len(result) == 1
    assert result[0].constants["constant_K"] == "100"


def test_expand_range_series_preserves_original_stat_and_x() -> None:
    base = _base_series()
    args = MultiDict([("range_K", "1"), ("range_K", "2")])

    result = _expand_range_series(base, args)

    for series in result:
        assert series.x == "time"
        assert series.y == "outcome"
        assert series.statistic == "none"


def test_expand_range_series_expands_repetition_range() -> None:
    base = _base_series({"constant_K": "2"})
    args = MultiDict([("range_repetition", "0"), ("range_repetition", "1"), ("range_repetition", "2")])

    result = _expand_range_series(base, args)

    assert len(result) == 3
    assert [series.constants["constant_repetition"] for series in result] == ["0", "1", "2"]
    for series in result:
        assert series.constants["constant_K"] == "2"


def test_expand_range_series_combines_repetition_with_other_params() -> None:
    base = _base_series()
    args = MultiDict([
        ("range_repetition", "0"),
        ("range_repetition", "1"),
        ("range_K", "1"),
        ("range_K", "2"),
    ])

    result = _expand_range_series(base, args)

    assert len(result) == 4
    repetitions = {series.constants["constant_repetition"] for series in result}
    ks = {series.constants["constant_K"] for series in result}
    assert repetitions == {"0", "1"}
    assert ks == {"1", "2"}