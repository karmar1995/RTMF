import pandas as pd
import plotly.graph_objects as go
from plotly.colors import DEFAULT_PLOTLY_COLORS

from services.visualization.plots.uof_ringplot import UoF_Ringplot


def _sensitivity_csv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "output": ["outcome"] * 3,
            "S_exp": [0.6] * 3,
            "input": ["A", "B", "C"],
            "ST": [0.4, 0.35, 0.05],
            "Si": [0.3, 0.1, 0.05],
        }
    )


def _figure(traits) -> go.Figure:
    fig = go.Figure()
    UoF_Ringplot().fill_figure(_sensitivity_csv(), fig, traits)
    return fig


def _colors_by_name(fig) -> dict:
    return {trace.name: trace.marker.color for trace in fig.data}


def test_ringplot_reads_config_trait_and_filters_selected_output() -> None:
    fig = _figure(
        [
            {
                "type": "uof_ringplot",
                "output": "outcome",
                "mode": "det",
                "color_dic": {"A": "#abcdef"},
            }
        ]
    )

    names = [trace.name for trace in fig.data]
    assert names[0] == "Deterministic"
    assert "Stochastic" in names
    assert "A" in names
    assert "C" in names
    assert fig.layout.title.text == "Sensitivity structure for outcome (det)"

    colors = _colors_by_name(fig)
    assert colors["A"] == "#abcdef"
    assert colors["B"] == DEFAULT_PLOTLY_COLORS[1]
    assert colors["C"] == DEFAULT_PLOTLY_COLORS[2]


def test_ringplot_falls_back_to_stochastic_mode() -> None:
    fig = _figure([{"type": "uof_ringplot", "output": "outcome", "mode": "sto"}])

    assert [trace.name for trace in fig.data][0] == "Stochastic"
    assert fig.layout.title.text == "Sensitivity structure for outcome (sto)"
