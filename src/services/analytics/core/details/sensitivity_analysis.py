from __future__ import annotations

import csv
import io

import numpy as np
import pandas as pd
from SALib.analyze import sobol

from use_case_contracts.dtos import SensitivityAnalysisResult

_SKIP_COLS = {"seed", "realization_id"}
_DEFAULT_BOUNDS: list[float] = [-2.12, 2.12]


def read_csv_from_string(csv_data: str) -> pd.DataFrame:
    try:
        sample = csv_data[:8192]
        dialect = csv.Sniffer().sniff(sample)
    except Exception:
        dialect = csv.excel
    return pd.read_csv(io.StringIO(csv_data), sep=dialect.delimiter)


def prepare_problem(problem: dict[str, object]) -> dict[str, object]:
    problem = dict(problem)
    problem["num_vars"] = len(problem["names"])
    return problem


def compute_saltelli_indices(
    problem: dict[str, object],
    data: pd.DataFrame,
    n_real: int,
    output_names: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    exp = pd.DataFrame(
        data.values.reshape(-1, n_real, data.shape[1]).mean(1)
    )
    exp.columns = output_names

    var = pd.DataFrame(
        data.values.reshape(-1, n_real, data.shape[1]).var(1)
    )
    var.columns = output_names

    vy = data.var()
    v_exp = exp.var()
    s_exp = (v_exp / vy).clip(upper=1)
    keys = ["S1", "ST", "S1_conf", "ST_conf"]

    df_exp = pd.DataFrame()
    for output_name in output_names:
        s_indices = sobol.analyze(
            problem,
            np.array(exp[output_name]),
            calc_second_order=False,
        )
        s_dict = {key: s_indices[key] for key in keys}
        s_dict["oSi"] = s_dict["S1"]
        s_dict["oST"] = s_dict["ST"]
        s_dict["S1"] = s_dict["S1"] * s_exp[output_name]
        s_dict["ST"] = s_dict["ST"] * s_exp[output_name]
        s_dict["input"] = problem["names"]
        s_dict["output"] = [output_name] * len(s_indices["S1"])
        df_exp = pd.concat(
            [df_exp, pd.DataFrame(s_dict)], ignore_index=True
        )

    df_exp.columns = [
        "Si",
        "ST",
        "Si_conf",
        "ST_conf",
        "oSi",
        "oST",
        "input",
        "output",
    ]
    df_exp["S_exp"] = df_exp["output"].map(s_exp.to_dict())
    df_exp[df_exp.select_dtypes("float64").columns] = (
        df_exp.select_dtypes("float64").clip(lower=0)
    )

    df_var = pd.DataFrame()
    if n_real > 2:
        for output_name in output_names:
            try:
                s_indices = sobol.analyze(
                    problem,
                    np.array(var[output_name]),
                    calc_second_order=False,
                )
            except Exception:
                continue

            s_dict = {key: s_indices[key] for key in keys}
            s_dict["oSi"] = s_dict["S1"]
            s_dict["oST"] = s_dict["ST"]
            s_dict["input"] = problem["names"]
            s_dict["output"] = [output_name] * len(s_indices["S1"])
            df_var = pd.concat(
                [df_var, pd.DataFrame(s_dict)], ignore_index=True
            )

        if not df_var.empty:
            df_var.columns = [
                "Si",
                "ST",
                "Si_conf",
                "ST_conf",
                "oSi",
                "oST",
                "input",
                "output",
            ]
            df_var[df_var.select_dtypes("float64").columns] = (
                df_var.select_dtypes("float64").clip(lower=0)
            )

    return df_exp, df_var, exp


def find_important_parameters(
    df_det: pd.DataFrame,
) -> dict[str, list[str]]:
    eps = 1e-12
    min_total_importance = 0.05
    min_relative_importance = 0.10
    lambda_interaction = 0.6

    df_det["interaction"] = np.maximum(df_det["ST"] - df_det["Si"], 0.0)
    df_det["importance"] = (
        df_det["Si"] + lambda_interaction * df_det["interaction"]
    )
    importance_sum = df_det.groupby("output")["importance"].sum()
    df_det["importance_sum"] = df_det["output"].map(importance_sum)
    df_det["output_sensitive"] = (
        df_det["importance_sum"] >= min_total_importance
    )
    df_det["relative_importance"] = np.where(
        df_det["importance_sum"] > eps,
        df_det["importance"] / df_det["importance_sum"],
        0.0,
    )

    important = df_det[
        (df_det["output_sensitive"])
        & (df_det["relative_importance"] >= min_relative_importance)
    ]

    all_outputs = df_det["output"].unique()
    important_dict: dict[str, list[str]] = {output: [] for output in all_outputs}

    important_grouped = (
        important.groupby("output")["input"].apply(list).to_dict()
    )
    important_dict.update(important_grouped)

    return important_dict


def run_sobol_analysis(
    csv_data: str,
    problem: dict[str, object],
    n_real: int,
    output_names: list[str] | None = None,
) -> SensitivityAnalysisResult:
    data = read_csv_from_string(csv_data)
    problem = prepare_problem(problem)

    input_names = set(problem["names"])
    skip_cols = _SKIP_COLS

    input_df = (
        data[[column for column in data.columns if column in input_names]]
        .iloc[::n_real]
        .reset_index(drop=True)
    )

    detected_output_names = output_names or [
        column
        for column in data.columns
        if column not in input_names and column not in skip_cols
    ]
    output_data = data[detected_output_names]

    df_det, df_sto, mean_values = compute_saltelli_indices(
        problem=problem,
        data=output_data,
        n_real=n_real,
        output_names=detected_output_names,
    )

    mean_valued_data = pd.concat([input_df, mean_values], axis=1).copy()
    mean_valued_data.insert(0, "seed", range(len(mean_valued_data)))
    mean_data_csv = mean_valued_data.to_csv(sep=";", index=False)

    deterministic_indices_csv = df_det.to_csv(index=False)
    stochastic_indices_csv = df_sto.to_csv(index=False) if not df_sto.empty else ""

    important_parameters = find_important_parameters(df_det)

    return SensitivityAnalysisResult(
        mean_data_csv=mean_data_csv,
        important_parameters=important_parameters,
        deterministic_indices_csv=deterministic_indices_csv,
        stochastic_indices_csv=stochastic_indices_csv,
    )
