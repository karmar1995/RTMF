from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import threading


@dataclass
class _CacheEntry:
    """Internal cache metadata kept separate from cached objects."""

    entry: object
    last_accessed: datetime


class TimeLimitedCache:
    """Thread-safe time-limited in-memory cache for arbitrary objects."""

    def __init__(self, ttl: timedelta) -> None:
        if ttl < timedelta(0):
            raise ValueError("ttl must not be negative")
        self._ttl = ttl
        self._clock = _utc_now
        self._entries: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, entry_id: str) -> object | None:
        """Return a cached entry and refresh access time if it exists."""

        now = self._current_time()
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return None
            entry.last_accessed = now
            return entry.entry

    def put(self, entry_id: str, entry: object) -> None:
        """Store or replace a cached entry."""

        with self._lock:
            self._entries[entry_id] = _CacheEntry(
                entry=entry,
                last_accessed=self._current_time(),
            )

    def get_entry_ids(self) -> list[str]:
        """Return a snapshot of the currently stored entry ids."""

        with self._lock:
            return list(self._entries.keys())

    def cleanup_if_expired(self, entry_ids: list[str]) -> list[str]:
        """Remove expired entries and return their ids."""

        now = self._current_time()
        expired_entry_ids: list[str] = []
        with self._lock:
            for entry_id in entry_ids:
                if self._is_expired(entry_id, now):
                    expired_entry_ids.append(entry_id)
            for entry_id in expired_entry_ids:
                self._entries.pop(entry_id, None)
            return expired_entry_ids

    def _current_time(self) -> datetime:
        current_time = self._clock()
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return current_time.astimezone(UTC)

    def _is_expired(self, entry_id: str, now: datetime) -> bool:
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        return now - entry.last_accessed >= self._ttl


def _utc_now() -> datetime:
    return datetime.now(UTC)
