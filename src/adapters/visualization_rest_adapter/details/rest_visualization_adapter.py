from __future__ import annotations

import io
import json
import socket
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from use_case_contracts.ports import VisualizationPort
from use_case_contracts.dtos import (
    PlotSpec,
    PlotArea,
    PlotLine,
    PlotAnnotation,
    PlotDiagonalLine,
)
from use_case_contracts.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from adapters.visualization_rest_adapter.config import VisualizationConfig

_PLOT_2D_PATH = "/api/v1/generate-plot2D"
_SUPPORTED_PLOT_TYPES = ["Line", "Boxplot", "Scatter"]


def unzip_string(data: bytes) -> str:
    """Return UTF-8 text from a zip archive containing exactly one regular file."""

    with zipfile.ZipFile(io.BytesIO(data), mode="r") as zf:
        names = [name for name in zf.namelist() if not name.endswith("/")]
        if not names:
            raise ValueError("Zip archive has no files")
        if len(names) > 1:
            raise ValueError("Zip archive has multiple files")
        return zf.read(names[0]).decode("utf-8")


class RestVisualizationAdapter(VisualizationPort):
    def __init__(
        self, config: VisualizationConfig, http_client: Any | None = None
    ) -> None:
        self._config = config
        self._base_url = _normalize_base_url(config.base_url)
        self._http = http_client

    def supported_plot_types(self) -> list[str]:
        return list(_SUPPORTED_PLOT_TYPES)

    def render_plot(self, zip_csv_bytes: bytes, plot_spec: PlotSpec) -> str:
        traits = json.dumps(self._plot_spec_to_traits(plot_spec))
        body, content_type = _encode_multipart(
            fields={
                "type": plot_spec.plot_type,
                "traits": traits,
            },
            files=[
                ("data", "series.zip", "application/zip", zip_csv_bytes),
            ],
        )
        payload = self._request_json(
            method="POST",
            path=_PLOT_2D_PATH,
            body=body,
            headers={"Content-Type": content_type},
        )
        return _parse_plot_id(payload)

    def get_plot_html(self, plot_id: str) -> str:
        response = self._request_bytes(
            method="GET",
            path=f"/api/v1/get-plot-html/{urllib.parse.quote(plot_id, safe='')}",
            accept="text/html",
        )
        return _decode_utf8_text(
            response, error_label=f"Visualization service failure - malformed HTML"
        )

    def get_plot_status(self, plot_id: str) -> str:
        payload = self._request_json(
            method="GET",
            path=f"/api/v1/get-plot-status/{urllib.parse.quote(plot_id, safe='')}",
        )
        return _parse_status(payload)

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = self._request_bytes(
            method=method,
            path=path,
            body=body,
            headers=headers,
            accept="application/json",
        )
        if not response:
            return None
        try:
            return json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExternalServiceError(
                f"Visualization service returned malformed JSON for {method} {self._build_url(path)}"
            ) from exc

    def _request_bytes(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        accept: str,
    ) -> bytes:
        url = self._build_url(path)
        request_headers = {"Accept": accept}
        if self._config.auth_token:
            request_headers["Authorization"] = f"Bearer {self._config.auth_token}"
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(
            url, data=body, headers=request_headers, method=method
        )
        timeout = self._config.timeout_seconds or 10
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            response_body = exc.read() if exc.fp else b""
            message = _format_http_error(
                method=method, url=url, status=exc.code, body=response_body
            )
            if exc.code in (401, 403):
                raise AuthenticationError(message) from exc
            if exc.code == 404:
                raise NotFoundError(message) from exc
            if exc.code == 400:
                raise ValidationError(message) from exc
            raise ExternalServiceError(message) from exc
        except (urllib.error.URLError, socket.timeout) as exc:
            raise ExternalServiceError(
                f"Visualization service request failed ({method} {url}): {exc}"
            ) from exc

    def _build_url(self, path: str) -> str:
        return urllib.parse.urljoin(f"{self._base_url}/", path.lstrip("/"))

    def _plot_spec_to_traits(self, plotSpec: PlotSpec) -> list[dict[str, Any]]:
        traits: list[dict[str, Any]] = []
        traits.extend(self._plot_vertical_lines_to_traits(plotSpec.vertical_lines))
        traits.extend(self._plot_areas_to_traits(plotSpec.areas))
        traits.extend(self._plot_annotations_to_traits(plotSpec.annotations))
        traits.extend(self._plot_diagonal_lines_to_traits(plotSpec.diagonal_lines))
        traits.extend(self._plot_layout_to_traits(plotSpec))
        traits.extend(self._plot_series_to_traits(plotSpec))
        return traits

    def _plot_series_to_traits(self, plotSpec: PlotSpec) -> list[dict[str, Any]]:
        templates = plotSpec.series_hover_templates or {}
        styles = plotSpec.series_styles or {}
        names = list(dict.fromkeys([*templates.keys(), *styles.keys()]))
        traits: list[dict[str, Any]] = []
        for name in names:
            trait: dict[str, Any] = {"type": "series", "y_name": name}
            if name in templates:
                trait["hovertemplate"] = templates[name]
            trait.update(styles.get(name, {}))
            traits.append(trait)
        return traits

    def _plot_layout_to_traits(self, plotSpec: PlotSpec) -> list[dict[str, Any]]:
        if plotSpec.title is None and plotSpec.xaxis_title is None and plotSpec.yaxis_title is None:
            return []
        return [{
            "type": "layout",
            "title": plotSpec.title,
            "xaxis_title": plotSpec.xaxis_title,
            "yaxis_title": plotSpec.yaxis_title,
        }]

    def _plot_vertical_lines_to_traits(
        self, vertical_lines: list[PlotLine]
    ) -> list[dict[str, Any]]:
        traits: list[dict[str, Any]] = []
        for line in vertical_lines:
            traits.append(
                {
                    "type": "line",
                    "orientation": "vertical",
                    "x": line.point,
                    "color": line.color,
                    "linestyle": "dashed",
                    "linewidth": 2,
                }
            )
        return traits

    def _plot_areas_to_traits(self, areas: list[PlotArea]) -> list[dict[str, Any]]:
        traits: list[dict[str, Any]] = []
        for area in areas:
            traits.append(
                {
                    "type": "background",
                    "start": area.begin,
                    "end": area.end,
                    "color": area.color,
                    "alpha": 0.2,
                }
            )
        return traits

    def _plot_annotations_to_traits(
        self, annotations: list[PlotAnnotation]
    ) -> list[dict[str, Any]]:
        traits: list[dict[str, Any]] = []
        for annotation in annotations:
            traits.append(
                {
                    "type": "annotation",
                    "x": annotation.point,
                    "text": annotation.text,
                    "color": annotation.color,
                    "fontsize": 18,
                }
            )
        return traits

    def _plot_diagonal_lines_to_traits(
        self, diagonal_lines: list[PlotDiagonalLine]
    ) -> list[dict[str, Any]]:
        traits: list[dict[str, Any]] = []
        for line in diagonal_lines:
            traits.append(
                {
                    "type": "line",
                    "orientation": "diagonal",
                    "p_start": list(line.p_start),
                    "p_end": list(line.p_end),
                    "color": line.color,
                    "dash": line.dash,
                }
            )
        return traits


def _normalize_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        raise ValueError("Visualization base URL must not be empty")
    return normalized


def _encode_multipart(
    *,
    fields: dict[str, str],
    files: list[tuple[str, str, str, bytes]],
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    lines: list[bytes] = []
    for name, value in fields.items():
        if value is None:
            continue
        lines.append(f"--{boundary}".encode("utf-8"))
        lines.append(f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"))
        lines.append(b"")
        lines.append(str(value).encode("utf-8"))
    for field, filename, content_type, data in files:
        lines.append(f"--{boundary}".encode("utf-8"))
        lines.append(
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"'.encode(
                "utf-8"
            )
        )
        lines.append(f"Content-Type: {content_type}".encode("utf-8"))
        lines.append(b"")
        lines.append(data)
    lines.append(f"--{boundary}--".encode("utf-8"))
    lines.append(b"")
    body = b"\r\n".join(lines)
    return body, f"multipart/form-data; boundary={boundary}"


def _parse_plot_id(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("plot_id", "plotId", "id"):
            value = payload.get(key)
            if value:
                return str(value)
    raise ExternalServiceError(
        "Visualization service returned invalid plot creation payload"
    )


def _parse_status(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        value = payload.get("status")
        if value is None:
            raise ExternalServiceError(
                "Visualization service returned status payload without status field"
            )
        return str(value)
    raise ExternalServiceError("Visualization service returned invalid status payload")


def _decode_utf8_text(data: bytes, *, error_label: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExternalServiceError(error_label) from exc


def _format_http_error(*, method: str, url: str, status: int, body: bytes) -> str:
    snippet = body.decode("utf-8", errors="replace").strip()
    if len(snippet) > 200:
        snippet = f"{snippet[:200]}..."
    if snippet:
        return f"Visualization service request failed ({method} {url}, status={status}, body={snippet})"
    return f"Visualization service request failed ({method} {url}, status={status})"
