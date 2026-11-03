from __future__ import annotations

from services.analytics.core.details.analytics_service_controller import (
    AnalyticsServiceController,
)

_RESULTS_URL = "s3://rtmf/jobs/1097/subjobs/0/results.csv.zip"
_TIMESERIES_URL = "s3://rtmf/jobs/1097/subjobs/0/ts_0.csv.zip"


def _results_csv() -> str:
    rows = ["A;Queue"]
    for index in range(12):
        value = f"{0.1 * (index + 1):.1f}"
        if index < 3:
            rows.append(f"{value};ts_0.csv")
        else:
            rows.append(f"{value};{0.5 + 0.1 * index:.1f}")
    return "\n".join(rows) + "\n"


def test_sensitivity_aggregates_timeseries_output_from_s3_results(
    fake_results_repository,
) -> None:
    repository = fake_results_repository(
        {
            _RESULTS_URL: _results_csv(),
            _TIMESERIES_URL: "time;Queue\n0;0.4\n1;0.9\n2;0.6\n",
        }
    )
    controller = AnalyticsServiceController(results_repository=repository)

    result = controller.analyze_sensitivity(
        problem={
            "names": ["A"],
            "bounds": [[0.0, 2.0]],
        },
        n_real=4,
        output_names=["Queue"],
        results_urls=[_RESULTS_URL],
        aggregation="mean",
    )

    assert repository.downloads == [_RESULTS_URL, _TIMESERIES_URL]
    assert "Queue" in result.mean_data_csv
    assert "ts_0.csv" not in result.mean_data_csv
