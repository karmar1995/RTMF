from __future__ import annotations

import csv
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from SALib.analyze import sobol

_SKIP_COLS = {"seed", "realization_id"}
_DEFAULT_BOUNDS: list[float] = [-2.12, 2.12]


class FakeSensitivityAnalysis:
    def __init__(
        self,
        problem: dict[str, object] | None = None,
        output_mean_data_filename: str = "stochastic_input_for_optimization.csv",
        important_parameters_filename: str = "important_parameters.pkl",
    ) -> None:
        self.problem = problem
        self.output_mean_data_filename = output_mean_data_filename
        self.important_parameters_filename = important_parameters_filename

    def analyze_results(
        self,
        outputs_filename: str | Path,
        n_real: int,
        output_mean_data_filename: str | None = None,
        important_parameters_filename: str | None = None,
        output_names: list[str] | None = None,
        output_det_filename: str = "det_S_ind.csv",
        output_sto_filename: str = "sto_S_ind.csv",
    ) -> dict[str, Path]:
        outputs_path = Path(outputs_filename)
        output_dir = outputs_path.parent
        mean_data_path = output_dir / (
            output_mean_data_filename or self.output_mean_data_filename
        )
        important_parameters_path = output_dir / (
            important_parameters_filename or self.important_parameters_filename
        )
        output_det_path = output_dir / output_det_filename
        output_sto_path = output_dir / output_sto_filename

        data = self._read_csv_auto(outputs_path)

        if self.problem is None:
            problem = self._infer_problem_from_csv(data)
        else:
            problem = self._prepare_problem(self.problem)

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

        df_det, df_sto, mean_values = self._compute_saltelli_indices(
            problem=problem,
            data=output_data,
            n_real=n_real,
            output_names=detected_output_names,
        )

        mean_valued_data = pd.concat([input_df, mean_values], axis=1).copy()
        mean_valued_data.insert(0, "seed", range(len(mean_valued_data)))
        mean_valued_data.to_csv(mean_data_path, sep=";", index=False)

        df_det.to_csv(output_det_path, index=False)
        if not df_sto.empty:
            df_sto.to_csv(output_sto_path, index=False)

        important_parameters = self._find_important_parameters(df_det)
        with important_parameters_path.open("wb") as output_file:
            pickle.dump(important_parameters, output_file)

        return {
            "mean_data": mean_data_path,
            "important_parameters": important_parameters_path,
            "deterministic_indices": output_det_path,
            "stochastic_indices": output_sto_path,
        }

    def _infer_problem_from_csv(self, data: pd.DataFrame) -> dict[str, object]:
        input_names = [
            col for col in data.columns
            if col not in _SKIP_COLS and not col.startswith("value")
        ]
        return {
            "num_vars": len(input_names),
            "names": input_names,
            "bounds": [list(_DEFAULT_BOUNDS) for _ in input_names],
            "skip": list(_SKIP_COLS),
        }

    def _prepare_problem(self, problem: dict[str, object]) -> dict[str, object]:
        problem = dict(problem)
        problem["num_vars"] = len(problem["names"])
        return problem

    def _read_csv_auto(self, path: Path) -> pd.DataFrame:
        try:
            with path.open("r", encoding="utf-8") as input_file:
                sample = input_file.read(8192)
                input_file.seek(0)
                dialect = csv.Sniffer().sniff(sample)
            data = pd.read_csv(path, sep=dialect.delimiter)
            if len(data.columns) > 1:
                return data
        except Exception:
            pass

        raise ValueError(f"Could not auto-detect CSV format for {path}.")

    def _compute_saltelli_indices(
        self,
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

    def _find_important_parameters(
        self, df_det: pd.DataFrame
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
