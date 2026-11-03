from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import gzip
import hashlib
import io
import threading

import numpy as np
import pandas as pd

from services.analytics.core.details.main_results_csv_builder import MainResultsCsvBuilder
from services.analytics.core.details.timeseries_aggregation import (
    aggregate_timeseries_values,
    is_timeseries_reference,
    resolve_aggregation_spec,
    resolve_timeseries_url,
)

DEFAULT_RESULTS_TABLE_CACHE_BYTES = 256 * 1024 * 1024

DELIMITER = ";"


def aggregated_column_name(column: str, method: str) -> str:
    """Name of the derived column holding ``column`` aggregated with ``method``."""

    return f"{column}[{method}]"


def results_table_key(results_urls: Sequence[str]) -> str:
    """Cache key covering the ordered result URLs; order defines the row order."""

    digest = hashlib.sha256()
    for url in results_urls:
        digest.update(url.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _encode_offsets(offsets: Sequence[int]) -> bytes:
    return gzip.compress(np.asarray(offsets, dtype="<i4").tobytes())


def _decode_offsets(blob: bytes) -> list[int]:
    if not blob:
        return [0]
    return np.frombuffer(gzip.decompress(blob), dtype="<i4").tolist()


@dataclass(frozen=True)
class ResultsTableEntry:
    """A merged results table held as compressed bytes plus its row/source index."""

    blob: bytes
    offsets: bytes
    columns: tuple[str, ...]

    @property
    def size_bytes(self) -> int:
        return len(self.blob) + len(self.offsets)

    @classmethod
    def create(cls, csv_text: str, offsets: Sequence[int]) -> "ResultsTableEntry":
        header = next(csv.reader(io.StringIO(csv_text), delimiter=DELIMITER), [])
        return cls(
            blob=gzip.compress(csv_text.encode("utf-8")),
            offsets=_encode_offsets(offsets),
            columns=tuple(header),
        )


@dataclass
class _Slot:
    entry: ResultsTableEntry
    last_accessed: datetime


class ResultsTableCache:
    """Byte-budgeted sliding-TTL cache of merged results tables.

    Entries grow as derived columns are appended, so eviction is driven by
    compressed size rather than entry count. The surface matches
    ``TimeLimitedCache`` so ``TimeLimitedCacheGarbageCollector`` can drive it
    unchanged.
    """

    def __init__(
        self,
        ttl: timedelta,
        max_bytes: int = DEFAULT_RESULTS_TABLE_CACHE_BYTES,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl < timedelta(0):
            raise ValueError("ttl must not be negative")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._ttl = ttl
        self._max_bytes = max_bytes
        self._clock = clock or _utc_now
        self._slots: dict[str, _Slot] = {}
        self._fill_locks: dict[str, threading.Lock] = {}
        self._size_bytes = 0
        self._lock = threading.Lock()

    @property
    def size_bytes(self) -> int:
        with self._lock:
            return self._size_bytes

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._slots)

    def get(self, entry_id: str) -> ResultsTableEntry | None:
        with self._lock:
            slot = self._slots.get(entry_id)
            if slot is None:
                return None
            slot.last_accessed = self._current_time()
            return slot.entry

    def put(self, entry_id: str, entry: ResultsTableEntry) -> None:
        with self._lock:
            replaced = self._slots.pop(entry_id, None)
            if replaced is not None:
                self._size_bytes -= replaced.entry.size_bytes
            self._slots[entry_id] = _Slot(
                entry=entry, last_accessed=self._current_time()
            )
            self._size_bytes += entry.size_bytes
            self._evict_to_budget(protect=entry_id)

    def fill_lock(self, entry_id: str) -> threading.Lock:
        """Return the per-key lock used to collapse concurrent fills."""

        with self._lock:
            lock = self._fill_locks.get(entry_id)
            if lock is None:
                lock = threading.Lock()
                self._fill_locks[entry_id] = lock
            return lock

    def get_entry_ids(self) -> list[str]:
        with self._lock:
            return list(self._slots.keys())

    def cleanup_if_expired(self, entry_ids: list[str]) -> list[str]:
        removed: list[str] = []
        with self._lock:
            now = self._current_time()
            for entry_id in entry_ids:
                slot = self._slots.get(entry_id)
                if slot is None:
                    continue
                if now - slot.last_accessed >= self._ttl:
                    del self._slots[entry_id]
                    self._size_bytes -= slot.entry.size_bytes
                    removed.append(entry_id)
            for entry_id in list(self._fill_locks):
                if entry_id not in self._slots:
                    del self._fill_locks[entry_id]
        return removed

    def _evict_to_budget(self, protect: str) -> None:
        while self._size_bytes > self._max_bytes:
            candidates = [
                (entry_id, slot)
                for entry_id, slot in self._slots.items()
                if entry_id != protect
            ]
            if not candidates:
                return
            oldest = min(candidates, key=lambda item: item[1].last_accessed)[0]
            slot = self._slots.pop(oldest)
            self._size_bytes -= slot.entry.size_bytes

    def _current_time(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


FetchTimeseriesBatch = Callable[[Sequence[str]], Mapping[str, bytes]]


class ResultsTable:
    """Mutable view over one cached merged results table.

    Time-series values are appended as derived columns named
    ``{column}[{method}]`` so the original reference cells survive untouched and
    a different aggregation method can be added later. Only the columns a request
    actually asks for are ever computed.
    """

    def __init__(
        self,
        *,
        entry: ResultsTableEntry,
        results_urls: Sequence[str],
        fetch_timeseries: FetchTimeseriesBatch,
        on_update: Callable[[ResultsTableEntry], None] | None = None,
        lock: threading.Lock | None = None,
        refresh_entry: Callable[[], ResultsTableEntry | None] | None = None,
    ) -> None:
        self._entry = entry
        self._results_urls = list(results_urls)
        self._fetch_timeseries = fetch_timeseries
        self._on_update = on_update
        self._refresh_entry = refresh_entry
        self._offsets = _decode_offsets(entry.offsets)
        self._lock = lock or threading.Lock()

    @classmethod
    def build(
        cls,
        *,
        results_urls: Sequence[str],
        sources: Sequence[str],
        fetch_timeseries: FetchTimeseriesBatch,
        on_update: Callable[[ResultsTableEntry], None] | None = None,
    ) -> "ResultsTable":
        csv_text, offsets = MainResultsCsvBuilder().build_with_offsets(sources)
        return cls(
            entry=ResultsTableEntry.create(csv_text, offsets),
            results_urls=results_urls,
            fetch_timeseries=fetch_timeseries,
            on_update=on_update,
        )

    @property
    def columns(self) -> tuple[str, ...]:
        return self._entry.columns

    def snapshot(self) -> ResultsTableEntry:
        return self._entry

    @property
    def row_count(self) -> int:
        return self._offsets[-1] if self._offsets else 0

    def csv_text(self) -> str:
        return gzip.decompress(self._entry.blob).decode("utf-8")

    def entry_size_bytes(self) -> int:
        return self._entry.size_bytes

    def materialize(self, requests: Mapping[str, str]) -> dict[str, str]:
        """Ensure each requested column is numeric and report the column to use.

        Scalar columns are already usable. A time-series column is satisfied by a
        derived column, which is computed only when it is not cached yet.
        """

        timeseries = self._classify(list(requests))
        pending = [
            (base, method, aggregated_column_name(base, method))
            for base, method in requests.items()
            if timeseries[base]
            and aggregated_column_name(base, method) not in self._entry.columns
        ]
        if pending:
            self._append_derived_columns(pending)
        return {
            base: (
                aggregated_column_name(base, method)
                if timeseries[base]
                else base
            )
            for base, method in requests.items()
        }

    def _classify(self, columns: Sequence[str]) -> dict[str, bool]:
        """Report, per column, whether any cell holds a time-series reference."""

        found = {column: False for column in columns}
        with self._open_reader() as reader:
            index_of = self._header_index(reader, columns)
            for row in reader:
                for column in columns:
                    if not found[column] and is_timeseries_reference(
                        row[index_of[column]]
                    ):
                        found[column] = True
        return found

    def _append_derived_columns(
        self, pending: Sequence[tuple[str, str, str]]
    ) -> None:
        with self._lock:
            latest = self._refresh_entry() if self._refresh_entry else None
            if latest is not None:
                self._entry = latest
                self._offsets = _decode_offsets(latest.offsets)
            if all(derived in self._entry.columns for _b, _m, derived in pending):
                return
            self._entry = self._build_derived_entry(pending)
            if self._on_update is not None:
                self._on_update(self._entry)

    def _build_derived_entry(
        self, pending: Sequence[tuple[str, str, str]]
    ) -> ResultsTableEntry:
        references: dict[tuple[str, str], list[int]] = {}

        with self._open_reader() as reader:
            index_of = self._header_index(reader, [base for base, _m, _d in pending])
            for row_number, row in enumerate(reader):
                source_url = self._source_url_for_row(row_number)
                for base, _method, _derived in pending:
                    cell = (row[index_of[base]] or "").strip()
                    if not is_timeseries_reference(cell):
                        raise ValueError(
                            f"Column {base!r} mixes time-series references with "
                            f"literal values at merged row {row_number}; it cannot "
                            "be aggregated as a single column."
                        )
                    url = resolve_timeseries_url(source_url=source_url, cell=cell)
                    references.setdefault((url, base), []).append(row_number)

        contents = self._fetch_timeseries(
            list(dict.fromkeys(url for url, _base in references))
        )
        aggregates = self._aggregate_all(
            contents=contents,
            references=references,
            pending=pending,
        )
        return self._write_back(pending, aggregates)

    def _aggregate_all(
        self,
        *,
        contents: Mapping[str, bytes],
        references: Mapping[tuple[str, str], Sequence[int]],
        pending: Sequence[tuple[str, str, str]],
    ) -> dict[str, list[float | None]]:
        specs = {
            base: resolve_aggregation_spec(method) for base, method, _d in pending
        }
        aggregates: dict[str, list[float | None]] = {
            base: [None] * self.row_count for base, _m, _d in pending
        }

        for (url, base), row_indexes in references.items():
            content = contents.get(url)
            if content is None:
                continue
            frame = pd.read_csv(
                io.StringIO(content.decode("utf-8")),
                delimiter=DELIMITER,
                usecols=[base],
            )
            value = aggregate_timeseries_values(
                dataframe=frame,
                value_column=base,
                aggregation_spec=specs[base],
            )
            for row_index in row_indexes:
                aggregates[base][row_index] = value
        return aggregates

    def _write_back(
        self,
        pending: Sequence[tuple[str, str, str]],
        aggregates: Mapping[str, Sequence[float | None]],
    ) -> ResultsTableEntry:
        output = io.StringIO()
        writer = csv.writer(output, delimiter=DELIMITER, lineterminator="\n")
        writer.writerow(
            list(self._entry.columns) + [derived for _b, _m, derived in pending]
        )

        position = 0
        with self._open_reader() as reader:
            next(reader, None)
            for row in reader:
                writer.writerow(
                    row
                    + [
                        _format_optional(aggregates[base][position])
                        for base, _method, _derived in pending
                    ]
                )
                position += 1

        return ResultsTableEntry.create(output.getvalue(), self._offsets)

    @contextmanager
    def _open_reader(self):
        stream = io.StringIO(self.csv_text())
        try:
            yield csv.reader(stream, delimiter=DELIMITER)
        finally:
            stream.close()

    def _header_index(self, reader, columns: Sequence[str]) -> dict[str, int]:
        header = next(reader, None)
        if header is None:
            raise ValueError("Results table is empty")
        index_of = {name: index for index, name in enumerate(header)}
        missing = [column for column in columns if column not in index_of]
        if missing:
            raise ValueError(f"Missing required columns in CSV: {missing}")
        return index_of

    def _source_url_for_row(self, row_number: int) -> str:
        source_index = bisect_right(self._offsets, row_number) - 1
        if source_index < 0 or source_index >= len(self._results_urls):
            raise ValueError(
                f"Merged row {row_number} has no owning source; the cached table "
                "offsets are inconsistent with the requested result URLs."
            )
        return self._results_urls[source_index]


def _format_optional(value: float | None) -> str:
    return "" if value is None else repr(float(value))