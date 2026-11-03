from __future__ import annotations

import threading

from services.analytics.core.details.cache_entry_requests_queue import CacheEntryRequestsQueue
from services.analytics.core.details.job_results_cache_entry_builder import JobResultsEntryCacheBuilder


class CacheEntryRequestsProcessor:
    """Dispatch queued cache entry requests to the first available builder."""

    def __init__(
        self,
        requests_queue: CacheEntryRequestsQueue,
        builders: list[JobResultsEntryCacheBuilder],
        dispatch_interval: float = 0.5,
    ) -> None:
        self._requests_queue = requests_queue
        self._builders = builders
        self._dispatch_interval = dispatch_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the background dispatcher thread if it is not already running."""

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Request dispatcher shutdown and wait for the thread to exit."""

        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def is_running(self) -> bool:
        """Return whether the dispatcher thread is currently alive."""

        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._dispatch_once()
            self._stop_event.wait(self._dispatch_interval)

    def _dispatch_once(self) -> None:
        builder = self._find_available_builder()
        if builder is None:
            return

        request = self._requests_queue.pop()
        if request is None:
            return

        builder.assign(request)

    def _find_available_builder(self) -> JobResultsEntryCacheBuilder | None:
        for builder in self._builders:
            if not builder.busy():
                return builder
        return None
