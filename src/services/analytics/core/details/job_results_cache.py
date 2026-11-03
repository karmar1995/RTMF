from __future__ import annotations

import threading
from dataclasses import dataclass

from services.analytics.core.details.time_limited_cache import TimeLimitedCache
from services.analytics.core.model import JobResult


@dataclass
class CacheEntryRequest:
    job_id: str
    job_root_url: str
    results_urls: list[str]
    input_parameters: list[tuple[str, str]]
    output_parameters: list[tuple[str, str]]


class JobResultsCache(TimeLimitedCache):
    """Time-limited in-memory cache for lazily created JobResult instances."""

    def get(self, job_id: str) -> JobResult | None:
        """Return a cached job result and refresh access time if the entry is still valid."""

        entry = super().get(job_id)
        return entry

    def put(self, job_id: str, job_result: JobResult) -> None:
        """Store or replace a cached job result."""

        super().put(job_id, job_result)

    def get_jobs_ids(self) -> list[str]:
        """Return a snapshot of the currently stored job ids."""

        return super().get_entry_ids()


class JobResultFailures:
    """Registry of job results builds that failed, so a failed build stays
    distinguishable from a still-running one instead of collapsing into
    'unknown' once the builder clears its assignment."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, str] = {}

    def put(self, job_id: str, message: str) -> None:
        with self._lock:
            self._entries[job_id] = message

    def get(self, job_id: str) -> str | None:
        with self._lock:
            return self._entries.get(job_id)

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._entries.pop(job_id, None)
