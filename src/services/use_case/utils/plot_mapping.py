from __future__ import annotations

from dataclasses import fields, is_dataclass
from threading import Lock
import time

from use_case_contracts.dtos import PlotSpec


DEFAULT_PLOT_MAPPING_TTL_SECONDS = 12 * 60 * 60


class PlotMapping:
    """In-memory TTL cache for plot render ids keyed by series id and plot spec value."""

    def __init__(self, ttl_seconds: int = DEFAULT_PLOT_MAPPING_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = Lock()
        self._entries: dict[tuple[str, tuple], tuple[str, float]] = {}

    def get(self, series_id: str, plot_spec: PlotSpec) -> str | None:
        """Return a cached html id for the series/spec pair, or None if missing/expired."""
        key = self._build_key(series_id, plot_spec)
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            html_id, stored_at = entry
            if self._is_expired(stored_at, now):
                self._entries.pop(key, None)
                return None
            return html_id

    def store(self, series_id: str, plot_spec: PlotSpec, html_id: str) -> None:
        """Store or replace a cached html id for the series/spec pair."""
        key = self._build_key(series_id, plot_spec)
        now = time.monotonic()
        with self._lock:
            self._cleanup_expired(now)
            self._entries[key] = (html_id, now)

    def clear(self) -> None:
        """Remove all cached entries."""
        with self._lock:
            self._entries.clear()

    def _cleanup_expired(self, now: float) -> None:
        expired_keys = [
            key for key, (_, stored_at) in self._entries.items()
            if self._is_expired(stored_at, now)
        ]
        for key in expired_keys:
            self._entries.pop(key, None)

    def _is_expired(self, stored_at: float, now: float) -> bool:
        return now - stored_at >= self._ttl_seconds

    def _build_key(self, series_id: str, plot_spec: PlotSpec) -> tuple[str, tuple]:
        return series_id, _normalize_value(plot_spec)


class ParserRecognitionMapping:
    """In-memory TTL cache for parser recognition ids keyed by prepared series id."""

    def __init__(self, ttl_seconds: int = DEFAULT_PLOT_MAPPING_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = Lock()
        self._entries: dict[str, tuple[str, float]] = {}

    def get(self, series_id: str) -> str | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(series_id)
            if entry is None:
                return None
            recognition_id, stored_at = entry
            if self._is_expired(stored_at, now):
                self._entries.pop(series_id, None)
                return None
            return recognition_id

    def store(self, series_id: str, recognition_id: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._cleanup_expired(now)
            self._entries[series_id] = (recognition_id, now)

    def _cleanup_expired(self, now: float) -> None:
        expired_keys = [
            key for key, (_, stored_at) in self._entries.items()
            if self._is_expired(stored_at, now)
        ]
        for key in expired_keys:
            self._entries.pop(key, None)

    def _is_expired(self, stored_at: float, now: float) -> bool:
        return now - stored_at >= self._ttl_seconds


def _normalize_value(value):
    if is_dataclass(value) and not isinstance(value, type):
        return tuple(
            (field.name, _normalize_value(getattr(value, field.name)))
            for field in fields(value)
        )
    if isinstance(value, dict):
        return tuple(
            (str(key), _normalize_value(item))
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_normalize_value(item) for item in value)
    if isinstance(value, set):
        normalized = [_normalize_value(item) for item in value]
        return tuple(sorted(normalized, key=repr))
    return value
