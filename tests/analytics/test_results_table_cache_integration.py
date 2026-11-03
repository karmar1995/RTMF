from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from services.analytics.core.details.analytics_service_controller import (
    AnalyticsServiceController,
)

HOST = "https://host"


def _results_and_series() -> dict[str, str]:
    return {
        f"{HOST}/config/results.csv.zip": (
            "A;Queue;Load\n"
            "0.1;q0.csv;l0.csv\n"
            "0.1;q1.csv;l1.csv\n"
            "0.9;q2.csv;l2.csv\n"
            "0.9;q3.csv;l3.csv\n"
        ),
        f"{HOST}/config/q0.csv.zip": "time;Queue\n0;0.5\n1;1.0\n",
        f"{HOST}/config/q1.csv.zip": "time;Queue\n0;0.6\n1;1.1\n",
        f"{HOST}/config/q2.csv.zip": "time;Queue\n0;1.0\n1;3.0\n",
        f"{HOST}/config/q3.csv.zip": "time;Queue\n0;1.0\n1;2.9\n",
        f"{HOST}/config/l0.csv.zip": "time;Load\n0;10\n1;15\n",
        f"{HOST}/config/l1.csv.zip": "time;Load\n0;20\n1;25\n",
        f"{HOST}/config/l2.csv.zip": "time;Load\n0;30\n1;35\n",
        f"{HOST}/config/l3.csv.zip": "time;Load\n0;40\n1;45\n",
    }


RESULTS_URL = f"{HOST}/config/results.csv.zip"


def _analyze(controller, **overrides):
    kwargs = {
        "problem": {"names": ["A"]},
        "output_column": "Queue",
        "threshold": 2.0,
        "direction": "greater",
        "results_urls": [RESULTS_URL],
        "aggregation": "max",
    }
    kwargs.update(overrides)
    return controller.analyze_monte_carlo_filtering(**kwargs)


def test_scalar_second_request_downloads_nothing(fake_results_repository) -> None:
    files = {
        f"{HOST}/one/results.csv.zip": "repetition;A;output\n0;0.1;1.0\n1;0.1;1.2\n",
        f"{HOST}/two/results.csv.zip": "repetition;A;output\n0;0.9;3.0\n1;0.9;2.8\n",
    }
    repository = fake_results_repository(files)
    controller = AnalyticsServiceController(results_repository=repository)
    urls = list(files)

    first = controller.analyze_monte_carlo_filtering(
        problem={"names": ["A"]},
        output_column="output",
        threshold=2.0,
        direction="greater",
        results_urls=urls,
        run_output_columns=["output"],
    )
    downloads_after_first = list(repository.downloads)
    second = controller.analyze_monte_carlo_filtering(
        problem={"names": ["A"]},
        output_column="output",
        threshold=2.0,
        direction="greater",
        results_urls=urls,
        run_output_columns=["output"],
    )

    assert len(first.runs) == len(second.runs) == 4
    assert [run.outputs["output"] for run in first.runs] == [
        run.outputs["output"] for run in second.runs
    ]
    assert repository.downloads == downloads_after_first
    assert sorted(set(downloads_after_first)) == sorted(urls)


def test_changing_the_threshold_reuses_the_cached_table(
    fake_results_repository,
) -> None:
    repository = fake_results_repository(_results_and_series())
    controller = AnalyticsServiceController(results_repository=repository)

    first = _analyze(controller, threshold=2.0)
    after_first = list(repository.downloads)
    second = _analyze(controller, threshold=2.5)

    assert first.behavioural_count == 2
    assert second.behavioural_count == 2
    assert repository.downloads == after_first


def test_repeated_request_does_not_refetch_timeseries(
    fake_results_repository,
) -> None:
    repository = fake_results_repository(_results_and_series())
    controller = AnalyticsServiceController(results_repository=repository)

    _analyze(controller)
    after_first = list(repository.downloads)
    _analyze(controller)

    assert repository.downloads == after_first


def test_derived_columns_are_added_lazily_and_cached(
    fake_results_repository,
) -> None:
    repository = fake_results_repository(_results_and_series())
    controller = AnalyticsServiceController(results_repository=repository)

    first = _analyze(
        controller,
        output_aggregations={"Load": "min"},
        run_output_columns=["Queue", "Load"],
    )
    after_first = list(repository.downloads)
    second = _analyze(
        controller,
        output_aggregations={"Load": "min"},
        run_output_columns=["Queue", "Load"],
    )

    assert [run.outputs["Load"] for run in first.runs] == [
        pytest.approx(10.0),
        pytest.approx(20.0),
        pytest.approx(30.0),
        pytest.approx(40.0),
    ]
    assert [run.outputs["Load"] for run in second.runs] == [
        run.outputs["Load"] for run in first.runs
    ]
    # The series for both columns were fetched once, on the first request only.
    assert len(after_first) == 9
    assert repository.downloads == after_first


def test_switching_the_aggregation_method_refetches_only_the_series(
    fake_results_repository,
) -> None:
    repository = fake_results_repository(_results_and_series())
    controller = AnalyticsServiceController(results_repository=repository)

    _analyze(controller, run_output_columns=["Queue"])
    after_first = list(repository.downloads)
    switched = _analyze(controller, aggregation="p95", run_output_columns=["Queue"])

    # Only the four Queue series are re-read; the results CSV is not re-fetched.
    assert RESULTS_URL not in repository.downloads[len(after_first) :]
    assert len(repository.downloads) - len(after_first) == 4
    # p95 differs from max, proving the second derived column was really built.
    assert [run.outputs["Queue"] for run in switched.runs] == [
        pytest.approx(0.975),
        pytest.approx(1.075),
        pytest.approx(2.9),
        pytest.approx(2.805),
    ]


def test_derived_output_is_reported_under_the_user_facing_name(
    fake_results_repository,
) -> None:
    repository = fake_results_repository(_results_and_series())
    controller = AnalyticsServiceController(results_repository=repository)

    result = _analyze(controller, run_output_columns=["Queue"])

    assert result.output_column == "Queue"
    assert result.aggregation == "max"
    for run in result.runs:
        assert "Queue" in run.outputs
        assert not any(key.startswith("Queue[") for key in run.outputs)


def test_distinct_result_urls_do_not_share_a_cache_entry(
    fake_results_repository,
) -> None:
    files = _results_and_series()
    files[f"{HOST}/other/results.csv.zip"] = (
        "A;Queue;Load\n0.4;oq.csv;ol.csv\n0.6;oq2.csv;ol2.csv\n"
    )
    files[f"{HOST}/other/oq.csv.zip"] = "time;Queue\n0;1.0\n1;3.0\n"
    files[f"{HOST}/other/ol.csv.zip"] = "time;Load\n0;1.0\n1;2.0\n"
    files[f"{HOST}/other/oq2.csv.zip"] = "time;Queue\n0;0.5\n1;1.0\n"
    files[f"{HOST}/other/ol2.csv.zip"] = "time;Load\n0;0.5\n1;1.0\n"
    repository = fake_results_repository(files)
    controller = AnalyticsServiceController(results_repository=repository)

    _analyze(controller)
    after_first = list(repository.downloads)
    _analyze(controller, results_urls=[f"{HOST}/other/results.csv.zip"])

    assert f"{HOST}/other/results.csv.zip" in repository.downloads[len(after_first) :]


def test_reordering_result_urls_does_not_reuse_the_entry(
    fake_results_repository,
) -> None:
    files = {
        f"{HOST}/one/results.csv.zip": "A;output\n0.1;1.0\n",
        f"{HOST}/two/results.csv.zip": "A;output\n0.9;3.0\n",
    }
    repository = fake_results_repository(files)
    controller = AnalyticsServiceController(results_repository=repository)
    forward = [f"{HOST}/one/results.csv.zip", f"{HOST}/two/results.csv.zip"]
    backward = list(reversed(forward))

    controller.analyze_monte_carlo_filtering(
        problem={"names": ["A"]},
        output_column="output",
        threshold=2.0,
        direction="greater",
        results_urls=forward,
    )
    after_first = list(repository.downloads)
    controller.analyze_monte_carlo_filtering(
        problem={"names": ["A"]},
        output_column="output",
        threshold=2.0,
        direction="greater",
        results_urls=backward,
    )

    assert repository.downloads[len(after_first) :] == backward


def test_expired_entry_is_rebuilt(fake_results_repository) -> None:
    repository = fake_results_repository(_results_and_series())
    controller = AnalyticsServiceController(results_repository=repository)
    cache = controller._results_table_cache
    now = {"value": datetime(2026, 1, 1, tzinfo=UTC)}
    cache._clock = lambda: now["value"]

    _analyze(controller)
    after_first = list(repository.downloads)
    now["value"] += timedelta(minutes=31)
    cache.cleanup_if_expired(cache.get_entry_ids())
    _analyze(controller)

    assert len(repository.downloads) == len(after_first) * 2


def test_concurrent_requests_build_the_table_once(
    fake_results_repository,
) -> None:
    class _SlowRepository:
        def __init__(self, files):
            self._files = {key: value.encode() for key, value in files.items()}
            self.downloads: list[str] = []
            self._lock = threading.Lock()

        def download(self, url: str) -> bytes:
            with self._lock:
                self.downloads.append(url)
            time.sleep(0.05)
            return self._files[url]

    repository = _SlowRepository(_results_and_series())
    controller = AnalyticsServiceController(results_repository=repository)
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def worker() -> None:
        barrier.wait()
        try:
            _analyze(controller)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert repository.downloads.count(RESULTS_URL) == 1
    assert len([url for url in repository.downloads if "q" in url]) == 4


def test_unresolved_timeseries_output_is_still_rejected(
    fake_results_repository,
) -> None:
    repository = fake_results_repository(_results_and_series())
    controller = AnalyticsServiceController(results_repository=repository)

    with pytest.raises(ValueError, match="unresolved timeseries references"):
        _analyze(controller, aggregation=None)


def test_scalar_timeseries_output_without_aggregation_is_unchanged(
    fake_results_repository,
) -> None:
    files = {
        f"{HOST}/config/results.csv.zip": "A;Queue\n0.1;1.0\n0.9;3.0\n",
    }
    repository = fake_results_repository(files)
    controller = AnalyticsServiceController(results_repository=repository)

    result = _analyze(controller, aggregation=None)

    assert result.behavioural_count == 1
    assert repository.downloads.count(RESULTS_URL) == 1