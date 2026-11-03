from __future__ import annotations

from typing import Protocol
from uuid import UUID


class VisualizationServicePort(Protocol):
    def render_plot(self, data: bytes, plot_type: str, traits: list[dict] | None = None) -> UUID:
        ...

    def get_plot_html(self, plot_id: UUID) -> str | None:
        ...

    def get_plot_status(self, plot_id: UUID) -> str:
        ...

    def supported_plot_types(self) -> list[dict[str, str]]:
        ...
