from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.analytics.core.details.main_results_csv_builder import (
    MainResultsCsvBuilder,
)
from services.analytics.core.details.results_table_cache import (
    ResultsTable,
    ResultsTableCache,
    ResultsTableEntry,
    aggregated_column_name,
    results_table_key,
)

HOST = "https://host"


class _Fixture:
    """Builds a merged table over fake sources and records time-series fetches."""

    def __init__(
        self,
        sources: dict[str, str],
        contents: dict[str, bytes] | None = None,
        results_urls: list[str] | None = None,
    ) -> None:
        self.urls = list(
            results_urls if results_urls is not None else sources
        )
        self.calls: list[list[str]] = []
        self.contents = dict(contents or {})
        self.table = ResultsTable.build(
            results_urls=self.urls,
            sources=list(sources.values()),
            fetch_timeseries=self._fetch,
        )

    def _fetch(self, urls):
        self.calls.append(list(urls))
        return {url: self.contents[url] for url in urls}


def _fixed_clock(start: datetime):
    state = {"now": start}

    def clock() -> datetime:
        return state["now"]

    def advance(delta: timedelta) -> None:
        state["now"] = state["now"] + delta

    clock.advance = advance  # type: ignore[attr-defined]
    return clock


def _queue(values: list[float], column: str = "Queue") -> bytes:
    body = "".join(f"{index};{value}\n" for index, value in enumerate(values))
    return f"time;{column}\n{body}".encode()


# --- MainResultsCsvBuilder.build_with_offsets -------------------------------


def test_build_with_offsets_reports_each_source_start_row() -> None:
    text, offsets = MainResultsCsvBuilder().build_with_offsets(
        ["A;B\n1;2\n3;4\n", "A;B\n5;6\n"]
    )

    assert text == "A;B\n1;2\n3;4\n5;6\n"
    assert offsets == [0, 2, 3]


def test_build_with_offsets_repeats_offset_for_empty_sources() -> None:
    text, offsets = MainResultsCsvBuilder().build_with_offsets(
        ["A;B\n1;2\n", "", "   \n", "A;B\n5;6\n"]
    )

    assert text == "A;B\n1;2\n5;6\n"
    assert offsets == [0, 1, 1, 1, 2]


def test_build_with_offsets_returns_one_more_offset_than_sources() -> None:
    _text, offsets = MainResultsCsvBuilder().build_with_offsets(
        ["A;B\n1;2\n", "A;B\n3;4\n", "A;B\n5;6\n"]
    )

    assert len(offsets) == 4
    assert offsets[-1] == 3


def test_build_still_concatenates_without_offsets() -> None:
    assert MainResultsCsvBuilder().build(["A;B\n1;2\n", "A;B\n3;4\n"]) == (
        "A;B\n1;2\n3;4\n"
    )


def test_build_with_offsets_rejects_mismatched_headers() -> None:
    with pytest.raises(ValueError, match="CSV header mismatch"):
        MainResultsCsvBuilder().build_with_offsets(["A;B\n1;2\n", "A;C\n3;4\n"])


# --- ResultsTableCache ------------------------------------------------------


def test_cache_returns_none_for_unknown_entry() -> None:
    assert ResultsTableCache(timedelta(minutes=1)).get("missing") is None


def test_cache_expires_entries_after_ttl() -> None:
    clock = _fixed_clock(datetime(2026, 1, 1, tzinfo=UTC))
    cache = ResultsTableCache(timedelta(minutes=30), clock=clock)
    cache.put("k", ResultsTableEntry.create("A;B\n1;2\n", [0, 1]))

    clock.advance(timedelta(minutes=31))

    assert cache.cleanup_if_expired(cache.get_entry_ids()) == ["k"]
    assert cache.get("k") is None
    assert cache.size_bytes == 0


def test_cache_ttl_refreshes_on_read() -> None:
    clock = _fixed_clock(datetime(2026, 1, 1, tzinfo=UTC))
    cache = ResultsTableCache(timedelta(minutes=30), clock=clock)
    cache.put("k", ResultsTableEntry.create("A;B\n1;2\n", [0, 1]))

    clock.advance(timedelta(minutes=25))
    assert cache.get("k") is not None
    clock.advance(timedelta(minutes=25))

    assert cache.get("k") is not None


def test_cache_evicts_least_recently_used_to_stay_within_budget() -> None:
    clock = _fixed_clock(datetime(2026, 1, 1, tzinfo=UTC))
    per_entry = ResultsTableEntry.create("A;B\n1;2\n", [0, 1]).size_bytes
    cache = ResultsTableCache(
        timedelta(minutes=30), max_bytes=per_entry * 2, clock=clock
    )

    cache.put("first", ResultsTableEntry.create("A;B\n1;2\n", [0, 1]))
    clock.advance(timedelta(seconds=1))
    cache.put("second", ResultsTableEntry.create("A;B\n3;4\n", [0, 1]))
    clock.advance(timedelta(seconds=1))
    cache.get("first")
    clock.advance(timedelta(seconds=1))
    cache.put("third", ResultsTableEntry.create("A;B\n5;6\n", [0, 1]))

    assert cache.entry_count == 2
    assert cache.size_bytes <= per_entry * 2
    assert cache.get("first") is not None
    assert cache.get("third") is not None
    assert cache.get("second") is None


def test_cache_keeps_an_oversized_entry_it_just_stored() -> None:
    cache = ResultsTableCache(timedelta(minutes=30), max_bytes=1)

    cache.put("k", ResultsTableEntry.create("A;B\n1;2\n", [0, 1]))

    assert cache.get("k") is not None


def test_cache_size_tracks_replacements() -> None:
    cache = ResultsTableCache(timedelta(minutes=30))
    entry = ResultsTableEntry.create("A;B\n1;2\n", [0, 1])

    cache.put("k", entry)
    cache.put("k", entry)

    assert cache.size_bytes == entry.size_bytes
    assert cache.entry_count == 1


def test_fill_lock_is_shared_per_key_and_distinct_across_keys() -> None:
    cache = ResultsTableCache(timedelta(minutes=1))

    assert cache.fill_lock("a") is cache.fill_lock("a")
    assert cache.fill_lock("a") is not cache.fill_lock("b")


def test_fill_locks_survive_cleanup_for_keys_still_cached() -> None:
    clock = _fixed_clock(datetime(2026, 1, 1, tzinfo=UTC))
    cache = ResultsTableCache(timedelta(minutes=1), clock=clock)
    lock = cache.fill_lock("kept")
    cache.put("kept", ResultsTableEntry.create("A;B\n1;2\n", [0, 1]))

    cache.cleanup_if_expired(cache.get_entry_ids())

    assert cache.fill_lock("kept") is lock


def test_cache_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError):
        ResultsTableCache(timedelta(seconds=-1))
    with pytest.raises(ValueError):
        ResultsTableCache(timedelta(minutes=1), max_bytes=0)


def test_cache_rejects_naive_clock() -> None:
    cache = ResultsTableCache(
        timedelta(minutes=1), clock=lambda: datetime(2026, 1, 1)
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        cache.put("k", ResultsTableEntry.create("A;B\n1;2\n", [0, 1]))


# --- keys and naming -------------------------------------------------------


def test_results_table_key_is_order_sensitive() -> None:
    assert results_table_key(["a", "b"]) != results_table_key(["b", "a"])


def test_results_table_key_is_stable_for_equal_urls() -> None:
    assert results_table_key(["a", "b"]) == results_table_key(["a", "b"])


def test_results_table_key_avoids_boundary_collisions() -> None:
    assert results_table_key(["ab", "c"]) != results_table_key(["a", "bc"])


def test_aggregated_column_name_embeds_the_method() -> None:
    assert aggregated_column_name("Total queue", "p95") == "Total queue[p95]"


# --- scalar columns --------------------------------------------------------


def test_scalar_columns_are_used_without_deriving_anything() -> None:
    fixture = _Fixture({f"{HOST}/results.csv.zip": "A;B\n0.1;5\n0.9;7\n"})

    resolved = fixture.table.materialize({"B": "max"})

    assert resolved == {"B": "B"}
    assert fixture.calls == []
    assert fixture.table.columns == ("A", "B")


def test_missing_column_is_reported_by_name() -> None:
    fixture = _Fixture({f"{HOST}/results.csv.zip": "A;B\n0.1;5\n"})

    with pytest.raises(ValueError, match="Missing required columns in CSV"):
        fixture.table.materialize({"missing": "max"})


# --- lazy derived columns --------------------------------------------------


def test_time_series_column_is_derived_once_and_then_reused() -> None:
    fixture = _Fixture(
        {f"{HOST}/config/results.csv.zip": "A;Queue\n0.1;q0.csv\n0.9;q1.csv\n"},
        contents={
            f"{HOST}/config/q0.csv.zip": _queue([1, 3]),
            f"{HOST}/config/q1.csv.zip": _queue([8, 9]),
        },
    )

    first = fixture.table.materialize({"Queue": "max"})
    second = fixture.table.materialize({"Queue": "max"})

    assert first == {"Queue": "Queue[max]"}
    assert second == {"Queue": "Queue[max]"}
    assert len(fixture.calls) == 1
    assert "Queue[max]" in fixture.table.columns


def test_derived_column_preserves_the_original_reference() -> None:
    fixture = _Fixture(
        {f"{HOST}/config/results.csv.zip": "A;Queue\n0.1;q0.csv\n"},
        contents={f"{HOST}/config/q0.csv.zip": _queue([1, 3])},
    )

    fixture.table.materialize({"Queue": "max"})

    text = fixture.table.csv_text()
    assert "q0.csv" in text
    assert "Queue" in fixture.table.columns
    assert fixture.table.columns == ("A", "Queue", "Queue[max]")


def test_derived_values_land_on_the_row_that_referenced_them() -> None:
    fixture = _Fixture(
        {
            f"{HOST}/one/results.csv.zip": "A;Queue\n0.1;q0.csv\n0.5;q1.csv\n",
            f"{HOST}/two/results.csv.zip": "A;Queue\n0.9;q2.csv\n",
        },
        contents={
            f"{HOST}/one/q0.csv.zip": _queue([1]),
            f"{HOST}/one/q1.csv.zip": _queue([5]),
            f"{HOST}/two/q2.csv.zip": _queue([9]),
        },
    )

    fixture.table.materialize({"Queue": "max"})

    lines = fixture.table.csv_text().splitlines()
    assert lines == [
        "A;Queue;Queue[max]",
        "0.1;q0.csv;1.0",
        "0.5;q1.csv;5.0",
        "0.9;q2.csv;9.0",
    ]


def test_each_reference_resolves_against_its_own_source_directory() -> None:
    fixture = _Fixture(
        {
            f"{HOST}/one/results.csv.zip": "A;Queue\n0.1;q.csv\n",
            f"{HOST}/two/results.csv.zip": "A;Queue\n0.9;q.csv\n",
        },
        contents={
            f"{HOST}/one/q.csv.zip": _queue([2]),
            f"{HOST}/two/q.csv.zip": _queue([2]),
        },
    )

    fixture.table.materialize({"Queue": "max"})

    assert sorted(fixture.calls[0]) == [
        f"{HOST}/one/q.csv.zip",
        f"{HOST}/two/q.csv.zip",
    ]


def test_repeated_reference_downloads_the_series_once() -> None:
    fixture = _Fixture(
        {f"{HOST}/config/results.csv.zip": "A;Queue\n0.1;q.csv\n0.2;q.csv\n0.3;q.csv\n"},
        contents={f"{HOST}/config/q.csv.zip": _queue([1, 2])},
    )

    fixture.table.materialize({"Queue": "max"})

    assert fixture.calls == [[f"{HOST}/config/q.csv.zip"]]


def test_changing_the_method_adds_a_second_derived_column() -> None:
    fixture = _Fixture(
        {f"{HOST}/config/results.csv.zip": "A;Queue\n0.1;q.csv\n"},
        contents={f"{HOST}/config/q.csv.zip": _queue([1, 2, 3, 4])},
    )

    assert fixture.table.materialize({"Queue": "max"}) == {"Queue": "Queue[max]"}
    assert fixture.table.materialize({"Queue": "p95"}) == {"Queue": "Queue[p95]"}

    header, row = fixture.table.csv_text().splitlines()
    assert header == "A;Queue;Queue[max];Queue[p95]"
    assert row.startswith("0.1;q.csv;")
    assert len(fixture.calls) == 2


def test_multiple_columns_are_derived_in_one_pass() -> None:
    fixture = _Fixture(
        {f"{HOST}/config/results.csv.zip": "A;Queue;Load\n0.1;q.csv;l.csv\n"},
        contents={
            f"{HOST}/config/q.csv.zip": _queue([1, 2]),
            f"{HOST}/config/l.csv.zip": _queue([4, 6], column="Load"),
        },
    )

    resolved = fixture.table.materialize({"Queue": "max", "Load": "min"})

    assert resolved == {"Queue": "Queue[max]", "Load": "Load[min]"}
    assert len(fixture.calls) == 1
    header, row = fixture.table.csv_text().splitlines()
    assert header == "A;Queue;Load;Queue[max];Load[min]"
    assert row == "0.1;q.csv;l.csv;2.0;4.0"


def test_each_series_is_read_with_only_the_column_it_serves() -> None:
    fixture = _Fixture(
        {f"{HOST}/config/results.csv.zip": "A;Queue;Load\n0.1;q.csv;l.csv\n"},
        contents={
            f"{HOST}/config/q.csv.zip": _queue([1, 2]),
            f"{HOST}/config/l.csv.zip": _queue([4, 6], column="Load"),
        },
    )

    fixture.table.materialize({"Queue": "max", "Load": "min"})

    # A cross-serving read would raise because neither file holds both columns.
    assert fixture.table.csv_text().splitlines()[1].endswith(";2.0;4.0")


def test_mixed_reference_and_literal_column_is_rejected() -> None:
    fixture = _Fixture(
        {f"{HOST}/config/results.csv.zip": "A;Queue\n0.1;q.csv\n0.2;5\n"},
        contents={f"{HOST}/config/q.csv.zip": _queue([1, 2])},
    )

    with pytest.raises(ValueError, match="mixes time-series references"):
        fixture.table.materialize({"Queue": "max"})


def test_unsupported_aggregation_method_is_rejected() -> None:
    fixture = _Fixture(
        {f"{HOST}/config/results.csv.zip": "A;Queue\n0.1;q.csv\n"},
        contents={f"{HOST}/config/q.csv.zip": _queue([1, 2])},
    )

    with pytest.raises(ValueError, match="Unsupported aggregation method"):
        fixture.table.materialize({"Queue": "nonsense"})


def test_derived_entry_is_published_through_on_update() -> None:
    published: list[ResultsTableEntry] = []
    table = ResultsTable(
        entry=ResultsTableEntry.create("A;Queue\n0.1;q.csv\n", [0, 1]),
        results_urls=[f"{HOST}/config/results.csv.zip"],
        fetch_timeseries=lambda urls: {
            url: _queue([1, 2]) for url in urls
        },
        on_update=published.append,
    )

    table.materialize({"Queue": "max"})

    assert len(published) == 1
    assert "Queue[max]" in published[0].columns


def test_entry_round_trips_through_compression() -> None:
    entry = ResultsTableEntry.create("A;B\n0.1;5\n", [0, 1])

    restored = ResultsTable(
        entry=entry, results_urls=["r"], fetch_timeseries=lambda urls: {}
    )

    assert restored.row_count == 1
    assert restored.csv_text() == "A;B\n0.1;5\n"
    assert restored.columns == ("A", "B")