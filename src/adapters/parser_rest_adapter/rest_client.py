from __future__ import annotations

import csv
import json
import math
import socket
from dataclasses import dataclass
from io import BytesIO, StringIO
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from adapters.parser_rest_adapter.config import ParserConfig
from adapters.parser_rest_adapter.errors import (
    ParserRestConnectionError,
    ParserRestHttpError,
    ParserRestInvalidResponseError,
)

_RECOGNITION_PATH = "/api/v1/resiliency_stages_recognition"
_METRIC_FIELDS = {
    "recovery_time_in_steps",
    "shock_time_in_steps",
    "shock_drop_pct_ref_normal",
    "shock_drop_pct_ref_baseline",
    "shock_stage_avg",
    "shock_stage_std",
}


@dataclass(frozen=True)
class ParserRecognitionResponse:
    phases: list[tuple[float, float, str]]
    metrics: dict[str, float | None] | None = None


class ParserRestClient:
    def __init__(self, config: ParserConfig, http_client: Any | None = None) -> None:
        self._config = config
        self._base_url = _normalize_base_url(config.base_url)
        self._http = http_client

    def recognize_stages(self, time_series_csv_bytes: bytes) -> str:
        time_series_zip_bytes = _rewrite_zip_csv_separator(time_series_csv_bytes)
        body, content_type = _encode_multipart(
            fields={},
            files=[
                ("file", "timeseries.zip", "application/zip", time_series_zip_bytes),
            ],
        )
        payload = self._request_json(
            method="POST",
            path=_RECOGNITION_PATH,
            body=body,
            headers={"Content-Type": content_type},
            expected_statuses={202},
        )
        return _parse_recognition_id(payload)

    def get_recognition_status(self, recognition_id: str) -> str:
        payload = self._request_json(
            method="GET",
            path=(
                f"{_RECOGNITION_PATH}/"
                f"{urllib.parse.quote(recognition_id, safe='')}/status"
            ),
        )
        return _parse_status(payload)

    def get_disaster_stage_recognition(self, recognition_id: str) -> ParserRecognitionResponse:
        payload = self._request_json(
            method="GET",
            path=f"{_RECOGNITION_PATH}/{urllib.parse.quote(recognition_id, safe='')}",
        )
        return _parse_recognition_result(payload)

    def get_disaster_stages(self, recognition_id: str) -> list[tuple[float, float, str]]:
        return self.get_disaster_stage_recognition(recognition_id).phases

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        expected_statuses: set[int] | None = None,
    ) -> Any:
        response = self._request_bytes(
            method=method,
            path=path,
            body=body,
            headers=headers,
            accept="application/json",
            expected_statuses=expected_statuses,
        )
        if not response:
            return None
        try:
            return json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserRestInvalidResponseError(
                f"Parser service returned malformed JSON for {method} {self._build_url(path)}"
            ) from exc

    def _request_bytes(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        accept: str,
        expected_statuses: set[int] | None = None,
    ) -> bytes:
        url = self._build_url(path)
        request_headers = {"Accept": accept}
        if self._config.auth_token:
            request_headers["Authorization"] = f"Bearer {self._config.auth_token}"
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        timeout = self._config.timeout_seconds or 10
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if expected_statuses is not None and response.status not in expected_statuses:
                    response_body = response.read()
                    raise _http_error(
                        method=method,
                        url=url,
                        status=response.status,
                        body=response_body,
                    )
                return response.read()
        except urllib.error.HTTPError as exc:
            response_body = exc.read() if exc.fp else b""
            raise _http_error(method=method, url=url, status=exc.code, body=response_body) from exc
        except (urllib.error.URLError, socket.timeout) as exc:
            raise ParserRestConnectionError(
                f"Parser service request failed ({method} {url}): {exc}"
            ) from exc

    def _build_url(self, path: str) -> str:
        return urllib.parse.urljoin(f"{self._base_url}/", path.lstrip("/"))


def _normalize_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        raise ValueError("Parser base URL must not be empty")
    return normalized


def _encode_multipart(
    *,
    fields: dict[str, str | int | float | None],
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
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"'.encode("utf-8")
        )
        lines.append(f"Content-Type: {content_type}".encode("utf-8"))
        lines.append(b"")
        lines.append(data)
    lines.append(f"--{boundary}--".encode("utf-8"))
    lines.append(b"")
    body = b"\r\n".join(lines)
    return body, f"multipart/form-data; boundary={boundary}"


def _rewrite_zip_csv_separator(zip_bytes: bytes) -> bytes:
    filename, csv_text = _extract_single_csv_from_zip(zip_bytes)
    converted_csv_text = _convert_csv_delimiter(csv_text)
    return _build_zip_with_csv(filename, converted_csv_text)


def _extract_single_csv_from_zip(zip_bytes: bytes) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes), mode="r") as zf:
            csv_names = [
                name
                for name in zf.namelist()
                if not name.endswith("/") and name.lower().endswith(".csv")
            ]
            if not csv_names:
                raise ParserRestInvalidResponseError("Parser input ZIP does not contain a CSV file")
            if len(csv_names) > 1:
                raise ParserRestInvalidResponseError(
                    "Parser input ZIP contains multiple CSV files"
                )
            filename = csv_names[0]
            try:
                csv_text = zf.read(filename).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ParserRestInvalidResponseError(
                    "Parser input CSV is not valid UTF-8"
                ) from exc
            return filename, csv_text
    except zipfile.BadZipFile as exc:
        raise ParserRestInvalidResponseError("Parser input is not a valid ZIP archive") from exc


def _convert_csv_delimiter(
    csv_text: str,
    src_delimiter: str = ",",
    dst_delimiter: str = ";",
) -> str:
    input_buffer = StringIO(csv_text, newline="")
    output_buffer = StringIO(newline="")
    reader = csv.reader(input_buffer, delimiter=src_delimiter)
    writer = csv.writer(output_buffer, delimiter=dst_delimiter, lineterminator="\n")
    writer.writerows(reader)
    return output_buffer.getvalue()


def _build_zip_with_csv(filename: str, csv_text: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename or "timeseries.csv", csv_text.encode("utf-8"))
    return buffer.getvalue()


def _parse_recognition_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ParserRestInvalidResponseError("Parser service returned invalid recognition payload")
    value = payload.get("recognition_id")
    if value is None:
        raise ParserRestInvalidResponseError(
            "Parser service returned recognition payload without recognition_id field"
        )
    return str(value)


def _parse_status(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ParserRestInvalidResponseError("Parser service returned invalid status payload")
    value = payload.get("status")
    if value is None:
        raise ParserRestInvalidResponseError(
            "Parser service returned status payload without status field"
        )
    return str(value)


def _parse_phases(payload: Any) -> list[tuple[float, float, str]]:
    if not isinstance(payload, dict):
        raise ParserRestInvalidResponseError("Parser service returned invalid phases payload")
    phases = payload.get("phases")
    if phases is None:
        return []
    if not isinstance(phases, list):
        raise ParserRestInvalidResponseError(
            "Parser service returned phases payload without phases list"
        )
    parsed: list[tuple[float, float, str]] = []
    for phase in phases:
        if not isinstance(phase, (list, tuple)) or len(phase) != 3:
            raise ParserRestInvalidResponseError(
                "Parser service returned malformed phase entry"
            )
        start, end, phase_name = phase
        try:
            parsed.append((float(start), float(end), str(phase_name)))
        except (TypeError, ValueError) as exc:
            raise ParserRestInvalidResponseError(
                "Parser service returned phase entry with invalid start or end"
            ) from exc
    return parsed


def _parse_recognition_result(payload: Any) -> ParserRecognitionResponse:
    return ParserRecognitionResponse(
        phases=_parse_phases(payload),
        metrics=_parse_metrics(payload),
    )


def _parse_metrics(payload: Any) -> dict[str, float | None] | None:
    if not isinstance(payload, dict):
        raise ParserRestInvalidResponseError("Parser service returned invalid phases payload")
    metrics = payload.get("metrics")
    if metrics is None:
        return None
    if not isinstance(metrics, dict):
        return None

    parsed: dict[str, float | None] = {}
    for field in _METRIC_FIELDS:
        value = metrics.get(field)
        if value is None:
            parsed[field] = None
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            parsed[field] = None
            continue
        if not math.isfinite(numeric_value):
            parsed[field] = None
            continue
        parsed[field] = numeric_value
    return parsed


def _http_error(*, method: str, url: str, status: int, body: bytes) -> ParserRestHttpError:
    snippet = body.decode("utf-8", errors="replace").strip()
    if len(snippet) > 200:
        snippet = f"{snippet[:200]}..."
    if snippet:
        message = f"Parser service request failed ({method} {url}, status={status}, body={snippet})"
    else:
        message = f"Parser service request failed ({method} {url}, status={status})"
    return ParserRestHttpError(message, status_code=status, response_body=snippet or None)
