from __future__ import annotations

import logging
import threading

from use_case_contracts.messages import (
    CleanupExpiredSystemDiscoveryTrainingQueueEntries,
)
from use_case_contracts.ports import UseCaseAPI

logger = logging.getLogger(__name__)


class PeriodicSystemDiscoveryTrainingQueueCleanup:
    def __init__(
        self,
        *,
        usecases: UseCaseAPI,
        interval_seconds: float,
        terminal_retention_days: int,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("System Discovery cleanup interval must be positive")
        if terminal_retention_days < 0:
            raise ValueError("System Discovery cleanup retention must not be negative")
        self._usecases = usecases
        self._interval_seconds = interval_seconds
        self._terminal_retention_days = terminal_retention_days
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self.is_running():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run_once(self) -> None:
        try:
            self._usecases.handle(
                CleanupExpiredSystemDiscoveryTrainingQueueEntries(
                    terminal_retention_days=self._terminal_retention_days
                )
            )
        except Exception:
            logger.exception("System Discovery training queue cleanup failed")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._stop_event.wait(self._interval_seconds):
                return
            self.run_once()
