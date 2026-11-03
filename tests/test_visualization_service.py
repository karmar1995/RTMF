from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from services.visualization.core.errors import UnknownPlotType
from services.visualization.core.executor import VisualizationExecutor
from services.visualization.core.service import VisualizationService
from services.visualization.rest_api.app import create_app


def _zip_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("data.csv", text)
    return buffer.getvalue()


class _UnusedExecutor:
    def submit_future(self, *args, **kwargs):
        raise AssertionError("executor must not be called for an unknown plot type")


def test_render_plot_rejects_unknown_plot_type() -> None:
    service = VisualizationService(executor=_UnusedExecutor())

    with pytest.raises(UnknownPlotType):
        service.render_plot(
            data=_zip_bytes("x;y\n1;2\n"),
            plot_type="Box",
            traits=None,
        )


def test_generate_plot2d_rejects_unknown_plot_type_with_400() -> None:
    client = TestClient(create_app(VisualizationService(VisualizationExecutor())))

    response = client.post(
        "/api/v1/generate-plot2D",
        data={"type": "Box"},
        files={"data": ("series.zip", _zip_bytes("x;y\n1;2\n"), "application/zip")},
    )

    assert response.status_code == 400
    assert "Unsupported plot type" in response.json()["detail"]
