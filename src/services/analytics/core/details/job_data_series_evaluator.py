from __future__ import annotations

from collections.abc import Callable
import io
from dataclasses import dataclass

import pandas as pd
from pandas.errors import EmptyDataError

from services.analytics.core.model import DataSeries
from use_case_contracts.ports import ResultsRepositoryPort


@dataclass(frozen=True)
class _AggregationSpec:
    name: str
    aggregator: str | Callable[[pd.Series], float]

def _identity_aggregator(series: pd.Series) -> float:
    if len(series) != 1:
        raise ValueError(
            f"'none' statistic expects exactly one value per group, got {len(series)}"
        )
    return float(series.iloc[0])


SUPPORTED_STATISTICS = {
    "mean": _AggregationSpec(name="mean", aggregator="mean"),
    "min": _AggregationSpec(name="min", aggregator="min"),
    "max": _AggregationSpec(name="max", aggregator="max"),
    "median": _AggregationSpec(name="median", aggregator=lambda series: series.quantile(0.5)),
    "p95": _AggregationSpec(name="p95", aggregator=lambda series: series.quantile(0.95)),
    "none": _AggregationSpec(
        name="none",
        aggregator=lambda series: _identity_aggregator(series),
    ),
}

def time_series_statistic_to_aggregator_name(statistic_name: str):
    lookup = {
        'average_over_time': 'mean',
        'min_over_time': 'min',
        'max_over_time': 'max',
        'median_over_time': 'median',
        'p95_over_time': 'p95',
        'series_average': 'mean',
        'series_min': 'min',
        'series_max': 'max',
        'series_median': 'median',
        'series_p95': 'p95'
    }
    try:
        return lookup[statistic_name.lower()]
    except KeyError:
        return statistic_name.lower()

def get_supported_statistics_names() -> list[str]:
    return list(SUPPORTED_STATISTICS.keys())


class JobDataSeriesEvaluator:
    """Evaluate an aggregated x/y data series from one in-memory job CSV."""

    def __init__(self,
                 main_results: str,
                 results_repository: ResultsRepositoryPort
                 ) -> None:
        self._main_results = main_results
        self._results_repo = results_repository

    def evaluateTimeSeries(
            self,
            y_param: str,
            constants: list[tuple[str, str]],
            statistic: str,
    ) -> DataSeries:
        x_param = "time"
        aggregator_name = time_series_statistic_to_aggregator_name(statistic)
        aggregation = self._aggregation_spec(aggregator_name)

        dataframe = self._load_dataframe()
        self._require_columns(dataframe, [y_param])
        self._require_columns(dataframe, [name for name, _ in constants])

        filtered = self._filter_constants(dataframe, constants).copy()
        filtered = filtered.dropna(subset=[y_param])

        sub_results = []
        for url in filtered[y_param]:
            content = self._results_repo.download(url).decode(encoding="utf-8")
            sub_result_df = self._load_dataframe_from_str(content)
            self._require_columns(sub_result_df, [x_param, y_param])

            prepared = sub_result_df[[x_param, y_param]].copy()
            prepared[x_param] = prepared[x_param].map(self._normalize_scalar_value)
            prepared[y_param] = pd.to_numeric(prepared[y_param], errors="coerce")
            prepared = prepared.dropna(subset=[x_param, y_param]).rename(
                columns={y_param: "value"}
            )

            if not prepared.empty:
                sub_results.append(prepared)

        grouped = self._aggregate_time_series(sub_results, aggregator_name)

        if grouped.empty:
            return DataSeries(
                x_name=x_param,
                y_name=y_param,
                statistic=aggregation.name,
                constants=list(constants),
                x_values=[],
                y_values=[],
            )

        x_values = [self._serialize_x_value(value) for value in grouped[x_param].tolist()]
        y_values = [float(value) for value in grouped["value"].tolist()]

        return DataSeries(
            x_name=x_param,
            y_name=y_param,
            statistic=aggregation.name,
            constants=list(constants),
            x_values=x_values,
            y_values=y_values,
        )

    def aggregateTimeSeries(
            self,
            x_param: str,
            y_param: str,
            constants: list[tuple[str, str]],
            statistic: str,
    ) -> DataSeries:
        x_param = x_param
        aggregator_name = time_series_statistic_to_aggregator_name(statistic)

        aggregation = self._aggregation_spec(aggregator_name)

        dataframe = self._load_dataframe()
        self._require_columns(dataframe, [x_param, y_param])
        self._require_columns(dataframe, [name for name, _ in constants])

        filtered = self._filter_constants(dataframe, constants).copy()
        filtered[x_param] = filtered[x_param].map(self._normalize_scalar_value)
        filtered = filtered.dropna(subset=[x_param, y_param])

        if filtered.empty:
            return DataSeries(
                x_name=x_param,
                y_name=y_param,
                statistic=aggregation.name,
                constants=list(constants),
                x_values=[],
                y_values=[],
            )

        x_to_samples: dict[str | int | float | bool, list[float]] = {}

        for _, row in filtered.iterrows():
            x_value = row[x_param]
            url = row[y_param]

            if not isinstance(url, str) or not url.strip():
                continue

            content = self._results_repo.download(url).decode(encoding="utf-8")
            sub_result_df = self._load_dataframe_from_str(content)
            self._require_columns(sub_result_df, ["time", y_param])

            samples = pd.to_numeric(sub_result_df[y_param], errors="coerce").dropna()
            if samples.empty:
                continue

            x_to_samples.setdefault(x_value, []).extend(float(value) for value in samples.tolist())

        if not x_to_samples:
            return DataSeries(
                x_name=x_param,
                y_name=y_param,
                statistic=aggregation.name,
                constants=list(constants),
                x_values=[],
                y_values=[],
            )

        rows: list[dict[str, object]] = []
        for x_value, samples in x_to_samples.items():
            if not samples:
                continue

            samples_series = pd.Series(samples, dtype="float64")
            aggregated_value = float(samples_series.agg(aggregation.aggregator))

            rows.append(
                {
                    x_param: x_value,
                    y_param: aggregated_value,
                }
            )

        if not rows:
            return DataSeries(
                x_name=x_param,
                y_name=y_param,
                statistic=aggregation.name,
                constants=list(constants),
                x_values=[],
                y_values=[],
            )

        grouped = pd.DataFrame(rows)
        grouped[x_param] = grouped[x_param].map(self._normalize_scalar_value)
        grouped[y_param] = pd.to_numeric(grouped[y_param], errors="coerce")
        grouped = grouped.dropna(subset=[x_param, y_param])

        if grouped.empty:
            return DataSeries(
                x_name=x_param,
                y_name=y_param,
                statistic=aggregation.name,
                constants=list(constants),
                x_values=[],
                y_values=[],
            )

        numeric_x_values = pd.to_numeric(grouped[x_param], errors="coerce")
        if not numeric_x_values.isna().any() and not any(
                isinstance(value, bool) for value in grouped[x_param].tolist()
        ):
            grouped = grouped.sort_values(
                by=x_param,
                key=lambda s: pd.to_numeric(s, errors="coerce"),
            )

        x_values = [self._serialize_x_value(value) for value in grouped[x_param].tolist()]
        y_values = [float(value) for value in grouped[y_param].tolist()]

        return DataSeries(
            x_name=x_param,
            y_name=y_param,
            statistic=aggregation.name,
            constants=list(constants),
            x_values=x_values,
            y_values=y_values,
        )

    def evaluateSeries(
        self,
        x_param: str,
        y_param: str,
        constants: list[tuple[str, str]],
        statistic: str,
    ) -> DataSeries:
        """Return an aggregated data series for the requested columns."""

        dataframe = self._load_dataframe()
        self._require_columns(dataframe, [x_param, y_param])
        self._require_columns(dataframe, [name for name, _ in constants])

        filtered = self._filter_constants(dataframe, constants).copy()
        filtered[x_param] = filtered[x_param].map(self._normalize_scalar_value)
        filtered[y_param] = pd.to_numeric(filtered[y_param], errors="coerce")
        filtered = filtered.dropna(subset=[x_param, y_param])

        if filtered.empty:
            return DataSeries(
                x_name=x_param,
                y_name=y_param,
                statistic=statistic,
                constants=list(constants),
                x_values=[],
                y_values=[],
            )

        aggregation = self._aggregation_spec(statistic)
        grouped = (
            filtered.groupby(x_param, sort=False, dropna=True)[y_param]
            .agg(aggregation.aggregator)
            .reset_index()
        )

        grouped[x_param] = grouped[x_param].map(self._normalize_scalar_value)
        grouped[y_param] = pd.to_numeric(grouped[y_param], errors="coerce")
        grouped = grouped.dropna(subset=[x_param, y_param])

        if grouped.empty:
            return DataSeries(
                x_name=x_param,
                y_name=y_param,
                statistic=aggregation.name,
                constants=list(constants),
                x_values=[],
                y_values=[],
            )

        numeric_x_values = pd.to_numeric(grouped[x_param], errors="coerce")
        if not numeric_x_values.isna().any() and not any(
            isinstance(value, bool) for value in grouped[x_param].tolist()
        ):
            grouped = grouped.sort_values(by=x_param, key=lambda s: pd.to_numeric(s, errors="coerce"))

        x_values = [self._serialize_x_value(value) for value in grouped[x_param].tolist()]
        y_values = [float(value) for value in grouped[y_param].tolist()]

        return DataSeries(
            x_name=x_param,
            y_name=y_param,
            statistic=aggregation.name,
            constants=list(constants),
            x_values=x_values,
            y_values=y_values,
        )

    def _aggregate_time_series(
            self,
            sub_results: list[pd.DataFrame],
            statistic: str,
    ) -> pd.DataFrame:
        aggregation = self._aggregation_spec(statistic)

        if not sub_results:
            return pd.DataFrame(columns=["time", "value"])

        combined = pd.concat(sub_results, ignore_index=True)

        if combined.empty:
            return pd.DataFrame(columns=["time", "value"])

        grouped = (
            combined.groupby("time", sort=False, dropna=True)["value"]
            .agg(aggregation.aggregator)
            .reset_index()
        )

        grouped["time"] = grouped["time"].map(self._normalize_scalar_value)
        grouped["value"] = pd.to_numeric(grouped["value"], errors="coerce")
        grouped = grouped.dropna(subset=["time", "value"])

        if grouped.empty:
            return pd.DataFrame(columns=["time", "value"])

        numeric_x_values = pd.to_numeric(grouped["time"], errors="coerce")
        if not numeric_x_values.isna().any() and not any(
                isinstance(value, bool) for value in grouped["time"].tolist()
        ):
            grouped = grouped.sort_values(
                by="time",
                key=lambda s: pd.to_numeric(s, errors="coerce"),
            )

        return grouped

    def _load_dataframe_from_str(self, content: str) -> pd.DataFrame:
        try:
            dataframe = pd.read_csv(io.StringIO(content), delimiter=";")
        except EmptyDataError as exc:
            raise ValueError("Job result CSV is empty") from exc
        if dataframe.empty and len(dataframe.columns) == 0:
            raise ValueError("Job result CSV has no columns")
        return dataframe

    def _load_dataframe(self) -> pd.DataFrame:
        return self._load_dataframe_from_str(self._main_results)

    def _require_columns(self, dataframe: pd.DataFrame, columns: list[str]) -> None:
        for column in columns:
            if column not in dataframe.columns:
                raise ValueError(f"Missing expected column {column!r}")

    def _filter_constants(
        self,
        dataframe: pd.DataFrame,
        constants: list[tuple[str, str]],
    ) -> pd.DataFrame:
        if not constants:
            return dataframe

        mask = pd.Series(True, index=dataframe.index)
        for parameter_name, constant_value in constants:
            comparable_values = dataframe[parameter_name].map(self._normalize_scalar_value)
            mask &= comparable_values.map(
                lambda actual: self._matches_constant(actual, constant_value)
            )
        return dataframe[mask]

    def _aggregation_spec(self, statistic: str) -> _AggregationSpec:
        normalized = statistic.strip().lower()
        return SUPPORTED_STATISTICS[normalized]

    def _matches_constant(self, actual: object, expected: str) -> bool:
        normalized_actual = self._normalize_scalar_value(actual)
        normalized_expected = self._normalize_constant_value(expected)

        if normalized_actual is None:
            return False
        if type(normalized_actual) is type(normalized_expected):
            return normalized_actual == normalized_expected
        if (
            isinstance(normalized_actual, (int, float))
            and not isinstance(normalized_actual, bool)
            and isinstance(normalized_expected, (int, float))
            and not isinstance(normalized_expected, bool)
        ):
            return float(normalized_actual) == float(normalized_expected)
        return str(normalized_actual) == str(normalized_expected)

    def _normalize_constant_value(self, value: str) -> str | int | float | bool:
        stripped = value.strip()
        lowered = stripped.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        try:
            if any(token in stripped for token in (".", "e", "E")):
                return float(stripped)
            return int(stripped)
        except ValueError:
            return stripped

    def _normalize_scalar_value(self, value: object) -> str | int | float | bool | None:
        if pd.isna(value):
            return None
        if hasattr(value, "item"):
            python_value = value.item()
        else:
            python_value = value
        if python_value is None:
            return None
        if isinstance(python_value, bool):
            return python_value
        if isinstance(python_value, (str, int, float)):
            return python_value
        return str(python_value)

    def _serialize_x_value(self, value: object) -> str | int | float | bool:
        normalized = self._normalize_scalar_value(value)
        if normalized is None:
            raise ValueError("x values must not be missing after filtering")
        return normalized
