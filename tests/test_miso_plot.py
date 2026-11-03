import pandas as pd
import plotly.graph_objects as go

from services.visualization.plots.miso import MISO


def _miso_csv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "A": [0.1, 0.4, 0.7],
            "B": [0.2, 0.5, 0.8],
        }
    )


def _traces(traits) -> dict:
    fig = go.Figure()
    MISO().fill_figure(_miso_csv(), fig, traits)
    return {trace.name: trace for trace in fig.data}


def test_miso_defaults_to_webgl_traces_with_line_mode() -> None:
    traces = _traces(None)

    assert list(traces) == ["A", "B"]
    assert traces["A"].mode == "lines"
    assert traces["A"].type == "scattergl"
    assert traces["A"].opacity == 0.7
    assert traces["B"].opacity == 1.0


def test_miso_reads_use_webgl_config_from_trait() -> None:
    traces = _traces([{"type": "miso", "use_webgl": False}])

    assert traces["A"].type == "scatter"
    assert traces["B"].type == "scatter"


def test_miso_applies_line_styles_and_renames_traces() -> None:
    traits = [
        {"type": "series", "y_name": "A", "name": "first", "color": "#ff0000"},
        {"type": "series", "y_name": "A", "dash": "dash"},
        {"type": "series", "y_name": "B", "width": 4},
    ]
    traces = _traces(traits)

    assert list(traces) == ["first", "B"]
    assert traces["first"].line.color == "#ff0000"
    assert traces["first"].line.dash == "dash"
    assert traces["B"].line.width == 4


def test_miso_ignores_scatter_only_style_keys() -> None:
    traits = [{"type": "series", "y_name": "A", "symbol": "square", "size": 8}]
    trace = _traces(traits)["A"]

    assert trace.line.to_plotly_json() == {}
