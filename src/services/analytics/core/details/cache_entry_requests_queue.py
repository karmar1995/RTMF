from __future__ import annotations

import queue
from queue import Queue

from services.analytics.core.details.job_results_cache import CacheEntryRequest


class CacheEntryRequestsQueue:
    """Thread-safe queue that decouples request submission from cache entry building."""

    def __init__(self, maxsize: int = 0) -> None:
        self._queue: Queue[CacheEntryRequest] = Queue(maxsize=maxsize)

    def put(self, request: CacheEntryRequest) -> None:
        """Enqueue a cache entry request."""

        self._queue.put(request)

    def pop(self) -> CacheEntryRequest | None:
        """Return the next request if available, otherwise None."""

        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None
