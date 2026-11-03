from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import threading

from services.analytics.core.details.time_limited_cache import TimeLimitedCache
from services.analytics.core.model import MultiDataSeries


@dataclass(frozen=True)
class MultiDataSeriesCacheKey:
    raw_series_ids: tuple[str, ...]


@dataclass(frozen=True)
class MultiDataSeriesCacheEntry:
    """One cache entry stored in the TTL cache."""

    entry_id: str
    key: MultiDataSeriesCacheKey
    multi_data_series: MultiDataSeries


class MultiDataSeriesCache(TimeLimitedCache):
    """Time-limited in-memory cache for MultiDataSeries objects keyed by raw series ids."""

    def __init__(self, ttl: timedelta) -> None:
        super().__init__(ttl)
        self._id_to_key: dict[str, MultiDataSeriesCacheKey] = {}
        self._key_to_id: dict[MultiDataSeriesCacheKey, str] = {}
        self._mapping_lock = threading.Lock()
        self._in_progress_key_to_id: dict[MultiDataSeriesCacheKey, str] = {}
        self._invalid_ids = set()

    def put_in_progress_id(self, raw_series_ids: list[str], in_progress_id: str) -> None:
        key = self.build_key(raw_series_ids)
        with self._mapping_lock:
            if key not in self._in_progress_key_to_id:
                self._in_progress_key_to_id[key] = in_progress_id

    def put(self, entry_id: str, entry: object) -> None:
        """Store or replace a cache entry by id."""

        if not isinstance(entry, MultiDataSeriesCacheEntry):
            raise TypeError("entry must be a MultiDataSeriesCacheEntry")

        with self._mapping_lock:
            existing_id = self._key_to_id.get(entry.key)
            stored_entry = entry
            stored_entry_id = entry_id
            if existing_id is not None and existing_id != entry_id:
                stored_entry_id = existing_id
                stored_entry = MultiDataSeriesCacheEntry(
                    entry_id=existing_id,
                    key=entry.key,
                    multi_data_series=entry.multi_data_series,
                )
            self._key_to_id[stored_entry.key] = stored_entry_id
            self._id_to_key[stored_entry_id] = stored_entry.key
            if stored_entry_id != entry_id:
                self._id_to_key.pop(entry_id, None)
            if stored_entry.key in self._in_progress_key_to_id:
                del self._in_progress_key_to_id[stored_entry.key]
            super().put(stored_entry_id, stored_entry)

    def get(self, entry_id: str) -> MultiDataSeries | None:
        """Return a cached multi data series by cache-entry id."""

        entry = super().get(entry_id)
        if isinstance(entry, MultiDataSeriesCacheEntry):
            return entry.multi_data_series
        return None

    def get_id(self, raw_series_ids: list[str]) -> str | None:
        """Return the cache-entry id for the given logical key, if present."""

        key = self.build_key(raw_series_ids)
        with self._mapping_lock:
            ready_id = self._key_to_id.get(key)
            if ready_id:
                return ready_id
            return self._in_progress_key_to_id.get(key)

    def get_by_key(self, raw_series_ids: list[str]) -> MultiDataSeries | None:
        """Return a cached multi data series by logical key."""

        key = self.build_key(raw_series_ids)
        with self._mapping_lock:
            entry_id = self._key_to_id.get(key)
        if entry_id is None:
            return None

        entry = super().get(entry_id)
        if isinstance(entry, MultiDataSeriesCacheEntry):
            return entry.multi_data_series
        if entry is None:
            with self._mapping_lock:
                current_entry_id = self._key_to_id.get(key)
                if current_entry_id == entry_id:
                    self._remove_mappings_for_entry_id(entry_id)
        return None

    def get_key(self, entry_id: str) -> MultiDataSeriesCacheKey | None:
        """Return the logical key associated with a cache-entry id."""

        with self._mapping_lock:
            return self._id_to_key.get(entry_id)

    def remove_by_id(self, entry_id: str) -> None:
        """Remove a cached multi data series and all related mappings by cache-entry id."""

        with self._mapping_lock:
            with self._lock:
                self._entries.pop(entry_id, None)
            self._remove_mappings_for_entry_id(entry_id)

    def cleanup_if_expired(self, entry_ids: list[str]) -> list[str]:
        """Remove expired entries and clean related key/id mappings."""

        with self._mapping_lock:
            expired_entry_ids = super().cleanup_if_expired(entry_ids)
            for entry_id in expired_entry_ids:
                self._remove_mappings_for_entry_id(entry_id)
            return expired_entry_ids

    def get_entry_ids(self) -> list[str]:
        """Return a snapshot of the currently stored cache-entry ids."""

        return super().get_entry_ids()

    def build_key(self, raw_series_ids: list[str]) -> MultiDataSeriesCacheKey:
        return MultiDataSeriesCacheKey(raw_series_ids=tuple(raw_series_ids))

    def mark_invalid(self, series_id):
        self._invalid_ids.add(series_id)

    def is_invalid(self, series_id):
        return series_id in self._invalid_ids

    def _remove_mappings_for_entry_id(self, entry_id: str) -> None:
        key = self._id_to_key.pop(entry_id, None)
        if key is None:
            return
        mapped_entry_id = self._key_to_id.get(key)
        if mapped_entry_id == entry_id:
            self._key_to_id.pop(key, None)
