import pandas as pd
import plotly.graph_objects as go
from dataclasses import fields

from use_case_contracts.dtos import PlotSpec
from adapters.visualization_rest_adapter.config import VisualizationConfig
from adapters.visualization_rest_adapter.details.rest_visualization_adapter import RestVisualizationAdapter
from services.visualization.plots.plot import Plot


def _make_adapter() -> RestVisualizationAdapter:
    return RestVisualizationAdapter(config=VisualizationConfig(base_url="http://fake"))


def test_layout_trait_emitted_when_titles_set() -> None:
    adapter = _make_adapter()
    spec = PlotSpec(plot_type="Line", vertical_lines=[], areas=[], annotations=[], diagonal_lines=[],
                    xaxis_title="time", yaxis_title="outcome")
    traits = adapter._plot_spec_to_traits(spec)
    layout = next(t for t in traits if t.get("type") == "layout")
    assert layout["xaxis_title"] == "time"
    assert layout["yaxis_title"] == "outcome"


def test_layout_trait_not_emitted_when_titles_none() -> None:
    adapter = _make_adapter()
    spec = PlotSpec(plot_type="Line", vertical_lines=[], areas=[], annotations=[], diagonal_lines=[])
    traits = adapter._plot_spec_to_traits(spec)
    assert all(t.get("type") != "layout" for t in traits)


def test_layout_trait_not_emitted_when_only_xaxis_set() -> None:
    adapter = _make_adapter()
    spec = PlotSpec(plot_type="Line", vertical_lines=[], areas=[], annotations=[], diagonal_lines=[],
                    xaxis_title="x")
    traits = adapter._plot_spec_to_traits(spec)
    layout = next(t for t in traits if t.get("type") == "layout")
    assert layout["xaxis_title"] == "x"
    assert layout["yaxis_title"] is None
    assert layout["title"] is None


def test_layout_trait_emitted_for_title() -> None:
    adapter = _make_adapter()
    spec = PlotSpec(plot_type="Scatter", vertical_lines=[], areas=[], annotations=[],
                    diagonal_lines=[], title="My title")
    layout = next(t for t in adapter._plot_spec_to_traits(spec) if t.get("type") == "layout")
    assert layout["title"] == "My title"


def test_layout_trait_emitted_for_empty_title() -> None:
    adapter = _make_adapter()
    spec = PlotSpec(plot_type="Scatter", vertical_lines=[], areas=[], annotations=[],
                    diagonal_lines=[], title="")
    layout = next(t for t in adapter._plot_spec_to_traits(spec) if t.get("type") == "layout")
    assert layout["title"] == ""


def test_layout_trait_not_emitted_when_only_empty_title() -> None:
    adapter = _make_adapter()
    spec = PlotSpec(plot_type="Line", vertical_lines=[], areas=[], annotations=[],
                    diagonal_lines=[], title="")
    layout = next(t for t in adapter._plot_spec_to_traits(spec) if t.get("type") == "layout")
    assert layout["title"] == ""
    assert layout["xaxis_title"] is None


def test_apply_layout_title_overrides_plot_default() -> None:
    class DummyPlot(Plot):
        def description(self) -> str:
            return ""
        def fill_figure(self, data, fig, traits):
            fig.update_layout(title="plot_default")

    html = DummyPlot().generate(
        pd.DataFrame({"x": [1], "y": [2]}), [{"type": "layout", "title": "trait_title"}]
    )
    assert "trait_title" in html
    assert "plot_default" not in html


def test_apply_layout_empty_title_suppresses_plot_default() -> None:
    class DummyPlot(Plot):
        def description(self) -> str:
            return ""
        def fill_figure(self, data, fig, traits):
            fig.update_layout(title="plot_default")

    html = DummyPlot().generate(
        pd.DataFrame({"x": [1], "y": [2]}), [{"type": "layout", "title": ""}]
    )
    assert "plot_default" not in html


def test_apply_layout_titles_overrides_axes() -> None:
    class DummyPlot(Plot):
        def description(self) -> str:
            return ""
        def fill_figure(self, data, fig, traits):
            fig.update_layout(xaxis_title="old_x", yaxis_title="old_y")
            fig.add_trace(go.Scatter(x=[1, 2], y=[3, 4]))

    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    traits = [{"type": "layout", "xaxis_title": "new_x", "yaxis_title": "new_y"}]
    html = DummyPlot().generate(df, traits)
    assert "new_x" in html
    assert "new_y" in html
    assert "old_x" not in html
    assert "old_y" not in html


def test_apply_layout_titles_noop_when_trait_absent() -> None:
    class DummyPlot(Plot):
        def description(self) -> str:
            return ""
        def fill_figure(self, data, fig, traits):
            fig.update_layout(xaxis_title="keep_x", yaxis_title="keep_y")

    df = pd.DataFrame({"x": [1], "y": [2]})
    html = DummyPlot().generate(df, [])
    assert "keep_x" in html
    assert "keep_y" in html


def test_plot_spec_backward_compatible() -> None:
    spec = PlotSpec(plot_type="Line", vertical_lines=[], areas=[], annotations=[], diagonal_lines=[])
    assert spec.xaxis_title is None
    assert spec.yaxis_title is None
    assert spec.title is None
    assert spec.series_hover_templates is None
    assert spec.series_styles is None


def test_series_traits_emitted_for_styles() -> None:
    adapter = _make_adapter()
    spec = PlotSpec(
        plot_type="Scatter",
        vertical_lines=[],
        areas=[],
        annotations=[],
        diagonal_lines=[],
        series_styles={
            "Behavioural": {"name": "Behavioural", "color": "#2563eb"},
            "Non-behavioural": {"name": "Non-behavioural", "color": "#dc2626"},
        },
    )
    traits = adapter._plot_spec_to_traits(spec)
    assert [t for t in traits if t.get("type") == "series"] == [
        {"type": "series", "y_name": "Behavioural", "name": "Behavioural", "color": "#2563eb"},
        {
            "type": "series",
            "y_name": "Non-behavioural",
            "name": "Non-behavioural",
            "color": "#dc2626",
        },
    ]


def test_series_traits_merge_hover_templates_and_styles() -> None:
    adapter = _make_adapter()
    spec = PlotSpec(
        plot_type="Scatter",
        vertical_lines=[],
        areas=[],
        annotations=[],
        diagonal_lines=[],
        series_hover_templates={"Behavioural": "<b>Behavioural</b><extra></extra>"},
        series_styles={"Behavioural": {"name": "Behavioural", "color": "#2563eb"}},
    )
    traits = adapter._plot_spec_to_traits(spec)
    assert [t for t in traits if t.get("type") == "series"] == [
        {
            "type": "series",
            "y_name": "Behavioural",
            "hovertemplate": "<b>Behavioural</b><extra></extra>",
            "name": "Behavioural",
            "color": "#2563eb",
        },
    ]


def test_series_traits_cover_style_only_series() -> None:
    adapter = _make_adapter()
    spec = PlotSpec(
        plot_type="Scatter",
        vertical_lines=[],
        areas=[],
        annotations=[],
        diagonal_lines=[],
        series_hover_templates={"run_5": "<b>run_5</b><extra></extra>"},
        series_styles={"Behavioural": {"color": "#2563eb"}},
    )
    traits = adapter._plot_spec_to_traits(spec)
    assert [t for t in traits if t.get("type") == "series"] == [
        {"type": "series", "y_name": "run_5", "hovertemplate": "<b>run_5</b><extra></extra>"},
        {"type": "series", "y_name": "Behavioural", "color": "#2563eb"},
    ]


def test_plot_spec_has_no_series_modes_field() -> None:
    field_names = {field.name for field in fields(PlotSpec)}
    assert "series_modes" not in field_names


def test_series_traits_emitted_for_hover_templates() -> None:
    adapter = _make_adapter()
    spec = PlotSpec(
        plot_type="Line",
        vertical_lines=[],
        areas=[],
        annotations=[],
        diagonal_lines=[],
        series_hover_templates={"run_5": "<b>run_5</b><extra></extra>"},
    )
    traits = adapter._plot_spec_to_traits(spec)
    assert [t for t in traits if t.get("type") == "series"] == [
        {"type": "series", "y_name": "run_5", "hovertemplate": "<b>run_5</b><extra></extra>"},
    ]


def test_no_series_traits_without_hover_config() -> None:
    adapter = _make_adapter()
    spec = PlotSpec(plot_type="Line", vertical_lines=[], areas=[], annotations=[], diagonal_lines=[])
    traits = adapter._plot_spec_to_traits(spec)
    assert all(t.get("type") != "series" for t in traits)
