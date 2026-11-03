import pandas as pd
import plotly.graph_objects as go

from services.visualization.plots.bar import Bar
from services.visualization.plots.boxplot import Boxplot
from services.visualization.plots.plot import Plot
from services.visualization.plots.scatter import Scatter
from services.visualization.plots.tools.traits_parser import TraitsParser


DEFAULT_BAR_HOVER = "<b>%{x}</b><br>Value: %{y:.2f}<extra></extra>"
DEFAULT_BOX_HOVER = (
    "<b>%{fullData.name}</b><br>"
    "bin: %{x}<br>"
    "value: %{y:.2f}<extra></extra>"
)


class _DummyPlot(Plot):
    def description(self) -> str:
        return ""

    def fill_figure(self, data, fig, traits):
        pass


def _output_csv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "repetition": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "run_5": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "run_7": [2.0, 1.0, 4.0, 3.0, 6.0, 5.0],
        }
    )


def _traces_by_name(plot, traits) -> dict:
    fig = go.Figure()
    plot.fill_figure(_output_csv(), fig, traits)
    grouped: dict = {}
    for trace in fig.data:
        grouped.setdefault(trace.name, []).append(trace)
    return grouped


def _resolve(traits, style_traits):
    styles = _DummyPlot().series_styles(traits, "series")
    return _DummyPlot().resolve_series(
        styles, "run_5", style_traits, default_hovertemplate="fallback"
    )


def test_resolve_series_routes_trace_keys_to_the_trace() -> None:
    traits = [
        {
            "type": "series",
            "y_name": "run_5",
            "hovertemplate": "custom",
            "mode": "markers",
            "color": "#ff0000",
        }
    ]
    trace_options, style = _resolve(traits, TraitsParser.SCATTER_STYLE_TRAITS)

    assert trace_options == {"hovertemplate": "custom", "mode": "markers"}
    assert style == {"color": "#ff0000"}


def test_resolve_series_drops_keys_the_plot_does_not_accept() -> None:
    traits = [
        {
            "type": "series",
            "y_name": "run_5",
            "dash": "dash",
            "width": 4,
            "symbol": "square",
        }
    ]
    trace_options, style = _resolve(traits, TraitsParser.BAR_STYLE_TRAITS)

    assert style == {}
    assert trace_options == {"hovertemplate": "fallback"}


def test_resolve_series_applies_defaults_for_unset_columns() -> None:
    trace_options, style = _resolve([], TraitsParser.LINE_STYLE_TRAITS)

    assert trace_options == {"hovertemplate": "fallback"}
    assert style == {}


def test_resolve_series_omits_mode_when_not_given() -> None:
    traits = [{"type": "series", "y_name": "run_5", "hovertemplate": "custom"}]
    trace_options, _ = _resolve(traits, TraitsParser.LINE_STYLE_TRAITS)

    assert "mode" not in trace_options


def test_resolve_series_merges_repeated_traits_for_the_same_column() -> None:
    traits = [
        {"type": "series", "y_name": "run_5", "hovertemplate": "first", "color": "#111"},
        {"type": "series", "y_name": "run_5", "color": "#222"},
    ]
    trace_options, style = _resolve(traits, TraitsParser.SCATTER_STYLE_TRAITS)

    assert trace_options == {"hovertemplate": "first"}
    assert style == {"color": "#222"}


def test_resolve_series_merges_multiple_trait_types() -> None:
    traits = [
        {"type": "line", "y_name": "run_5", "width": 3},
        {"type": "series", "y_name": "run_5", "hovertemplate": "custom"},
    ]
    styles = _DummyPlot().series_styles(traits, "line", "series")
    trace_options, style = _DummyPlot().resolve_series(
        styles, "run_5", TraitsParser.LINE_STYLE_TRAITS, default_hovertemplate=None
    )

    assert trace_options == {"hovertemplate": "custom"}
    assert style == {"width": 3}


def test_resolve_series_nests_boxplot_line_color() -> None:
    traits = [{"type": "series", "y_name": "run_5", "line_color": "#ff00ff"}]
    trace_options, style = _resolve(traits, TraitsParser.BOXPLOT_STYLE_TRAITS)

    assert trace_options == {"hovertemplate": "fallback"}
    assert style == {"line": {"color": "#ff00ff"}}


def test_bar_uses_default_hover_without_traits() -> None:
    traces = _traces_by_name(Bar(), None)
    assert list(traces) == ["run_5", "run_7"]
    for trace in traces["run_5"]:
        assert trace.hovertemplate == DEFAULT_BAR_HOVER
        assert trace.marker.color is None


def test_bar_applies_per_series_hover_and_marker_style() -> None:
    traits = [
        {
            "type": "series",
            "y_name": "run_5",
            "hovertemplate": "custom",
            "color": "#00ff00",
        }
    ]
    traces = _traces_by_name(Bar(), traits)

    for trace in traces["run_5"]:
        assert trace.hovertemplate == "custom"
        assert trace.marker.color == "#00ff00"
    for trace in traces["run_7"]:
        assert trace.hovertemplate == DEFAULT_BAR_HOVER
        assert trace.marker.color is None


def test_bar_applies_configured_aggregation() -> None:
    traces = _traces_by_name(Bar(), [{"type": "bar", "agg_type": "sum", "n_bins": 2}])

    assert list(traces) == ["run_5", "run_7"]
    run_5 = traces["run_5"]
    assert len(run_5) == 1
    assert list(run_5[0].y) == [6.0, 15.0]
    assert list(traces["run_7"][0].y) == [7.0, 14.0]
    assert run_5[0].name == "run_5"


def test_bar_ignores_series_mode_and_renames_traces() -> None:
    traits = [
        {"type": "series", "y_name": "run_5", "mode": "markers", "name": "behavioural"},
        {"type": "series", "y_name": "run_7", "name": "non-behavioural"},
    ]
    traces = _traces_by_name(Bar(), traits)

    assert list(traces) == ["behavioural", "non-behavioural"]


def test_boxplot_ignores_series_mode_and_renames_traces() -> None:
    traits = [
        {"type": "series", "y_name": "run_5", "mode": "markers", "name": "behavioural"},
    ]
    traces = _traces_by_name(Boxplot(), traits)

    assert list(traces) == ["behavioural", "run_7"]


def test_boxplot_applies_series_line_color() -> None:
    traits = [{"type": "series", "y_name": "run_5", "line_color": "#123456"}]
    traces = _traces_by_name(Boxplot(), traits)

    for trace in traces["run_5"]:
        assert trace.marker.line.color == "#123456"
    for trace in traces["run_7"]:
        assert trace.marker.line.color is None


def test_boxplot_uses_default_hover_without_traits() -> None:
    traces = _traces_by_name(Boxplot(), None)
    assert list(traces) == ["run_5", "run_7"]
    for trace in traces["run_5"] + traces["run_7"]:
        assert trace.hovertemplate == DEFAULT_BOX_HOVER
        assert trace.marker.color is None


def test_boxplot_applies_per_series_hover_and_marker_style() -> None:
    traits = [
        {
            "type": "series",
            "y_name": "run_5",
            "hovertemplate": "custom",
            "color": "#abcdef",
        }
    ]
    traces = _traces_by_name(Boxplot(), traits)

    assert len(traces["run_5"]) == len(traces["run_7"])
    for trace in traces["run_5"]:
        assert trace.hovertemplate == "custom"
        assert trace.marker.color == "#abcdef"
    for trace in traces["run_7"]:
        assert trace.hovertemplate == DEFAULT_BOX_HOVER
        assert trace.marker.color is None


def test_boxplot_config_colors_still_apply_without_series_traits() -> None:
    traits = [{"type": "boxplot", "colors": ["#111111", "#222222"]}]
    traces = _traces_by_name(Boxplot(), traits)

    for trace in traces["run_5"]:
        assert trace.marker.color == "#111111"
    for trace in traces["run_7"]:
        assert trace.marker.color == "#222222"


def test_boxplot_per_series_color_overrides_config_colors() -> None:
    traits = [
        {"type": "boxplot", "colors": ["#111111", "#222222"]},
        {"type": "series", "y_name": "run_5", "color": "#abcdef"},
    ]
    traces = _traces_by_name(Boxplot(), traits)

    for trace in traces["run_5"]:
        assert trace.marker.color == "#abcdef"
    for trace in traces["run_7"]:
        assert trace.marker.color == "#222222"


def test_scatter_applies_per_class_colour_and_legend_name() -> None:
    traits = [
        {"type": "series", "y_name": "run_5", "name": "Behavioural", "color": "#2563eb"},
        {
            "type": "series",
            "y_name": "run_7",
            "name": "Non-behavioural",
            "color": "#dc2626",
        },
    ]
    traces = _traces_by_name(Scatter(), traits)

    assert list(traces) == ["Behavioural", "Non-behavioural"]
    for trace in traces["Behavioural"]:
        assert trace.marker.color == "#2563eb"
    for trace in traces["Non-behavioural"]:
        assert trace.marker.color == "#dc2626"


def test_scatter_uses_column_names_without_traits() -> None:
    traces = _traces_by_name(Scatter(), None)

    assert list(traces) == ["run_5", "run_7"]
    for trace in traces["run_5"] + traces["run_7"]:
        assert trace.marker.color is None
