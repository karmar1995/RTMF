from __future__ import annotations

import io

import pandas as pd

from services.analytics.core.details.job_data_series_evaluator import SUPPORTED_STATISTICS


def is_timeseries_reference(value: object) -> bool:
    """Return whether a CSV cell points at a sibling time-series CSV."""

    return isinstance(value, str) and value.strip().lower().endswith(".csv")


def resolve_timeseries_url(*, source_url: str, cell: str) -> str:
    """Resolve a sibling time-series reference against the source URL it came from."""

    prefix, _, _ = source_url.rpartition("/")
    return f"{prefix}/{cell}.zip"


def resolve_aggregation_spec(aggregation: str):
    """Look up the aggregation spec for a user supplied method name."""

    aggregator_name = aggregation.strip().lower()
    if aggregator_name not in SUPPORTED_STATISTICS:
        raise ValueError(f"Unsupported aggregation method: {aggregation!r}")
    return SUPPORTED_STATISTICS[aggregator_name]


def aggregate_timeseries_values(
    *,
    dataframe: pd.DataFrame,
    value_column: str,
    aggregation_spec: object,
) -> float:
    """Reduce a time-series column to a single number using the requested aggregation."""

    if value_column not in dataframe.columns:
        raise ValueError(
            f"Timeseries CSV is missing expected column {value_column!r}"
        )
    series = pd.to_numeric(dataframe[value_column], errors="coerce").dropna()
    if series.empty:
        raise ValueError(
            f"No numeric values found in timeseries column {value_column!r}"
        )
    return float(series.agg(aggregation_spec.aggregator))


def load_timeseries_dataframe(
    *,
    timeseries_url: str,
    results_repository,
    timeseries_cache: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Download and parse a time-series CSV, memoised per request by URL."""

    if timeseries_url not in timeseries_cache:
        content = results_repository.download(timeseries_url).decode("utf-8")
        timeseries_cache[timeseries_url] = pd.read_csv(
            io.StringIO(content), delimiter=";"
        )
    return timeseries_cache[timeseries_url]