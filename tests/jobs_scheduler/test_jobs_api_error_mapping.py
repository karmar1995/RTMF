from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from services.jobs_scheduler.core.dtos import JobSummary
from services.jobs_scheduler.core.errors import (
    SlurmAuthenticationError,
    SlurmProtocolError,
    SlurmTokenUnavailableError,
    SlurmUnavailableError,
)
from services.jobs_scheduler.rest_api.app import create_app


@dataclass
class FakeJobsController:
    result: list[JobSummary] | None = None
    error: Exception | None = None

    def list_jobs(self) -> list[JobSummary]:
        if self.error is not None:
            raise self.error
        return self.result or []


def _list_jobs_endpoint(controller: FakeJobsController):
    app = create_app(controller)  # type: ignore[arg-type]
    routes = list(app.routes)
    while routes:
        route = routes.pop()
        if getattr(route, "path", None) == "/jobs":
            return route.endpoint
        if hasattr(route, "original_router"):
            routes.extend(route.original_router.routes)
    raise AssertionError("/jobs route not found")


def test_list_jobs_successful_response() -> None:
    endpoint = _list_jobs_endpoint(
        FakeJobsController(result=[JobSummary(job_id="101", status="running")])
    )

    result = endpoint()

    assert [item.model_dump() for item in result] == [
        {"job_id": "101", "status": "running"}
    ]


def test_token_generation_outage_maps_to_503_and_safe_detail(caplog) -> None:
    caplog.set_level(logging.WARNING)
    endpoint = _list_jobs_endpoint(
        FakeJobsController(
            error=SlurmTokenUnavailableError(
                "Slurm token generation timed out.",
                diagnostic_context={
                    "operation": "generate_slurm_token",
                    "adapter": "SlurmTokenRefresher",
                    "command": "scontrol",
                    "timeout_seconds": 10,
                },
            )
        )
    )

    with pytest.raises(Exception) as exc_info:
        endpoint()

    response = exc_info.value
    assert response.status_code == 503
    assert response.detail == "Slurm scheduler authentication is temporarily unavailable."
    assert "generate_slurm_token" in caplog.text
    assert "scontrol" in caplog.text


def test_slurm_network_failure_maps_to_503(caplog) -> None:
    caplog.set_level(logging.WARNING)
    endpoint = _list_jobs_endpoint(
        FakeJobsController(
            error=SlurmUnavailableError(
                "Slurm scheduler is temporarily unavailable.",
                diagnostic_context={
                    "operation": "list_jobs",
                    "adapter": "SlurmJobsScheduler",
                    "base_url": "http://slurm:6820",
                },
            )
        )
    )

    with pytest.raises(Exception) as exc_info:
        endpoint()

    response = exc_info.value
    assert response.status_code == 503
    assert response.detail == "Slurm scheduler is temporarily unavailable."
    assert "list_jobs" in caplog.text
    assert "http://slurm:6820" in caplog.text


def test_final_slurm_auth_failure_maps_to_safe_503(caplog) -> None:
    caplog.set_level(logging.WARNING)
    endpoint = _list_jobs_endpoint(
        FakeJobsController(
            error=SlurmAuthenticationError(
                "Slurm scheduler authentication failed.",
                diagnostic_context={
                    "operation": "list_jobs",
                    "adapter": "SlurmJobsScheduler",
                    "status_code": 403,
                },
            )
        )
    )

    with pytest.raises(Exception) as exc_info:
        endpoint()

    response = exc_info.value
    assert response.status_code == 503
    assert response.detail == "Slurm scheduler authentication is temporarily unavailable."
    assert "status_code': 403" in caplog.text


def test_invalid_slurm_response_maps_to_502(caplog) -> None:
    caplog.set_level(logging.WARNING)
    endpoint = _list_jobs_endpoint(
        FakeJobsController(
            error=SlurmProtocolError(
                "Slurm scheduler returned malformed data.",
                diagnostic_context={"operation": "list_jobs", "adapter": "SlurmJobsScheduler"},
            )
        )
    )

    with pytest.raises(Exception) as exc_info:
        endpoint()

    response = exc_info.value
    assert response.status_code == 502
    assert response.detail == "Slurm scheduler returned an invalid response."
    assert "Slurm protocol failure" in caplog.text


def test_unexpected_exception_maps_to_500_and_logs_traceback(caplog) -> None:
    caplog.set_level(logging.ERROR)
    endpoint = _list_jobs_endpoint(FakeJobsController(error=ValueError("boom")))

    with pytest.raises(Exception) as exc_info:
        endpoint()

    response = exc_info.value
    assert response.status_code == 500
    assert response.detail == "Internal server error."
    assert "Unexpected jobs scheduler request failure" in caplog.text
    assert "Traceback" in caplog.text
    assert "ValueError: boom" in caplog.text
