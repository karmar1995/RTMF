import pandas as pd
import plotly.graph_objects as go

from services.visualization.plots.ecdf import Ecdf


def _ecdf_csv() -> pd.DataFrame:
    rows = []
    for parameter in ("A", "B"):
        for x, cdf in ((0.1, 0.2), (0.2, 0.4), (0.3, 0.6), (0.4, 0.8), (0.5, 1.0)):
            rows.append([parameter, "behavioural", x, cdf, 0.9])
        for x, cdf in ((2.0, 0.25), (2.1, 0.5), (2.2, 0.75), (2.3, 1.0)):
            rows.append([parameter, "non_behavioural", x, cdf, 0.9])
    return pd.DataFrame(rows, columns=["parameter", "group", "x", "cdf", "d_statistic"])


def test_ecdf_plot_draws_separate_plot_per_parameter() -> None:
    html = Ecdf().generate(_ecdf_csv(), None)
    assert "Plotly" in html
    assert "Behavioural" in html
    assert "Non-behavioural" in html
    # Both parameter names appear as plot titles
    assert "A" in html
    assert "B" in html
    # One standalone plot div per parameter
    assert html.count("plotly-graph-div") == 2
    # plotly.js is loaded once per page, not embedded in the fragment
    assert html.count("window.PlotlyConfig") == 0


def test_ecdf_plot_includes_d_statistic() -> None:
    html = Ecdf().generate(_ecdf_csv(), None)
    assert "D-stat" in html
    assert "0.9000" in html


def test_ecdf_plot_handles_single_parameter() -> None:
    data = _ecdf_csv()[_ecdf_csv()["parameter"] == "A"]
    html = Ecdf().generate(data, None)
    assert "Behavioural" in html
    assert "Non-behavioural" in html
    assert html.count("plotly-graph-div") == 1


def test_ecdf_plot_handles_empty_data() -> None:
    data = pd.DataFrame()
    html = Ecdf().generate(data, None)
    figures = Ecdf().build_figures(pd.DataFrame(), None)
    assert len(figures) == 1
    assert isinstance(figures[0], go.Figure)
    assert "Plotly" in html


def test_ecdf_applies_shared_scheme_traits_to_every_subplot() -> None:
    traits = [
        {"type": "layout", "xaxis_title": "sample value"},
        {"type": "annotation", "text": "scheme-marker"},
    ]
    html = Ecdf().generate(_ecdf_csv(), traits)

    # Two parameters -> the shared scheme runs once per figure.
    assert html.count("plotly-graph-div") == 2
    assert html.count("sample value") == 2
    assert html.count("scheme-marker") == 2


def test_ecdf_description() -> None:
    assert "empirical cumulative distribution" in Ecdf().description().lower()
