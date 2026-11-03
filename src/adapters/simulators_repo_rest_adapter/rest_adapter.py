from __future__ import annotations

import json
import socket
import uuid
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from urllib.parse import urlparse

from adapters.simulators_repo_rest_adapter.config import SimulatorsRepoConfig
from adapters.simulators_repo_rest_adapter.serialization import (
    parse_registration_details,
    parse_registration_summary,
    parse_simulator_details,
    parse_simulator_summary,
    serialize_build_spec,
    serialize_params,
)

from use_case_contracts.ports import SimulatorRepository
from use_case_contracts.dtos import (
    RegistrationDetails,
    RegistrationSummary,
    SimulatorDetails,
    SimulatorSummary,
    SimulatorBuildRecord
)
from use_case_contracts.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)


class RestSimulatorsRepositoryAdapter(SimulatorRepository):
    def __init__(self, config: SimulatorsRepoConfig, http_client: Any | None = None) -> None:
        self._config = config
        self._base_url = _normalize_base_url(config.base_url)
        self._http = http_client

    def register(self, record: SimulatorBuildRecord) -> str:
        fields = {
            "model_name": record.model_name,
            "build": serialize_build_spec(record.build_spec),
            "input_params": serialize_params(record.input_params),
            "output_params": serialize_params(record.output_params),
        }
        if record.zip_filename:
            fields["zip_filename"] = record.zip_filename
        filename = record.zip_filename or "model.zip"
        body, content_type = _encode_multipart(
            fields=fields,
            files=[
                ("zip_file", filename, "application/zip", record.zip_bytes),
            ],
        )
        response = self._request(
            method="POST",
            path="/simulators/register",
            body=body,
            headers={"Content-Type": content_type},
        )
        data = _parse_json(response, "register")
        registration_id = data.get("registration_id") if isinstance(data, dict) else None
        if not registration_id:
            raise ExternalServiceError("Simulators repo returned invalid registration response")
        return str(registration_id)

    def registration_status(self, registration_id: str) -> str:
        payload = {"registration_ids": [registration_id]}
        response = self._request(
            method="POST",
            path="/registrations/status",
            json_body=payload,
        )
        data = _parse_json(response, "registrations.status")
        if not isinstance(data, list):
            raise ExternalServiceError("Simulators repo returned invalid status response")
        match = next(
            (item for item in data if isinstance(item, dict) and item.get("build_id") == registration_id),
            None,
        )
        if match is None and len(data) == 1 and isinstance(data[0], dict):
            match = data[0]
        if not match:
            raise NotFoundError(f"Registration '{registration_id}' not found")
        status = match.get("status")
        if not status:
            raise ExternalServiceError("Simulators repo status response missing status field")
        return str(status)

    def get(self, simulator_id: str) -> SimulatorDetails | None:

        payload = {"model_ids": [simulator_id]}
        response = self._request(
            method="POST",
            path="/simulators/details",
            json_body=payload,
        )
        data = _parse_json(response, "simulators.details")
        if not isinstance(data, list):
            raise ExternalServiceError("Simulators repo returned invalid simulator details response")
        if not data:
            return None
        first = data[0]
        if not isinstance(first, dict):
            raise ExternalServiceError("Simulators repo returned invalid simulator details item")
        return parse_simulator_details(first)

    def list_simulators(self) -> list[SimulatorSummary]:
        response = self._request(method="GET", path="/simulators")
        data = _parse_json(response, "simulators.list")
        if not isinstance(data, list):
            raise ExternalServiceError("Simulators repo returned invalid simulators list response")
        summaries: list[SimulatorSummary] = []
        for item in data:
            if isinstance(item, dict):
                summaries.append(parse_simulator_summary(item))
        return summaries

    def list_recent_registrations(self, limit: int = 100) -> list[RegistrationSummary]:
        clamped = max(1, min(int(limit or 100), 1000))
        response = self._request(
            method="GET",
            path="/registrations/recent",
            query={"limit": clamped},
        )
        data = _parse_json(response, "registrations.recent")
        if not isinstance(data, list):
            raise ExternalServiceError("Simulators repo returned invalid registrations list response")
        summaries: list[RegistrationSummary] = []
        for item in data:
            if isinstance(item, dict):
                summaries.append(parse_registration_summary(item))
        return summaries

    def get_registration_details(self, registration_id: str) -> RegistrationDetails | None:
        recent = self.list_recent_registrations(limit=1000)
        summary = next((item for item in recent if item.registration_id == registration_id), None)
        status_payload = {"registration_ids": [registration_id]}
        response = self._request(
            method="POST",
            path="/registrations/status",
            json_body=status_payload,
        )
        data = _parse_json(response, "registrations.status")
        detail = None
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("build_id") == registration_id:
                    detail = item
                    break
            if detail is None and len(data) == 1 and isinstance(data[0], dict):
                detail = data[0]
        if summary is None and detail is None:
            return None
        details = parse_registration_details(detail or {})
        if summary:
            return RegistrationDetails(
                registration_id=summary.registration_id,
                model_name=summary.model_name,
                status=summary.status or details.status,
                created_at=summary.created_at or details.created_at,
                version=details.version,
                build_id=details.build_id,
            )
        return details

    def _request(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None = None,
        json_body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        url = self._build_url(path, query)
        req_headers = {"Accept": "application/json"}
        if self._config.auth_token:
            req_headers["Authorization"] = f"Bearer {self._config.auth_token}"
        if headers:
            req_headers.update(headers)
        data = body
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        timeout = 60
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body_text = exc.read() if exc.fp else b""
            message = _format_http_error(exc.code, url, body_text)
            if exc.code in (401, 403):
                raise AuthenticationError(message) from exc
            if exc.code == 404:
                raise NotFoundError(message) from exc
            if exc.code == 400:
                raise ValidationError(message) from exc
            raise ExternalServiceError(message) from exc
        except (urllib.error.URLError, socket.timeout) as exc:
            raise ExternalServiceError(
                f"Simulators repo request failed (url={url}): {exc}"
            ) from exc

    def _build_url(self, path: str, query: dict[str, Any] | None) -> str:
        path_text = path.strip("/")
        base = f"{self._base_url}/{path_text}"
        if not query:
            return base
        return base + "?" + urllib.parse.urlencode(query, doseq=True)


def _normalize_base_url(value: str) -> str:
    base = value.strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme and parsed.netloc:
        return base
    raise ValueError(f"Invalid simulators repo base_url: {value!r}")


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
        lines.append(
            f'Content-Disposition: form-data; name="{name}"'.encode("utf-8")
        )
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
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def _parse_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8")) if raw else None
    except json.JSONDecodeError as exc:
        raise ExternalServiceError(
            f"Simulators repo returned invalid JSON for {label}"
        ) from exc


def _format_http_error(status: int, url: str, body: bytes) -> str:
    snippet = body.decode("utf-8", errors="ignore")[:200]
    return f"Simulators repo error (status={status}, url={url}): {snippet}"
