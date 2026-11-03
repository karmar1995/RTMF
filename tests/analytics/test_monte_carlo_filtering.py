from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from adapters.fake_adapters.fake_analytics import FakeAnalytics
from services.analytics.core.details.analytics_service_controller import (
    AnalyticsServiceController,
)
from services.analytics.core.details.monte_carlo_filtering import (
    run_monte_carlo_filtering,
)
from services.analytics.rest_api.api import create_app
from use_case_contracts.dtos import (
    MonteCarloFilteringResult,
    MonteCarloFilteringRun,
)
from use_case_contracts.errors import JobsRepositoryInvalidUrlError


_S3_RESULTS_URL_0 = "s3://rtmf/jobs/1097/subjobs/0/results.csv.zip"


def _csv_text() -> str:
    rows = [
        "A;B;output",
        "0.1;10;1.00",
        "0.1;10;1.05",
        "0.1;10;1.10",
        "0.1;10;1.15",
        "0.1;10;1.20",
        "0.9;10;3.00",
        "0.9;10;2.95",
        "0.9;10;3.05",
        "0.9;10;2.90",
        "0.9;10;3.10",
    ]
    return "\n".join(rows)


def test_monte_carlo_filtering_greater_detects_important_parameter() -> None:
    result = run_monte_carlo_filtering(
        csv_data=_csv_text(),
        parameter_names=["A", "B"],
        output_column="output",
        threshold=2.0,
        direction="greater",
    )

    assert result.output_column == "output"
    assert result.threshold == 2.0
    assert result.direction == "greater"
    assert result.behavioural_count == 5
    assert result.non_behavioural_count == 5

    by_name = {stat.parameter: stat for stat in result.parameters}
    assert by_name["A"].reject_h0 is True
    assert by_name["A"].d_statistic == pytest.approx(1.0)
    assert by_name["A"].behavioural_samples == 5
    assert by_name["A"].non_behavioural_samples == 5
    assert by_name["B"].reject_h0 is False
    assert by_name["B"].d_statistic == pytest.approx(0.0)


def test_monte_carlo_filtering_returns_ecdf_arrays() -> None:
    result = run_monte_carlo_filtering(
        csv_data=_csv_text(),
        parameter_names=["A", "B"],
        output_column="output",
        threshold=2.0,
        direction="greater",
    )

    stat_a = {stat.parameter: stat for stat in result.parameters}["A"]
    assert stat_a.behavioural_ecdf_x == pytest.approx([0.9, 0.9, 0.9, 0.9, 0.9])
    assert stat_a.behavioural_ecdf_y == pytest.approx([0.2, 0.4, 0.6, 0.8, 1.0])
    assert stat_a.non_behavioural_ecdf_x == pytest.approx([0.1, 0.1, 0.1, 0.1, 0.1])
    assert stat_a.non_behavioural_ecdf_y == pytest.approx([0.2, 0.4, 0.6, 0.8, 1.0])

    stat_b = {stat.parameter: stat for stat in result.parameters}["B"]
    # B is constant across all runs, so each group's ECDF is a step at 10.0
    assert stat_b.behavioural_ecdf_x == pytest.approx([10.0] * 5)
    assert stat_b.non_behavioural_ecdf_x == pytest.approx([10.0] * 5)


def test_monte_carlo_filtering_less_detects_important_parameter() -> None:
    result = run_monte_carlo_filtering(
        csv_data=_csv_text(),
        parameter_names=["A", "B"],
        output_column="output",
        threshold=2.0,
        direction="less",
    )

    by_name = {stat.parameter: stat for stat in result.parameters}
    assert result.behavioural_count == 5
    assert by_name["A"].reject_h0 is True
    assert by_name["B"].reject_h0 is False


def test_monte_carlo_filtering_builds_runs_for_every_row_from_direct_csv() -> None:
    csv_data = (
        "A;output\n"
        "0.1;1.0\n"
        "0.2;1.2\n"
        "0.3;1.4\n"
        "0.9;3.0\n"
        "0.8;2.8\n"
        "0.7;3.1\n"
    )

    result = run_monte_carlo_filtering(
        csv_data=csv_data,
        parameter_names=["A"],
        output_column="output",
        threshold=2.0,
        direction="greater",
        run_output_columns=["output"],
    )

    assert [run.index for run in result.runs] == [0, 1, 2, 3, 4, 5]
    assert [run.behavioural for run in result.runs] == [
        False,
        False,
        False,
        True,
        True,
        True,
    ]
    assert [run.parameters["A"] for run in result.runs] == [
        pytest.approx(0.1),
        pytest.approx(0.2),
        pytest.approx(0.3),
        pytest.approx(0.9),
        pytest.approx(0.8),
        pytest.approx(0.7),
    ]
    assert [run.outputs["output"] for run in result.runs] == [
        pytest.approx(1.0),
        pytest.approx(1.2),
        pytest.approx(1.4),
        pytest.approx(3.0),
        pytest.approx(2.8),
        pytest.approx(3.1),
    ]


def test_monte_carlo_filtering_only_exposes_requested_outputs() -> None:
    result = run_monte_carlo_filtering(
        csv_data=_csv_text(),
        parameter_names=["A", "B"],
        output_column="output",
        threshold=2.0,
        direction="greater",
    )

    assert len(result.runs) == 10
    assert result.runs[0].outputs == {}
    assert result.runs[0].parameters["A"] == pytest.approx(0.1)


def test_fake_analytics_returns_all_runs_for_direct_csv() -> None:
    result = FakeAnalytics().analyze_monte_carlo_filtering(
        csv_data=_csv_text(),
        problem={"names": ["A", "B"]},
        output_column="output",
        threshold=2.0,
        direction="greater",
        run_output_columns=["output"],
    )

    assert [run.index for run in result.runs] == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert [run.behavioural for run in result.runs] == [
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        True,
        True,
        True,
    ]
    assert [run.outputs["output"] for run in result.runs[:3]] == [
        pytest.approx(1.0),
        pytest.approx(1.05),
        pytest.approx(1.10),
    ]


def test_monte_carlo_filtering_rejects_direct_csv_timeseries_references() -> None:
    with pytest.raises(ValueError, match="unresolved timeseries references"):
        run_monte_carlo_filtering(
            csv_data="A;output\n0.1;run.csv\n0.9;other.csv\n",
            parameter_names=["A"],
            output_column="output",
            threshold=2.0,
            direction="greater",
        )


def test_monte_carlo_filtering_threshold_comparison_is_strict() -> None:
    result = run_monte_carlo_filtering(
        csv_data=_csv_text(),
        parameter_names=["A", "B"],
        output_column="output",
        threshold=1.1,
        direction="greater",
    )

    # output == 1.1 falls on the non-behavioural side
    assert result.behavioural_count == 7
    assert result.non_behavioural_count == 3


def test_monte_carlo_filtering_rejects_empty_behavioural_group() -> None:
    with pytest.raises(ValueError, match="behavioural"):
        run_monte_carlo_filtering(
            csv_data=_csv_text(),
            parameter_names=["A", "B"],
            output_column="output",
            threshold=100.0,
            direction="greater",
        )


def test_monte_carlo_filtering_rejects_empty_non_behavioural_group() -> None:
    with pytest.raises(ValueError, match="non-behavioural"):
        run_monte_carlo_filtering(
            csv_data=_csv_text(),
            parameter_names=["A", "B"],
            output_column="output",
            threshold=10.0,
            direction="less",
        )


def test_monte_carlo_filtering_rejects_invalid_direction() -> None:
    with pytest.raises(ValueError, match="direction"):
        run_monte_carlo_filtering(
            csv_data=_csv_text(),
            parameter_names=["A", "B"],
            output_column="output",
            threshold=2.0,
            direction="loss",
        )


def test_monte_carlo_filtering_rejects_missing_columns() -> None:
    with pytest.raises(ValueError, match="Missing required columns"):
        run_monte_carlo_filtering(
            csv_data=_csv_text(),
            parameter_names=["A", "Missing"],
            output_column="output",
            threshold=2.0,
            direction="greater",
        )


def test_monte_carlo_filtering_rejects_non_numeric_output() -> None:
    with pytest.raises(ValueError, match="non-numeric"):
        run_monte_carlo_filtering(
            csv_data="A;B;output\n0.1;10;abc\n0.9;10;3.0\n",
            parameter_names=["A", "B"],
            output_column="output",
            threshold=2.0,
            direction="greater",
        )


def test_monte_carlo_filtering_rejects_empty_parameter_names() -> None:
    with pytest.raises(ValueError, match="parameter_names"):
        run_monte_carlo_filtering(
            csv_data=_csv_text(),
            parameter_names=[],
            output_column="output",
            threshold=2.0,
            direction="greater",
        )


def test_controller_aggregates_timeseries_output_before_filtering(
    fake_results_repository,
) -> None:
    config_0 = (
        "A;B;Queue\n"
        "0.1;10;ts_0.csv\n"
        "0.1;10;ts_1.csv\n"
        "0.1;10;ts_2.csv\n"
        "0.1;10;ts_3.csv\n"
        "0.1;10;ts_4.csv\n"
    )
    config_1 = (
        "A;B;Queue\n"
        "0.9;10;ts_5.csv\n"
        "0.9;10;ts_6.csv\n"
        "0.9;10;ts_7.csv\n"
        "0.9;10;ts_8.csv\n"
        "0.9;10;ts_9.csv\n"
    )
    files: dict[str, str] = {
        "https://host/config_0/results.csv.zip": config_0,
        "https://host/config_1/results.csv.zip": config_1,
    }
    low_maxes = ["0.8", "1.0", "1.0", "1.0", "1.0"]
    for index, tail in enumerate(low_maxes):
        peak, _ = tail.split(".", 1)
        timeseries = f"time;Queue\n0;{float(peak) - 0.2:g}\n1;{tail}\n2;{tail}\n"
        files[f"https://host/config_0/ts_{index}.csv.zip"] = timeseries
    high_maxes = ["2.8", "3.0", "2.9", "2.9", "3.1"]
    for index, tail in enumerate(high_maxes):
        peak, _ = tail.split(".", 1)
        timeseries = f"time;Queue\n0;{float(peak) - 0.2:g}\n1;{tail}\n2;{tail}\n"
        files[f"https://host/config_1/ts_{index + 5}.csv.zip"] = timeseries

    controller = AnalyticsServiceController(
        results_repository=fake_results_repository(files)
    )

    result = controller.analyze_monte_carlo_filtering(
        problem={"names": ["A", "B"]},
        output_column="Queue",
        threshold=2.0,
        direction="greater",
        results_urls=[
            "https://host/config_0/results.csv.zip",
            "https://host/config_1/results.csv.zip",
        ],
        aggregation="max",
    )

    assert result.aggregation == "max"
    assert result.behavioural_count == 5
    assert result.non_behavioural_count == 5
    by_name = {stat.parameter: stat for stat in result.parameters}
    assert by_name["A"].reject_h0 is True
    assert by_name["B"].reject_h0 is False
    assert isinstance(result, MonteCarloFilteringResult)


def test_controller_builds_runs_with_independent_scatter_aggregation(
    fake_results_repository,
) -> None:
    config = (
        "A;Queue;Throughput\n"
        "0.1;q0.csv;t0.csv\n"
        "0.1;q1.csv;t1.csv\n"
        "0.9;q2.csv;t2.csv\n"
        "0.9;q3.csv;t3.csv\n"
    )
    files: dict[str, str] = {
        "https://host/config/results.csv.zip": config,
        "https://host/config/q0.csv.zip": "time;Queue\n0;0.5\n1;1.0\n",
        "https://host/config/q1.csv.zip": "time;Queue\n0;0.6\n1;1.1\n",
        "https://host/config/q2.csv.zip": "time;Queue\n0;1.0\n1;3.0\n",
        "https://host/config/q3.csv.zip": "time;Queue\n0;1.0\n1;2.9\n",
        "https://host/config/t0.csv.zip": "time;Throughput\n0;10\n1;15\n",
        "https://host/config/t1.csv.zip": "time;Throughput\n0;20\n1;25\n",
        "https://host/config/t2.csv.zip": "time;Throughput\n0;30\n1;35\n",
        "https://host/config/t3.csv.zip": "time;Throughput\n0;40\n1;45\n",
    }
    controller = AnalyticsServiceController(
        results_repository=fake_results_repository(files)
    )

    result = controller.analyze_monte_carlo_filtering(
        problem={"names": ["A"]},
        output_column="Queue",
        threshold=2.0,
        direction="greater",
        results_urls=["https://host/config/results.csv.zip"],
        aggregation="max",
        output_aggregations={"Throughput": "min"},
        run_output_columns=["Queue", "Throughput"],
    )

    # Filtering classification still uses the *max* of Queue.
    assert [run.behavioural for run in result.runs] == [False, False, True, True]
    assert [run.outputs["Queue"] for run in result.runs] == [
        pytest.approx(1.0),
        pytest.approx(1.1),
        pytest.approx(3.0),
        pytest.approx(2.9),
    ]
    # Scatter output uses its own aggregation (min) without touching the filter.
    assert [run.outputs["Throughput"] for run in result.runs] == [
        pytest.approx(10.0),
        pytest.approx(20.0),
        pytest.approx(30.0),
        pytest.approx(40.0),
    ]
    assert [run.parameters["A"] for run in result.runs] == [
        pytest.approx(0.1),
        pytest.approx(0.1),
        pytest.approx(0.9),
        pytest.approx(0.9),
    ]


def test_controller_collects_scalar_runs_for_all_rows(
    fake_results_repository,
) -> None:
    config_0 = (
        "repetition;A;output\n"
        "0;0.1;1.0\n"
        "1;0.1;1.2\n"
    )
    config_1 = (
        "repetition;A;output\n"
        "0;0.9;3.0\n"
        "1;0.9;2.8\n"
    )
    files: dict[str, str] = {
        "https://host/config_0/results.csv.zip": config_0,
        "https://host/config_1/results.csv.zip": config_1,
    }

    controller = AnalyticsServiceController(
        results_repository=fake_results_repository(files)
    )

    result = controller.analyze_monte_carlo_filtering(
        problem={"names": ["A"]},
        output_column="output",
        threshold=2.0,
        direction="greater",
        results_urls=[
            "https://host/config_0/results.csv.zip",
            "https://host/config_1/results.csv.zip",
        ],
        run_output_columns=["output"],
    )

    assert [run.index for run in result.runs] == [0, 1, 2, 3]
    assert [run.behavioural for run in result.runs] == [False, False, True, True]
    assert [run.outputs["output"] for run in result.runs] == [
        pytest.approx(1.0),
        pytest.approx(1.2),
        pytest.approx(3.0),
        pytest.approx(2.8),
    ]
    assert [run.parameters["A"] for run in result.runs] == [
        pytest.approx(0.1),
        pytest.approx(0.1),
        pytest.approx(0.9),
        pytest.approx(0.9),
    ]


def test_controller_caches_repeated_timeseries_urls_per_request(
    fake_results_repository,
) -> None:
    results_url = "https://host/config/results.csv.zip"
    behavioural_url = "https://host/config/behavioural.csv.zip"
    nonbehavioural_url = "https://host/config/nonbehavioural.csv.zip"
    files = {
        results_url: (
            "repetition;A;Queue\n"
            "0;0.1;behavioural.csv\n"
            "1;0.2;behavioural.csv\n"
            "0;0.8;nonbehavioural.csv\n"
            "1;0.9;nonbehavioural.csv\n"
        ),
        behavioural_url: "time;Queue\n0;2.5\n1;2.8\n2;2.6\n",
        nonbehavioural_url: "time;Queue\n0;0.4\n1;0.5\n2;0.6\n",
    }
    repository = fake_results_repository(files)
    controller = AnalyticsServiceController(results_repository=repository)

    result = controller.analyze_monte_carlo_filtering(
        problem={"names": ["A"]},
        output_column="Queue",
        threshold=2.0,
        direction="greater",
        results_urls=[results_url],
        aggregation="max",
        run_output_columns=["Queue"],
    )

    assert repository.downloads.count(results_url) == 1
    assert repository.downloads.count(behavioural_url) == 1
    assert repository.downloads.count(nonbehavioural_url) == 1
    assert [run.index for run in result.runs] == [0, 1, 2, 3]
    assert [run.outputs["Queue"] for run in result.runs] == [
        pytest.approx(2.8),
        pytest.approx(2.8),
        pytest.approx(0.6),
        pytest.approx(0.6),
    ]


class _ConcurrencyTrackingRepository:
    """Records the peak number of downloads in flight and their order."""

    def __init__(self, files: dict[str, str], delay: float = 0.05) -> None:
        self._files = files
        self._delay = delay
        self._lock = threading.Lock()
        self._in_flight = 0
        self.peak_in_flight = 0
        self.completed: list[str] = []

    def download(self, url: str) -> bytes:
        with self._lock:
            self._in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        try:
            time.sleep(self._delay)
            return self._files[url].encode("utf-8")
        finally:
            with self._lock:
                self._in_flight -= 1
                self.completed.append(url)

def _scalar_files(count: int) -> dict[str, str]:
    return {
        f"https://host/config_{index}/results.csv.zip": (
            "repetition;A;output\n"
            f"0;{index / 100:.2f};{float(index)}\n"
            f"1;{index / 100:.2f};{float(index) + 0.5}\n"
        )
        for index in range(count)
    }


def test_controller_downloads_result_sources_concurrently() -> None:
    urls = [
        f"https://host/config_{index}/results.csv.zip" for index in range(8)
    ]
    repository = _ConcurrencyTrackingRepository(_scalar_files(8))
    controller = AnalyticsServiceController(
        results_repository=repository,
        download_workers=8,
    )

    result = controller.analyze_monte_carlo_filtering(
        problem={"names": ["A"]},
        output_column="output",
        threshold=5.0,
        direction="greater",
        results_urls=urls,
        run_output_columns=["output"],
    )

    assert repository.peak_in_flight > 1
    # Order preservation: each source must stay aligned with its own URL, so the
    # last downloaded CSV value must map back to the last URL.
    assert len(result.runs) == 16
    assert [run.outputs["output"] for run in result.runs][:2] == [
        pytest.approx(0.0),
        pytest.approx(0.5),
    ]


def test_controller_download_sources_are_stable_when_delayed_unevenly() -> None:
    """A slow first URL must not let a later URL overtake it."""
    files = _scalar_files(6)
    repository = _ConcurrencyTrackingRepository(files)

    original_download = repository.download

    def download(url: str) -> bytes:
        if url.endswith("config_0/results.csv.zip"):
            time.sleep(0.2)
        return original_download(url)

    repository.download = download  # type: ignore[method-assign]
    controller = AnalyticsServiceController(
        results_repository=repository,
        download_workers=6,
    )

    result = controller.analyze_monte_carlo_filtering(
        problem={"names": ["A"]},
        output_column="output",
        threshold=5.0,
        direction="greater",
        results_urls=[
            f"https://host/config_{index}/results.csv.zip" for index in range(6)
        ],
        run_output_columns=["output"],
    )

    # config_0 rows must appear first even though it finished last.
    assert [run.outputs["output"] for run in result.runs] == [
        pytest.approx(0.0),
        pytest.approx(0.5),
        pytest.approx(1.0),
        pytest.approx(1.5),
        pytest.approx(2.0),
        pytest.approx(2.5),
        pytest.approx(3.0),
        pytest.approx(3.5),
        pytest.approx(4.0),
        pytest.approx(4.5),
        pytest.approx(5.0),
        pytest.approx(5.5),
    ]


def test_controller_downloads_serially_when_a_single_worker_is_configured() -> None:
    urls = [f"https://host/config_{index}/results.csv.zip" for index in range(4)]
    repository = _ConcurrencyTrackingRepository(_scalar_files(4), delay=0.01)
    controller = AnalyticsServiceController(
        results_repository=repository,
        download_workers=1,
    )

    controller.analyze_monte_carlo_filtering(
        problem={"names": ["A"]},
        output_column="output",
        threshold=2.0,
        direction="greater",
        results_urls=urls,
        run_output_columns=["output"],
    )

    assert repository.peak_in_flight == 1
    assert repository.completed == urls


def test_controller_propagates_the_first_download_failure() -> None:
    urls = [f"https://host/config_{index}/results.csv.zip" for index in range(6)]

    class _FailingRepository(_ConcurrencyTrackingRepository):
        def download(self, url: str) -> bytes:
            if url.endswith("config_2/results.csv.zip"):
                time.sleep(0.05)
                raise JobsRepositoryInvalidUrlError("broken url")
            return super().download(url)

    controller = AnalyticsServiceController(
        results_repository=_FailingRepository(_scalar_files(6)),
        download_workers=6,
    )

    with pytest.raises(JobsRepositoryInvalidUrlError):
        controller.analyze_monte_carlo_filtering(
            problem={"names": ["A"]},
            output_column="output",
            threshold=5.0,
            direction="greater",
            results_urls=urls,
            run_output_columns=["output"],
        )


def test_controller_short_circuits_a_single_result_url() -> None:
    url = "https://host/config_0/results.csv.zip"
    repository = _ConcurrencyTrackingRepository(_scalar_files(1))

    controller = AnalyticsServiceController(results_repository=repository)

    result = controller.analyze_monte_carlo_filtering(
        problem={"names": ["A"]},
        output_column="output",
        threshold=0.25,
        direction="greater",
        results_urls=[url],
        run_output_columns=["output"],
    )

    assert repository.peak_in_flight == 1
    assert len(result.runs) == 2


class _StubAnalytics:
    def analyze_monte_carlo_filtering(self, **kwargs) -> MonteCarloFilteringResult:
        return MonteCarloFilteringResult(
            output_column=kwargs["output_column"],
            threshold=kwargs["threshold"],
            direction=kwargs["direction"],
            aggregation=kwargs["aggregation"],
            behavioural_count=7,
            non_behavioural_count=3,
            runs=[
                MonteCarloFilteringRun(
                    index=1,
                    behavioural=True,
                    parameters={"A": 0.9},
                    outputs={"output": 2.5},
                )
            ],
            parameters=[],
        )


def test_rest_endpoint_returns_statistics() -> None:
    app = create_app(_StubAnalytics())
    client = TestClient(app)

    response = client.post(
        "/monte-carlo-filtering",
        json={
            "problem": {"names": ["A", "B"]},
            "output_column": "output",
            "threshold": 2.0,
            "direction": "greater",
            "aggregation": "max",
            "run_output_columns": ["output"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["output_column"] == "output"
    assert payload["threshold"] == 2.0
    assert payload["direction"] == "greater"
    assert payload["aggregation"] == "max"
    assert payload["behavioural_count"] == 7
    assert payload["non_behavioural_count"] == 3
    assert payload["runs"] == [
        {
            "index": 1,
            "behavioural": True,
            "parameters": {"A": 0.9},
            "outputs": {"output": 2.5},
        }
    ]
    assert payload["parameters"] == []


class _FailingResultsRepositoryAnalytics:
    def analyze_monte_carlo_filtering(self, **kwargs):
        raise JobsRepositoryInvalidUrlError("ts_0.csv.zip")


class _InvalidRequestAnalytics:
    def analyze_monte_carlo_filtering(self, **kwargs):
        raise ValueError("Job has no results to analyze")


def test_rest_endpoint_reports_results_repository_failures() -> None:
    app = create_app(_FailingResultsRepositoryAnalytics())
    client = TestClient(app)

    response = client.post(
        "/monte-carlo-filtering",
        json={
            "problem": {"names": ["A"]},
            "output_column": "output",
            "threshold": 2.0,
            "direction": "greater",
            "results_urls": [_S3_RESULTS_URL_0],
            "aggregation": "mean",
        },
    )

    assert response.status_code == 400
    assert "ts_0.csv.zip" in response.json()["detail"]


def test_rest_endpoint_reports_validation_failures() -> None:
    app = create_app(_InvalidRequestAnalytics())
    client = TestClient(app)

    response = client.post(
        "/monte-carlo-filtering",
        json={
            "problem": {"names": ["A"]},
            "output_column": "output",
            "threshold": 2.0,
            "direction": "greater",
            "results_urls": [_S3_RESULTS_URL_0],
            "aggregation": "mean",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Job has no results to analyze"}


def test_rest_endpoint_validates_direction() -> None:
    app = create_app(_StubAnalytics())
    client = TestClient(app)

    response = client.post(
        "/monte-carlo-filtering",
        json={
            "problem": {"names": ["A", "B"]},
            "output_column": "output",
            "threshold": 2.0,
            "direction": "loss",
        },
    )

    assert response.status_code == 422
