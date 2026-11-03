from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

from services.analytics.core.details.sensitivity_analysis import read_csv_from_string
from services.analytics.core.details.timeseries_aggregation import is_timeseries_reference
from use_case_contracts.dtos import (
    MonteCarloFilteringResult,
    MonteCarloFilteringRun,
    MonteCarloFilteringStatistic,
)


def smirnov_test(
    behavioural: np.ndarray,
    nonbehavioural: np.ndarray,
    alpha: float = 0.05,
) -> tuple[float, float, bool]:
    """Two-sided two-sample Smirnov (Kolmogorov-Smirnov) test.

    Returns the D statistic, the two-sided p-value and whether H0
    (both samples come from the same distribution) is rejected.
    """
    behavioural = np.asarray(behavioural, dtype=float)
    nonbehavioural = np.asarray(nonbehavioural, dtype=float)

    behavioural = behavioural[~np.isnan(behavioural)]
    nonbehavioural = nonbehavioural[~np.isnan(nonbehavioural)]

    result = ks_2samp(behavioural, nonbehavioural, alternative="two-sided")

    d = float(result.statistic)
    p = float(result.pvalue)
    h = p < alpha

    return d, p, h


def _empirical_cdf(samples: np.ndarray) -> tuple[list[float], list[float]]:
    ordered = np.sort(np.asarray(samples, dtype=float))
    ordered = ordered[~np.isnan(ordered)]
    if ordered.size == 0:
        return [], []
    cdf = np.arange(1, ordered.size + 1) / ordered.size
    return ordered.tolist(), cdf.tolist()


def run_monte_carlo_filtering(
    csv_data: str,
    parameter_names: list[str],
    output_column: str,
    threshold: float,
    direction: str,
    alpha: float = 0.05,
    aggregation: str | None = None,
    run_output_columns: list[str] | None = None,
    output_column_aliases: Mapping[str, str] | None = None,
) -> MonteCarloFilteringResult:
    """
    Run Monte Carlo Filtering on a combined main-results CSV.

    The CSV may contain scalar outputs directly or, when the output is a
    time series, pre-aggregated scalar values (one value per row).

    Parameters
    ----------
    csv_data : str
        Combined results CSV text (one header row).

    parameter_names : list of str
        Names of the input parameter columns.

    output_column : str
        Name of the output column to filter on.

    threshold : float
        Behavioural threshold value.

    direction : str
        "greater" -> behavioural when output > threshold.
        "less"    -> behavioural when output < threshold.
        Strict comparisons are used (equal values are non-behavioural).

    alpha : float, optional
        Significance level for the Smirnov test. Default 0.05.

    aggregation : str | None, optional
        Aggregation method used to reduce a time-series output to one
        value per row (""mean"", ""min"", ""max"", ""median"", ""p95"").
        Passed through into the result for reporting purposes.

    run_output_columns : list of str | None, optional
        Additional numeric output columns to expose on every run (used to
        plot runs against a freely chosen output).

    output_column_aliases : Mapping[str, str] | None, optional
        Report the CSV column under a different, user facing name. Used when
        the CSV holds a derived column such as ``"Queue[max]"`` that should be
        exposed to callers simply as ``"Queue"``.

    Returns
    -------
    MonteCarloFilteringResult
        Per-parameter Smirnov statistics plus behavioural class counts.
    """

    if not parameter_names:
        raise ValueError("parameter_names must contain at least one column name.")

    if direction not in ("greater", "less"):
        raise ValueError(
            "direction must be either 'greater' or 'less'."
        )

    dataframe = read_csv_from_string(csv_data)
    aliases = dict(output_column_aliases or {})

    requested_outputs = list(run_output_columns or [])
    required_columns = parameter_names + [output_column] + [
        name for name in requested_outputs if name not in parameter_names
    ]
    missing_columns = [
        column for column in required_columns if column not in dataframe.columns
    ]
    if missing_columns:
        raise ValueError(
            f"Missing required columns in CSV: {missing_columns}"
        )

    if dataframe[output_column].map(is_timeseries_reference).any():
        raise ValueError(
            f"Direct CSV contains unresolved timeseries references in output "
            f"column '{output_column}'; provide results_urls so they can be "
            "downloaded."
        )

    x = dataframe[parameter_names].to_numpy(dtype=float)
    base_y = pd.to_numeric(
        dataframe[output_column], errors="coerce"
    ).to_numpy(dtype=float)

    if np.isnan(base_y).any():
        raise ValueError(
            f"Output column '{output_column}' contains non-numeric values."
        )

    output_values: dict[str, np.ndarray] = {}
    for name in requested_outputs:
        numeric = pd.to_numeric(dataframe[name], errors="coerce").to_numpy(
            dtype=float
        )
        output_values[name] = numeric

    if direction == "greater":
        ib = base_y > threshold
        in_ = base_y <= threshold
    else:
        ib = base_y < threshold
        in_ = base_y >= threshold

    behavioural_count = int(np.sum(ib))
    non_behavioural_count = int(np.sum(in_))

    if behavioural_count == 0:
        raise ValueError(
            "No behavioural samples found for the given threshold and "
            "direction of output "
            f"'{output_column}'."
        )
    if non_behavioural_count == 0:
        raise ValueError(
            "No non-behavioural samples found for the given threshold and "
            "direction of output "
            f"'{output_column}'."
        )

    x_behavioural = x[ib]
    x_nonbehavioural = x[in_]

    statistics: list[MonteCarloFilteringStatistic] = []
    for parameter_index, parameter_name in enumerate(parameter_names):
        behavioural = x_behavioural[:, parameter_index]
        nonbehavioural = x_nonbehavioural[:, parameter_index]
        d, p, h = smirnov_test(
            behavioural,
            nonbehavioural,
            alpha=alpha,
        )

        b_x, b_y = _empirical_cdf(behavioural)
        nb_x, nb_y = _empirical_cdf(nonbehavioural)

        statistics.append(
            MonteCarloFilteringStatistic(
                parameter=parameter_name,
                d_statistic=d,
                p_value=p,
                reject_h0=h,
                behavioural_samples=behavioural_count,
                non_behavioural_samples=non_behavioural_count,
                behavioural_ecdf_x=b_x,
                behavioural_ecdf_y=b_y,
                non_behavioural_ecdf_x=nb_x,
                non_behavioural_ecdf_y=nb_y,
            )
        )

    behavioural_mask = ib.tolist()
    runs = _build_runs(
        parameter_names=parameter_names,
        x=x,
        output_values=output_values,
        behavioural_mask=behavioural_mask,
        output_column_aliases=output_column_aliases,
    )

    return MonteCarloFilteringResult(
        output_column=aliases.get(output_column, output_column),
        threshold=threshold,
        direction=direction,
        aggregation=aggregation,
        behavioural_count=behavioural_count,
        non_behavioural_count=non_behavioural_count,
        parameters=statistics,
        runs=runs,
    )


def _build_runs(
    *,
    parameter_names: list[str],
    x: np.ndarray,
    output_values: dict[str, np.ndarray],
    behavioural_mask: list[bool],
    output_column_aliases: Mapping[str, str] | None = None,
) -> list[MonteCarloFilteringRun]:
    aliases = output_column_aliases or {}
    runs: list[MonteCarloFilteringRun] = []
    for index, is_behavioural in enumerate(behavioural_mask):
        parameters = {
            name: float(x[index, position])
            for position, name in enumerate(parameter_names)
        }
        outputs = {
            aliases.get(name, name): float(values[index])
            for name, values in output_values.items()
        }
        runs.append(
            MonteCarloFilteringRun(
                index=index,
                behavioural=bool(is_behavioural),
                parameters=parameters,
                outputs=outputs,
            )
        )
    return runs
