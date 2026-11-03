from __future__ import annotations

import time

from services.analytics.core.details.data_series_cache import DataSeriesCache
from services.analytics.core.details.multi_data_series_cache import (
    MultiDataSeriesCache,
    MultiDataSeriesCacheEntry,
)
from services.analytics.core.model import DataSeries, MultiDataSeries

_POLL_INTERVAL_SECONDS = 1.0


class MultiDataSeriesCacheEntryBuilder:
    """Build multi-series cache entries from existing raw data series cache entries."""

    def __init__(
        self,
        data_series_cache: DataSeriesCache,
        multi_data_series_cache: MultiDataSeriesCache,
    ) -> None:
        self._data_series_cache = data_series_cache
        self._multi_data_series_cache = multi_data_series_cache

    def build(self, entry_id: str, raw_series_ids: list[str]) -> None:
        try:
            if not raw_series_ids:
                raise ValueError("raw_series_ids must not be empty")

            data_series_list = self._wait_for_data_series(raw_series_ids)
            reference = data_series_list[0]
            for candidate in data_series_list[1:]:
                if candidate.x_name != reference.x_name:
                    raise ValueError("DataSeries x_name values differ")
                if candidate.x_values != reference.x_values:
                    raise ValueError("DataSeries x_values differ")

            key = self._multi_data_series_cache.build_key(raw_series_ids)
            self._multi_data_series_cache.put(
                entry_id,
                MultiDataSeriesCacheEntry(
                    entry_id=entry_id,
                    key=key,
                    multi_data_series=MultiDataSeries(series=data_series_list),
                ),
            )
        except Exception as e:
            self._multi_data_series_cache.mark_invalid(entry_id)

    def _wait_for_data_series(self, raw_series_ids: list[str]) -> list[DataSeries]:
        watchdog = 900
        while watchdog > 0:
            watchdog -= 1
            data_series_list: list[DataSeries] = []
            for raw_series_id in raw_series_ids:
                data_series = self._data_series_cache.get(raw_series_id)
                if data_series is None:
                    break
                data_series_list.append(data_series)
            if len(data_series_list) == len(raw_series_ids):
                return data_series_list
            time.sleep(_POLL_INTERVAL_SECONDS)

        raise RuntimeError("Cannot build multi-series!")
