from __future__ import annotations

import json
import socket
import uuid
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from adapters.evaluator_rest_adapter.config import EvaluatorConfig
from adapters.evaluator_rest_adapter.serialization import (
    parse_evaluation_id,
    parse_evaluation_progress,
    parse_evaluation_result,
    parse_evaluation_summaries,
    parse_status,
)
from use_case_contracts.dtos import (
    EvaluationProgress,
    EvaluationResult,
    EvaluationSummary,
)
from use_case_contracts.errors import (
    AuthenticationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from use_case_contracts.ports import EvaluatorPort


class RestEvaluatorAdapter(EvaluatorPort):
    def __init__(self, config: EvaluatorConfig, http_client: Any | None = None) -> None:
        self._config = config
        self._base_url = _normalize_base_url(config.base_url)
        self._http = http_client

    def evaluate(
        self,
        simulator_id: str,
        number_of_repetitions=128,
        *,
        kmax: int = 30,
        epsilon: float = 1e-3,
        batch_size: int = 1,
        lhs_candidates: int = 1500,
        random_state: int = 42,
        problem: dict | None = None,
        aggregation: str | None = None,
    ) -> str:
        fields = {
            "simulator_id": simulator_id,
            "kmax": str(int(kmax)),
            "epsilon": str(epsilon),
            "batch_size": str(int(batch_size)),
            "lhs_candidates": str(int(lhs_candidates)),
            "random_state": str(int(random_state)),
            "number_of_repetitions": str(int(number_of_repetitions)),
        }
        if aggregation is not None:
            fields["aggregation"] = str(aggregation)
        files: dict[str, tuple[str, bytes, str]] | None = None
        if problem is not None:
            files = {
                "config_file": (
                    "problem.json",
                    json.dumps(problem).encode("utf-8"),
                    "application/json",
                )
            }
        payload = self._request_json(
            method="POST",
            path="/evaluations/",
            fields=fields,
            files=files,
        )
        return parse_evaluation_id(payload)

    def get_evaluation_status(self, evaluation_id: str) -> str:
        payload = self._request_json(
            method="GET",
            path=f"/evaluations/{urllib.parse.quote(evaluation_id, safe='')}/status",
        )
        return parse_status(payload)

    def get_evaluation_progress(self, evaluation_id: str) -> EvaluationProgress:
        payload = self._request_json(
            method="GET",
            path=f"/evaluations/{urllib.parse.quote(evaluation_id, safe='')}/progress",
        )
        return parse_evaluation_progress(payload)

    def get_evaluation_results(self, evaluation_id: str) -> EvaluationResult:
        payload = self._request_json(
            method="GET",
            path=f"/evaluations/{urllib.parse.quote(evaluation_id, safe='')}/results",
        )
        return parse_evaluation_result(payload)

    def list_evaluations(self) -> list[EvaluationSummary]:
        payload = self._request_json(method="GET", path="/evaluations/")
        return parse_evaluation_summaries(payload)

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        fields: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> Any:
        response = self._request_bytes(
            method=method,
            path=path,
            fields=fields,
            files=files,
            accept="application/json",
        )
        if not response:
            return None
        try:
            return json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExternalServiceError(
                f"Evaluator service returned malformed JSON for {method} {self._build_url(path)}"
            ) from exc

    def _request_bytes(
        self,
        *,
        method: str,
        path: str,
        fields: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        accept: str,
    ) -> bytes:
        url = self._build_url(path)
        headers = {"Accept": accept}
        data = None
        if self._config.auth_token:
            headers["Authorization"] = f"Bearer {self._config.auth_token}"
        if fields or files:
            data, content_type = _build_multipart_body(fields, files)
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        timeout = self._config.timeout_seconds or 10
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body_text = exc.read() if exc.fp else b""
            message = _format_http_error(
                method=method, url=url, status=exc.code, body=body_text
            )
            if exc.code in (401, 403):
                raise AuthenticationError(message) from exc
            if exc.code == 404:
                raise NotFoundError(message) from exc
            if exc.code == 400:
                raise ValidationError(message) from exc
            if exc.code == 409:
                raise ConflictError(message) from exc
            raise ExternalServiceError(message) from exc
        except (urllib.error.URLError, socket.timeout) as exc:
            raise ExternalServiceError(
                f"Evaluator service request failed ({method} {url}): {exc}"
            ) from exc

    def _build_url(self, path: str) -> str:
        return urllib.parse.urljoin(f"{self._base_url}/", path.lstrip("/"))


def _build_multipart_body(
    fields: dict[str, str] | None,
    files: dict[str, tuple[str, bytes, str]] | None,
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in (fields or {}).items():
        chunks.append(_part(boundary, name, None, value.encode("utf-8"), "text/plain"))
    for name, (filename, content, content_type) in (files or {}).items():
        chunks.append(_part(boundary, name, filename, content, content_type))
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _part(
    boundary: str,
    name: str,
    filename: str | None,
    content: bytes,
    content_type: str,
) -> bytes:
    disposition = f'form-data; name="{name}"'
    if filename:
        disposition += f'; filename="{filename}"'
    header = f"--{boundary}\r\n"
    header += f"Content-Disposition: {disposition}\r\n"
    header += f"Content-Type: {content_type}\r\n\r\n"
    return header.encode("utf-8") + content + b"\r\n"


def _normalize_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        raise ValueError("Evaluator base URL must not be empty")
    return normalized


def _format_http_error(*, method: str, url: str, status: int, body: bytes) -> str:
    snippet = body.decode("utf-8", errors="replace").strip()
    if len(snippet) > 200:
        snippet = f"{snippet[:200]}..."
    if snippet:
        return (
            f"Evaluator service request failed ({method} {url}, "
            f"status={status}, body={snippet})"
        )
    return f"Evaluator service request failed ({method} {url}, status={status})"
