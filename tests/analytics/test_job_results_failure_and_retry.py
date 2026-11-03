from __future__ import annotations

import threading
import time

from services.analytics.core.details.analytics_service_controller import (
    AnalyticsServiceController,
)
from use_case_contracts.dtos import ResultRef

_RESULT_URL = "https://host/config_0/results.csv.zip"

_SCALAR_FILE = (
    "repetition;A;output\n"
    "0;0.10;0.0\n"
    "1;0.10;0.5\n"
)


class _Repository:
    """Results repository whose download can fail and be repaired."""

    def __init__(self, files: dict[str, str], *, fail: bool = False, delay: float = 0.0) -> None:
        self._files = files
        self.fail = fail
        self._delay = delay
        self.downloads: list[str] = []

    def download(self, url: str) -> bytes:
        self.downloads.append(url)
        if self.fail:
            raise FileNotFoundError(url)
        if self._delay:
            time.sleep(self._delay)
        return self._files[url].encode("utf-8")


class _BlockingRepository:
    """Results repository that blocks until released, to hold a build in flight."""

    def __init__(self, files: dict[str, str], release: threading.Event) -> None:
        self._files = files
        self.release = release
        self.downloads: list[str] = []

    def download(self, url: str) -> bytes:
        self.downloads.append(url)
        self.release.wait(timeout=10)
        return self._files[url].encode("utf-8")


def _payload(job_id: str = "job-1"):
    return (
        job_id,
        "https://host/root",
        [ResultRef("", _RESULT_URL)],
        [("A", "float")],
        [("output", "float")],
    )


def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached within timeout")


def test_failed_build_records_error_and_initialize_does_not_rebuild() -> None:
    repository = _Repository({_RESULT_URL: _SCALAR_FILE}, fail=True)
    controller = AnalyticsServiceController(
        results_repository=repository, download_workers=1
    )

    controller.initialize_job(*_payload())
    _wait_until(lambda: controller.job_results_status("job-1") == "error")

    assert controller.job_results_status("job-1") == "error"
    assert controller.job_results_error("job-1") is not None

    downloads_before = len(repository.downloads)
    controller.initialize_job(*_payload())
    time.sleep(0.3)
    assert len(repository.downloads) == downloads_before
    assert controller.job_results_status("job-1") == "error"


def test_retry_rebuilds_after_failure() -> None:
    repository = _Repository({_RESULT_URL: _SCALAR_FILE}, fail=True)
    controller = AnalyticsServiceController(
        results_repository=repository, download_workers=1
    )

    controller.initialize_job(*_payload())
    _wait_until(lambda: controller.job_results_status("job-1") == "error")

    repository.fail = False
    controller.retry_job_results(*_payload())
    _wait_until(lambda: controller.job_results_status("job-1") == "ok")

    assert controller.job_results_error("job-1") is None
    assert len(repository.downloads) == 2


def test_initialize_job_does_not_duplicate_an_inflight_build() -> None:
    repository = _Repository(
        {_RESULT_URL: _SCALAR_FILE}, fail=False, delay=0.4
    )
    controller = AnalyticsServiceController(
        results_repository=repository, download_workers=1
    )

    controller.initialize_job(*_payload())
    controller.initialize_job(*_payload())
    time.sleep(0.1)
    assert controller.job_results_status("job-1") == "processing"

    _wait_until(lambda: controller.job_results_status("job-1") == "ok")
    assert len(repository.downloads) == 1


def test_stale_inflight_entry_is_pruned_after_configured_ttl() -> None:
    """A stuck inflight marker older than jobs_inflight_ttl_seconds no longer
    blocks re-initialization, and the knob is read from the controller config."""
    release = threading.Event()
    repository = _BlockingRepository({_RESULT_URL: _SCALAR_FILE}, release)
    controller = AnalyticsServiceController(
        results_repository=repository,
        download_workers=1,
        jobs_inflight_ttl_seconds=1,
    )

    controller.initialize_job(*_payload())
    _wait_until(lambda: len(repository.downloads) == 1)

    # TTL has now expired, so re-initializing must consider the entry stale and
    # enqueue another build instead of silently returning.
    time.sleep(1.1)
    controller.initialize_job(*_payload())

    release.set()
    _wait_until(lambda: len(repository.downloads) == 2)
    _wait_until(lambda: controller.job_results_status("job-1") == "ok")


def test_queued_job_reports_processing_before_a_builder_picks_it_up() -> None:
    """A job waiting in the queue (no free builder) must not look 'unknown'."""
    release = threading.Event()
    repository = _BlockingRepository({_RESULT_URL: _SCALAR_FILE}, release)
    controller = AnalyticsServiceController(
        results_repository=repository, download_workers=1
    )
    # Force a single builder so the second job stays queued.
    controller._job_entry_builders = controller._job_entry_builders[:1]
    controller._requests_processor._builders = controller._job_entry_builders

    controller.initialize_job(*_payload("job-1"))
    controller.initialize_job(*_payload("job-2"))
    time.sleep(0.2)

    assert controller.job_results_status("job-1") == "processing"
    assert controller.job_results_status("job-2") == "processing"

    release.set()
    _wait_until(
        lambda: controller.job_results_status("job-1") == "ok"
        and controller.job_results_status("job-2") == "ok"
    )


def test_status_is_unknown_for_an_unknown_job() -> None:
    controller = AnalyticsServiceController(
        results_repository=_Repository({}), download_workers=1
    )
    assert controller.job_results_status("never-seen") == "unknown"
    assert controller.job_results_error("never-seen") is None