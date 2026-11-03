from __future__ import annotations

import threading

from services.analytics.core.details.time_limited_cache import TimeLimitedCache


class TimeLimitedCacheGarbageCollector:
    """Periodically inspects registered cache entries in batches and removes expired ones."""

    def __init__(
        self,
        caches: list[TimeLimitedCache] | None = None,
        interval_seconds: float = 30.0,
        batch_size: int = 3,
        cache: TimeLimitedCache | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._caches: list[TimeLimitedCache] = []
        self._cursors: dict[int, int] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        if caches is not None:
            for registered_cache in caches:
                self.add_cache(registered_cache)
        if cache is not None:
            self.add_cache(cache)

    def start(self) -> None:
        """Start the GC daemon thread if it is not already running."""

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Request the GC thread to stop and wait for it to exit."""

        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def is_running(self) -> bool:
        """Return whether the GC daemon thread is currently alive."""

        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def add_cache(self, cache: TimeLimitedCache) -> None:
        """Register a cache for periodic garbage collection."""

        cache_id = id(cache)
        with self._lock:
            if cache_id in self._cursors:
                return
            self._caches.append(cache)
            self._cursors[cache_id] = 0

    def remove_cache(self, cache: TimeLimitedCache) -> None:
        """Unregister a cache from periodic garbage collection."""

        cache_id = id(cache)
        with self._lock:
            if cache_id not in self._cursors:
                return
            self._caches = [registered_cache for registered_cache in self._caches if registered_cache is not cache]
            self._cursors.pop(cache_id, None)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._collect_once()
            self._stop_event.wait(self._interval_seconds)

    def _collect_once(self) -> None:
        with self._lock:
            caches = list(self._caches)

        for cache in caches:
            entry_ids = cache.get_entry_ids()
            if not entry_ids:
                continue

            subset = self._select_subset(cache, entry_ids)
            if not subset:
                continue

            cache.cleanup_if_expired(subset)

    def _select_subset(
        self,
        cache: TimeLimitedCache,
        entry_ids: list[str],
    ) -> list[str]:
        cache_id = id(cache)
        with self._lock:
            if cache_id not in self._cursors:
                return []
            if len(entry_ids) <= self._batch_size:
                self._cursors[cache_id] = 0
                return entry_ids

            cursor = self._cursors[cache_id]
            start = cursor % len(entry_ids)
            end = start + self._batch_size
            if end <= len(entry_ids):
                subset = entry_ids[start:end]
            else:
                overflow = end - len(entry_ids)
                subset = entry_ids[start:] + entry_ids[:overflow]
            self._cursors[cache_id] = (start + self._batch_size) % len(entry_ids)
            return subset
