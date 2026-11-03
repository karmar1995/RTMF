from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from adapters.jobs_scheduler_rest_adapter.config import JobsSchedulerConfig
from adapters.jobs_scheduler_rest_adapter.serialization import (
    parse_job_info,
    parse_job_summary_list,
    parse_scheduled_batch_info,
    parse_sub_job_info_list,
    parse_text_response_payload,
)
from use_case_contracts.ports import JobsSchedulerPort
from use_case_contracts.dtos import JobInfo, JobSummary, ScheduledBatchInfo, SubJobInfo
from use_case_contracts.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)


class RestJobsSchedulerAdapter(JobsSchedulerPort):
    def __init__(self, config: JobsSchedulerConfig, http_client: Any | None = None) -> None:
        self._config = config
        self._base_url = _normalize_base_url(config.base_url)
        self._http = http_client

    def submit_simulation_batch(
        self,
        simulator_uri: str,
        matrix_uri: str,
        combinations: int,
        simulator_id: str,
    ) -> ScheduledBatchInfo:
        payload = self._request_json(
            method="POST",
            path="/jobs/submit",
            payload={
                "simulator_uri": simulator_uri,
                "matrix_uri": matrix_uri,
                "combinations": combinations,
                "simulator_id": simulator_id,
            },
        )
        return parse_scheduled_batch_info(payload)

    def get_job(self, job_id: str) -> JobInfo | None:
        try:
            payload = self._request_json(
                method="GET",
                path=f"/jobs/{urllib.parse.quote(job_id, safe='')}",
            )
        except NotFoundError:
            return None
        return parse_job_info(payload)

    def list_jobs(self) -> list[JobSummary]:
        payload = self._request_json(method="GET", path="/jobs")
        return parse_job_summary_list(payload)

    def get_job_sub_jobs(self, job_id: str) -> list[SubJobInfo]:
        try:
            payload = self._request_json(
                method="GET",
                path=f"/jobs/{urllib.parse.quote(job_id, safe='')}/sub-jobs",
            )
        except NotFoundError:
            return []
        return parse_sub_job_info_list(payload)

    def get_sub_job_stderr(self, job_id: str, sub_job_id: str) -> str:
        payload = self._request_json(
            method="GET",
            path=(
                f"/jobs/{urllib.parse.quote(job_id, safe='')}/sub-jobs/"
                f"{urllib.parse.quote(sub_job_id, safe='')}/stderr"
            ),
        )
        return parse_text_response_payload(payload)

    def get_sub_job_stdout(self, job_id: str, sub_job_id: str) -> str:
        payload = self._request_json(
            method="GET",
            path=(
                f"/jobs/{urllib.parse.quote(job_id, safe='')}/sub-jobs/"
                f"{urllib.parse.quote(sub_job_id, safe='')}/stdout"
            ),
        )
        return parse_text_response_payload(payload)

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        response = self._request_bytes(
            method=method,
            path=path,
            payload=payload,
            accept="application/json",
        )
        if not response:
            return None
        try:
            return json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExternalServiceError(
                f"Jobs scheduler service returned malformed JSON for {method} {self._build_url(path)}"
            ) from exc

    def _request_bytes(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        accept: str,
    ) -> bytes:
        url = self._build_url(path)
        headers = {"Accept": accept}
        data = None
        if self._config.auth_token:
            headers["Authorization"] = f"Bearer {self._config.auth_token}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        timeout = self._config.timeout_seconds or 10
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body_text = exc.read() if exc.fp else b""
            message = _format_http_error(method=method, url=url, status=exc.code, body=body_text)
            if exc.code in (401, 403):
                raise AuthenticationError(message) from exc
            if exc.code == 404:
                raise NotFoundError(message) from exc
            if exc.code == 400:
                raise ValidationError(message) from exc
            raise ExternalServiceError(message) from exc
        except (urllib.error.URLError, socket.timeout) as exc:
            raise ExternalServiceError(
                f"Jobs scheduler service request failed ({method} {url}): {exc}"
            ) from exc

    def _build_url(self, path: str) -> str:
        return urllib.parse.urljoin(f"{self._base_url}/", path.lstrip("/"))


def _normalize_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        raise ValueError("Jobs scheduler base URL must not be empty")
    return normalized


def _format_http_error(*, method: str, url: str, status: int, body: bytes) -> str:
    snippet = body.decode("utf-8", errors="replace").strip()
    if len(snippet) > 200:
        snippet = f"{snippet[:200]}..."
    if snippet:
        return (
            f"Jobs scheduler service request failed "
            f"({method} {url}, status={status}, body={snippet})"
        )
    return f"Jobs scheduler service request failed ({method} {url}, status={status})"
