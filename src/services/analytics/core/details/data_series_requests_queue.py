from __future__ import annotations

import queue
from queue import Queue

from services.analytics.core.details.data_series_cache import DataSeriesRequest


class DataSeriesRequestsQueue:
    """Thread-safe queue that decouples request submission from data-series cache entry building."""

    def __init__(self, maxsize: int = 0) -> None:
        self._queue: Queue[DataSeriesRequest] = Queue(maxsize=maxsize)

    def put(self, request: DataSeriesRequest) -> None:
        """Enqueue a data-series request."""

        self._queue.put(request)

    def pop(self) -> DataSeriesRequest | None:
        """Return the next request if available, otherwise None."""

        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None
