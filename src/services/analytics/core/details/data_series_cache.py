from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import threading

from services.analytics.core.details.time_limited_cache import TimeLimitedCache
from services.analytics.core.model import DataSeries


@dataclass(frozen=True)
class DataSeriesRequest:
    series_id: str
    job_id: str
    x_param: str
    y_param: str
    constants: list[tuple[str, str]]
    statistic: str


@dataclass(frozen=True)
class DataSeriesCacheKey:
    job_id: str
    x_param: str
    y_param: str
    constants: tuple[tuple[str, str], ...]
    statistic: str


@dataclass(frozen=True)
class DataSeriesCacheEntry:
    """One cache entry stored in the TTL cache."""

    entry_id: str
    key: DataSeriesCacheKey
    data_series: DataSeries


class DataSeriesCache(TimeLimitedCache):
    """Time-limited in-memory cache for DataSeries objects keyed by evaluation parameters."""

    def __init__(self, ttl: timedelta) -> None:
        super().__init__(ttl)
        self._id_to_key: dict[str, DataSeriesCacheKey] = {}
        self._key_to_id: dict[DataSeriesCacheKey, str] = {}
        self._mapping_lock = threading.Lock()
        self._in_progress_key_to_id: dict[DataSeriesCacheKey, str] = {}

    def put_in_progress_id(
        self,
        job_id: str,
        x_param: str,
        y_param: str,
        constants: list[tuple[str, str]],
        statistic: str,
        in_progress_id: str
    ):
        key = self.build_key(job_id, x_param, y_param, constants, statistic)
        with self._mapping_lock:
            if key not in self._in_progress_key_to_id:
                self._in_progress_key_to_id[key] = in_progress_id

    def put(self, entry_id: str, entry: object) -> None:
        """Store or replace a cache entry by id."""

        if not isinstance(entry, DataSeriesCacheEntry):
            raise TypeError("entry must be a DataSeriesCacheEntry")

        with self._mapping_lock:
            existing_id = self._key_to_id.get(entry.key)
            stored_entry = entry
            stored_entry_id = entry_id
            if existing_id is not None and existing_id != entry_id:
                stored_entry_id = existing_id
                stored_entry = DataSeriesCacheEntry(
                    entry_id=existing_id,
                    key=entry.key,
                    data_series=entry.data_series,
                )
            self._key_to_id[stored_entry.key] = stored_entry_id
            self._id_to_key[stored_entry_id] = stored_entry.key
            if stored_entry_id != entry_id:
                self._id_to_key.pop(entry_id, None)
            if stored_entry.key in self._in_progress_key_to_id:
                del self._in_progress_key_to_id[stored_entry.key]
            super().put(stored_entry_id, stored_entry)

    def get(self, entry_id: str) -> DataSeries | None:
        """Return a cached data series by cache-entry id."""

        entry = super().get(entry_id)
        if isinstance(entry, DataSeriesCacheEntry):
            return entry.data_series
        return None

    def get_id(
        self,
        job_id: str,
        x_param: str,
        y_param: str,
        constants: list[tuple[str, str]],
        statistic: str,
    ) -> str | None:
        """Return the cache-entry id for the given logical key, if present."""

        key = self.build_key(job_id, x_param, y_param, constants, statistic)
        with self._mapping_lock:
            ready_id = self._key_to_id.get(key)
            if ready_id:
                return ready_id
            return self._in_progress_key_to_id.get(key)

    def has_id(self, series_id):
        if series_id in self._id_to_key:
            return True
        for key, in_progress_id in self._in_progress_key_to_id.items():
            if in_progress_id == series_id:
                return True
        return False

    def get_by_key(
        self,
        job_id: str,
        x_param: str,
        y_param: str,
        constants: list[tuple[str, str]],
        statistic: str,
    ) -> DataSeries | None:
        """Return a cached data series by logical key."""

        key = self.build_key(job_id, x_param, y_param, constants, statistic)
        with self._mapping_lock:
            entry_id = self._key_to_id.get(key)
        if entry_id is None:
            return None

        entry = super().get(entry_id)
        if isinstance(entry, DataSeriesCacheEntry):
            return entry.data_series
        if entry is None:
            with self._mapping_lock:
                current_entry_id = self._key_to_id.get(key)
                if current_entry_id == entry_id:
                    self._remove_mappings_for_entry_id(entry_id)
        return None

    def get_key(self, entry_id: str) -> DataSeriesCacheKey | None:
        """Return the logical key associated with a cache-entry id."""

        with self._mapping_lock:
            return self._id_to_key.get(entry_id)

    def remove_by_id(self, entry_id: str) -> None:
        """Remove a cached data series and all related mappings by cache-entry id."""

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

    def build_key(
        self,
        job_id: str,
        x_param: str,
        y_param: str,
        constants: list[tuple[str, str]],
        statistic: str,
    ) -> DataSeriesCacheKey:
        return DataSeriesCacheKey(
            job_id=job_id,
            x_param=x_param,
            y_param=y_param,
            constants=self._normalize_constants(constants),
            statistic=statistic,
        )

    def _normalize_constants(
        self,
        constants: list[tuple[str, str]],
    ) -> tuple[tuple[str, str], ...]:
        return tuple(constants)

    def _remove_mappings_for_entry_id(self, entry_id: str) -> None:
        key = self._id_to_key.pop(entry_id, None)
        if key is None:
            return
        mapped_entry_id = self._key_to_id.get(key)
        if mapped_entry_id == entry_id:
            self._key_to_id.pop(key, None)

