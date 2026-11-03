from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
import socket
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from adapters.slurm_adapter.slurm_token_refresher import SlurmTokenRefresher


@dataclass(frozen=True)
class SlurmRestConnectionError(RuntimeError):
    message: str
    operation: str
    base_url: str
    timeout_seconds: float | None = None

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class SlurmRestTimeoutError(SlurmRestConnectionError):
    pass


@dataclass(frozen=True)
class SlurmRestError(RuntimeError):
    status_code: int
    body_snippet: str
    operation: str
    base_url: str
    timeout_seconds: float | None = None

    @property
    def status(self) -> int:
        return self.status_code

    @property
    def snippet(self) -> str:
        return self.body_snippet

    def __str__(self) -> str:
        return f"Slurm REST error {self.status_code}: {self.body_snippet}"


@dataclass(frozen=True)
class SlurmRestProtocolError(RuntimeError):
    message: str
    operation: str
    base_url: str
    body_snippet: str = ""

    def __str__(self) -> str:
        return self.message


class SlurmRestClient:
    def __init__(
        self,
        *,
        address: str | None = None,
        slurm_port: int = 6820,
        api_version: str,
        username: str,
        token_refresher: SlurmTokenRefresher,
        scheme: str = "http",
        base_url: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.__address = address
        self.__slurm_port = slurm_port
        self.__scheme = scheme
        self.__base_url = _normalize_base_url(base_url)
        self.__api_version = api_version
        self.__username = username
        self.__token_refresher = token_refresher
        self.__timeout_seconds = float(timeout_seconds)

    def _request(
        self,
        *,
        method: str,
        url: str,
        operation: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        base_url = self._slurm_base()
        raw: bytes
        for attempt in range(2):
            secret = self.__token_refresher.get_secret()
            headers = {
                "X-SLURM-USER-NAME": self.__username,
                "X-SLURM-USER-TOKEN": secret,
            }
            if body is not None:
                headers["Content-Type"] = "application/json"
            request = Request(url, data=body, method=method, headers=headers)
            try:
                with urlopen(request, timeout=self.__timeout_seconds) as response:
                    raw = response.read()
                    break
            except HTTPError as exc:
                if exc.code in {401, 403} and attempt == 0:
                    self.__token_refresher.invalidate_secret(secret)
                    continue
                raw = exc.read()
                text = raw.decode("utf-8", errors="replace")
                snippet = text[:500]
                raise SlurmRestError(
                    exc.code,
                    snippet,
                    operation=operation,
                    base_url=base_url,
                    timeout_seconds=self.__timeout_seconds,
                ) from exc
            except (socket.timeout, TimeoutError) as exc:
                raise SlurmRestTimeoutError(
                    f"Slurm REST request timed out for {operation}: {exc}",
                    operation=operation,
                    base_url=base_url,
                    timeout_seconds=self.__timeout_seconds,
                ) from exc
            except (URLError, ConnectionResetError, ConnectionError, OSError) as exc:
                raise SlurmRestConnectionError(
                    f"Slurm REST connection failed for {operation}: {exc}",
                    operation=operation,
                    base_url=base_url,
                    timeout_seconds=self.__timeout_seconds,
                ) from exc

        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise SlurmRestProtocolError(
                f"Slurm REST returned malformed JSON for {operation}.",
                operation=operation,
                base_url=base_url,
                body_snippet=text[:500],
            ) from exc

    def submit_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._slurm_base()}/slurm/{self.__api_version}/job/submit"
        return self._request(method="POST", url=url, operation="submit_job", payload=payload)

    def get_slurm_job(self, job_id: str) -> dict[str, Any]:
        url = f"{self._slurm_base()}/slurm/{self.__api_version}/job/{job_id}"
        return self._request(method="GET", url=url, operation="get_slurm_job")

    def list_slurm_jobs(self) -> dict[str, Any]:
        url = f"{self._slurm_base()}/slurm/{self.__api_version}/jobs"
        return self._request(method="GET", url=url, operation="list_slurm_jobs")

    def _slurm_base(self) -> str:
        if self.__base_url:
            return self.__base_url
        return f"{self.__scheme}://{self.__address}:{self.__slurm_port}"


def _normalize_base_url(base_url: str | None) -> str | None:
    if base_url is None:
        return None
    value = str(base_url).strip()
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("slurm.base_url must include scheme and host")
    return value.rstrip("/")
