from __future__ import annotations

import json
import socket
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import uuid

from adapters.system_discovery_rest_adapter.config import SystemDiscoveryConfig
from adapters.system_discovery_rest_adapter.errors import (
    SystemDiscoveryProtocolError,
    SystemDiscoveryRequestRejectedError,
    SystemDiscoveryResourceNotFoundError,
    SystemDiscoveryServiceUnavailableError,
)
from adapters.system_discovery_rest_adapter.mapping import (
    parse_simulation_status,
    parse_simulation_submission,
    parse_training_status,
    parse_training_submission,
    serialize_initial_conditions,
    serialize_system_parameters,
)
from use_case_contracts.dtos import (
    SystemDiscoverySimulationRequest,
    SystemDiscoverySimulationResultsArchive,
    SystemDiscoverySimulationStatus,
    SystemDiscoverySimulationSubmission,
    SystemDiscoveryTrainingRequest,
    SystemDiscoveryTrainingResultsArchive,
    SystemDiscoveryTrainingStatus,
    SystemDiscoveryTrainingSubmission,
)

_ZIP_MEDIA_TYPES = {"application/zip", "application/x-zip-compressed"}


class SystemDiscoveryRestClient:
    def __init__(self, config: SystemDiscoveryConfig, http_client: Any | None = None) -> None:
        self._config = config
        self._base_url = _normalize_base_url(config.base_url)
        self._http = http_client

    def submit_training(
        self,
        request: SystemDiscoveryTrainingRequest,
    ) -> SystemDiscoveryTrainingSubmission:
        body, content_type = _encode_multipart(
            fields={
                "system_parameters": serialize_system_parameters(request.system_parameters),
            },
            files=[
                ("data", "training_data.zip", "application/zip", request.training_data_archive),
            ],
        )
        payload = self._request_json(
            method="POST",
            path="/api/v1/train",
            body=body,
            headers={"Content-Type": content_type},
        )
        return parse_training_submission(payload)

    def get_training_status(self, training_id: str) -> SystemDiscoveryTrainingStatus:
        payload = self._request_json(
            method="GET",
            path=f"/api/v1/get_training_status/{urllib.parse.quote(training_id, safe='')}",
        )
        return parse_training_status(payload, requested_training_id=training_id)

    def download_training_results(self, training_id: str) -> SystemDiscoveryTrainingResultsArchive:
        content = self._request_zip(
            method="GET",
            path=f"/api/v1/get_training_results/{urllib.parse.quote(training_id, safe='')}",
        )
        return SystemDiscoveryTrainingResultsArchive(content=content)

    def submit_system_discovery_simulation(
        self,
        request: SystemDiscoverySimulationRequest,
    ) -> SystemDiscoverySimulationSubmission:
        fields: dict[str, str | int | None] = {
            "horizon": request.horizon,
            "initial_conditions": (
                None
                if request.initial_conditions is None
                else serialize_initial_conditions(request.initial_conditions)
            ),
        }
        body, content_type = _encode_multipart(
            fields=fields,
            files=[
                ("data", "simulation_data.zip", "application/zip", request.model_and_input_archive),
            ],
        )
        payload = self._request_json(
            method="POST",
            path="/api/v1/simulate",
            body=body,
            headers={"Content-Type": content_type},
        )
        return parse_simulation_submission(payload)

    def get_system_discovery_simulation_status(
        self,
        simulation_id: str,
    ) -> SystemDiscoverySimulationStatus:
        payload = self._request_json(
            method="GET",
            path=f"/api/v1/get_simulation_status/{urllib.parse.quote(simulation_id, safe='')}",
        )
        return parse_simulation_status(payload)

    def download_system_discovery_simulation_results(
        self,
        simulation_id: str,
    ) -> SystemDiscoverySimulationResultsArchive:
        content = self._request_zip(
            method="GET",
            path=f"/api/v1/get_simulation_results/{urllib.parse.quote(simulation_id, safe='')}",
        )
        return SystemDiscoverySimulationResultsArchive(content=content)

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response, content_type = self._request_bytes(
            method=method,
            path=path,
            body=body,
            headers=headers,
            accept="application/json",
        )
        if content_type and "json" not in content_type:
            raise SystemDiscoveryProtocolError(
                f"System Discovery service returned unexpected media type for {method} {self._build_url(path)}"
            )
        if not response:
            return None
        try:
            return json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemDiscoveryProtocolError(
                f"System Discovery service returned malformed JSON for {method} {self._build_url(path)}"
            ) from exc

    def _request_zip(self, *, method: str, path: str) -> bytes:
        response, content_type = self._request_bytes(
            method=method,
            path=path,
            accept="application/zip",
        )
        if content_type not in _ZIP_MEDIA_TYPES:
            raise SystemDiscoveryProtocolError(
                f"System Discovery service returned unexpected ZIP media type for {method} {self._build_url(path)}"
            )
        return response

    def _request_bytes(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        accept: str,
    ) -> tuple[bytes, str | None]:
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
                content_type = _response_content_type(response)
                return response.read(), content_type
        except urllib.error.HTTPError as exc:
            response_body = exc.read() if exc.fp else b""
            message = _format_http_error(method=method, url=url, status=exc.code, body=response_body)
            if exc.code == 404:
                raise SystemDiscoveryResourceNotFoundError(message) from exc
            if exc.code in (400, 422):
                raise SystemDiscoveryRequestRejectedError(message) from exc
            if exc.code >= 500:
                raise SystemDiscoveryServiceUnavailableError(message) from exc
            raise SystemDiscoveryProtocolError(message) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            raise SystemDiscoveryServiceUnavailableError(
                f"System Discovery service request failed ({method} {url}): {exc}"
            ) from exc

    def _build_url(self, path: str) -> str:
        return urllib.parse.urljoin(f"{self._base_url}/", path.lstrip("/"))


def _normalize_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        raise ValueError("System Discovery base URL must not be empty")
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


def _response_content_type(response: Any) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    get_content_type = getattr(headers, "get_content_type", None)
    if callable(get_content_type):
        return str(get_content_type()).lower()
    value = headers.get("Content-Type") if hasattr(headers, "get") else None
    if value is None:
        return None
    return str(value).split(";", 1)[0].strip().lower()


def _format_http_error(*, method: str, url: str, status: int, body: bytes) -> str:
    snippet = body.decode("utf-8", errors="replace").strip()
    if len(snippet) > 200:
        snippet = f"{snippet[:200]}..."
    if snippet:
        return (
            f"System Discovery service request failed "
            f"({method} {url}, body={snippet})"
        )
    return f"System Discovery service request failed ({method} {url})"
