import pandas as pd
import plotly.graph_objects as go

from services.visualization.plots.line import Line


def _line_csv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": [0.0, 1.0, 2.0],
            "run_5": [0.1, 0.6, 0.2],
            "run_7": [0.3, 0.9, float("nan")],
        }
    )


def _traces(traits) -> dict:
    fig = go.Figure()
    Line().fill_figure(_line_csv(), fig, traits)
    return {trace.name: trace for trace in fig.data}


def test_line_plot_uses_default_hover_and_mode_without_traits() -> None:
    traces = _traces(None)
    assert list(traces) == ["run_5", "run_7"]
    for trace in traces.values():
        assert trace.mode == "lines"
        assert trace.hovertemplate == "<b>%{y:.2f}</b><extra></extra>"
        assert trace.line.color is None
        assert trace.line.dash is None
        assert trace.line.width is None


def test_line_plot_applies_per_series_hover_template_and_mode() -> None:
    traits = [
        {
            "type": "series",
            "y_name": "run_5",
            "hovertemplate": "<b>run_5</b><br>time: %{x}<extra></extra>",
            "mode": "markers",
        },
        {"type": "series", "y_name": "run_7", "mode": "markers"},
    ]
    traces = _traces(traits)

    assert traces["run_5"].hovertemplate == "<b>run_5</b><br>time: %{x}<extra></extra>"
    assert traces["run_5"].mode == "markers"
    assert traces["run_7"].mode == "markers"
    assert traces["run_7"].hovertemplate == "<b>%{y:.2f}</b><extra></extra>"


def test_line_plot_keeps_line_style_keys_out_of_hover_options() -> None:
    traits = [
        {
            "type": "series",
            "y_name": "run_5",
            "color": "#ff0000",
            "dash": "dash",
            "width": 3,
            "hovertemplate": "custom",
            "mode": "lines+markers",
        }
    ]
    trace = _traces(traits)["run_5"]

    assert trace.line.color == "#ff0000"
    assert trace.line.dash == "dash"
    assert trace.line.width == 3
    assert trace.hovertemplate == "custom"
    assert trace.mode == "lines+markers"


def test_line_plot_drops_scatter_only_style_keys() -> None:
    traits = [{"type": "series", "y_name": "run_5", "symbol": "square", "size": 8}]
    trace = _traces(traits)["run_5"]

    assert trace.line.to_plotly_json() == {}


def test_line_plot_renames_traces_from_series_traits() -> None:
    traits = [{"type": "series", "y_name": "run_5", "name": "behavioural"}]
    traces = _traces(traits)

    assert list(traces) == ["behavioural", "run_7"]


def test_line_plot_honours_use_webgl_false() -> None:
    traits = [{"type": "series", "y_name": "run_5", "use_webgl": False}]

    assert _traces(traits)["run_5"].type == "scatter"
    assert _traces(None)["run_5"].type == "scattergl"
