import pandas as pd
import plotly.graph_objects as go

from services.visualization.plots.scatter import Scatter


def _scatter_csv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "repetition": [5.0, 6.0, 7.0],
            "run_5": [0.1, 0.6, 0.2],
            "run_7": [0.3, 0.9, float("nan")],
        }
    )


def _traces(traits) -> dict:
    fig = go.Figure()
    Scatter().fill_figure(_scatter_csv(), fig, traits)
    return {trace.name: trace for trace in fig.data}


def test_scatter_uses_default_hover_and_markers_without_traits() -> None:
    traces = _traces(None)
    assert list(traces) == ["run_5", "run_7"]
    for trace in traces.values():
        assert trace.mode == "markers"
        assert trace.hovertemplate.endswith("<extra></extra>")
    assert traces["run_5"].hovertemplate == (
        "<b>run_5</b>: %{y:.2f}<br><b>repetition</b>: %{x:.2f}<extra></extra>"
    )
    assert traces["run_5"].marker.color is None


def test_scatter_applies_per_series_hover_and_marker_style() -> None:
    traits = [
        {
            "type": "series",
            "y_name": "run_5",
            "hovertemplate": "<b>run_5</b><br>repetition: %{x}<extra></extra>",
            "color": "#ff0000",
            "size": 9,
        }
    ]
    traces = _traces(traits)

    assert traces["run_5"].hovertemplate == (
        "<b>run_5</b><br>repetition: %{x}<extra></extra>"
    )
    assert traces["run_5"].marker.color == "#ff0000"
    assert traces["run_5"].marker.size == 9
    assert traces["run_7"].marker.color is None
    assert traces["run_7"].hovertemplate == (
        "<b>run_7</b>: %{y:.2f}<br><b>repetition</b>: %{x:.2f}<extra></extra>"
    )


def test_scatter_keeps_line_style_keys_out_of_marker() -> None:
    traits = [
        {
            "type": "series",
            "y_name": "run_5",
            "hovertemplate": "custom",
            "dash": "dash",
            "width": 3,
        }
    ]
    trace = _traces(traits)["run_5"]

    assert trace.hovertemplate == "custom"
    assert trace.line.dash is None
    assert trace.line.width is None


def test_scatter_reads_legacy_scatter_typed_series_traits() -> None:
    traits = [{"type": "scatter", "y_name": "run_5", "hovertemplate": "legacy"}]
    assert _traces(traits)["run_5"].hovertemplate == "legacy"


def test_scatter_series_traits_win_over_legacy_scatter_traits() -> None:
    traits = [
        {"type": "scatter", "y_name": "run_5", "hovertemplate": "legacy"},
        {"type": "series", "y_name": "run_5", "hovertemplate": "series"},
    ]
    assert _traces(traits)["run_5"].hovertemplate == "series"


def test_scatter_renames_traces_from_series_traits() -> None:
    traits = [
        {"type": "series", "y_name": "run_5", "name": "behavioural"},
        {"type": "series", "y_name": "run_7", "name": "non-behavioural"},
    ]
    traces = _traces(traits)

    assert list(traces) == ["behavioural", "non-behavioural"]


def test_scatter_honours_use_webgl_false() -> None:
    assert _traces([{"type": "scatter", "use_webgl": False}])["run_5"].type == "scatter"
    assert _traces(None)["run_5"].type == "scattergl"


def test_scatter_title_can_be_suppressed_by_layout_trait() -> None:
    html = Scatter().generate(_scatter_csv(), [{"type": "layout", "title": ""}])

    assert "Relationship between outputs and repetition" not in html
