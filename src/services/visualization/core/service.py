from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from services.visualization.core.executor import VisualizationExecutor
from services.visualization.core.errors import DecodeError, UnknownPlotType
from services.visualization.core.zipper import Zipper
from services.visualization.enums.plot_type import Plot2DType
from services.visualization.plots.plot_generator import PlotGenerator


class VisualizationService:
    def __init__(self, executor: VisualizationExecutor) -> None:
        self._executor = executor
        self._zipper = Zipper()
        self._plot_generator = PlotGenerator()

    def render_plot(
        self, data: bytes, plot_type: str, traits: list[dict] | None = None
    ) -> UUID:
        data_in_ram: bytes = self._zipper.unzip(content=data)

        to_hash = str(plot_type) + str(data_in_ram) + str(json.dumps(traits or {}, sort_keys=True))
        hash_value = hashlib.sha256(to_hash.encode()).hexdigest()

        try:
            plot = Plot2DType(plot_type)
        except ValueError as exc:
            raise UnknownPlotType(f"Unsupported plot type: {plot_type!r}") from exc
        self._plot_generator.set_plot(plot)

        return self._executor.submit_future(
            hash_value, self._plot_generator.generate, data_in_ram, traits
        )

    def get_plot_html(self, plot_id: UUID) -> str | None:
        return self._executor.get_result(plot_id)

    def get_plot_status(self, plot_id: UUID) -> str:
        result = self._executor.get_future_status(plot_id)
        return result["status"].value

    def supported_plot_types(self) -> list[dict[str, str]]:
        return self._plot_generator.get_plots_info
