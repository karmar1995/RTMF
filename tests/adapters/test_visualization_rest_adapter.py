from __future__ import annotations

from adapters.visualization_rest_adapter.config import VisualizationConfig
from adapters.visualization_rest_adapter.details.rest_visualization_adapter import (
    RestVisualizationAdapter,
)
from services.visualization.enums.plot_type import Plot2DType


def _adapter() -> RestVisualizationAdapter:
    return RestVisualizationAdapter(
        VisualizationConfig(base_url="http://visualization")
    )


def test_supported_plot_types_are_valid_plot_2d_types() -> None:
    supported = _adapter().supported_plot_types()

    assert supported
    valid = {plot_type.value for plot_type in Plot2DType}
    assert set(supported) <= valid


def test_supported_plot_types_uses_canonical_boxplot_name() -> None:
    supported = _adapter().supported_plot_types()

    assert Plot2DType.BOXPLOT.value in supported
    assert "Box" not in supported
