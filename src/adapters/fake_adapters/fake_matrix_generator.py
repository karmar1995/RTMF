from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from SALib.sample import sobol as sobol_sample

from use_case_contracts.dtos import (
    GeneratedMatrixFile,
    MatrixParameterDefinition,
    SensitivityAnalysisParameter,
)
from use_case_contracts.ports import MatrixGenerationPort


_SATELLI_SAMPLE_SIZE = 128
_CALC_SECOND_ORDER = False


class FakeMatrixGenerator(MatrixGenerationPort):
    def __init__(self, output_root: Path | None = None) -> None:
        self._output_root = output_root or Path(".")

    def generate_linear_combinations(
        self,
        matrix_id: str,
        repetitions: int,
        parameter_definitions: list[MatrixParameterDefinition],
        fixed_params: dict[str, str],
        sweep_params: dict[str, list[str]],
    ) -> GeneratedMatrixFile:
        return self.generate_satelli_matrix_combinations(
            matrix_id=matrix_id,
            repetitions=repetitions,
            parameter_definitions=parameter_definitions,
            fixed_params=fixed_params,
            sweep_params=sweep_params,
        )

    def generate_satelli_matrix_combinations(
        self,
        matrix_id: str,
        repetitions: int,
        parameter_definitions: list[MatrixParameterDefinition],
        fixed_params: dict[str, str],
        sweep_params: dict[str, list[str]],
        sample_size: int = 128,
        seed: int | None = None,
    ) -> GeneratedMatrixFile:
        matrix_path = self._output_root / "matrices" / f"{matrix_id}.txt"
        matrix_path.parent.mkdir(parents=True, exist_ok=True)

        matrix_df = self._generate_gsa_matrix(
            parameter_definitions=parameter_definitions,
            fixed_params=fixed_params,
            sweep_params=sweep_params,
            sample_size=sample_size,
            repetitions=repetitions,
            calc_second_order=_CALC_SECOND_ORDER,
            seed=seed,
        )
        matrix_path.write_text(
            self._build_matrix_text(
                matrix_df=matrix_df,
                repetitions=repetitions,
                parameter_definitions=parameter_definitions,
            ),
            encoding="utf-8",
        )

        return GeneratedMatrixFile(matrix_url=str(matrix_path))

    def generate_sensitivity_analysis(
        self,
        matrix_id: str,
        parameters: list[SensitivityAnalysisParameter],
        sample_size: int,
        calc_second_order: bool,
        round_to_int: bool,
    ) -> GeneratedMatrixFile:
        raise NotImplementedError(
            "Sensitivity-analysis fake generation is not implemented yet."
        )

    def upload_matrix(
        self,
        matrix_id: str,
        matrix_text: str,
    ) -> GeneratedMatrixFile:
        matrix_path = self._output_root / "matrices" / f"{matrix_id}.txt"
        matrix_path.parent.mkdir(parents=True, exist_ok=True)
        matrix_path.write_text(matrix_text, encoding="utf-8")
        return GeneratedMatrixFile(matrix_url=str(matrix_path))

    def _build_sweep_problem(
        self,
        sweep_params: dict[str, list[str]],
    ) -> dict[str, object]:
        parameter_names = list(sweep_params)
        return {
            "num_vars": len(parameter_names),
            "names": parameter_names,
            "bounds": [
                self._resolve_sweep_parameter_bounds(
                    parameter_name=name, sweep_params=sweep_params
                )
                for name in parameter_names
            ],
        }

    def _resolve_sweep_parameter_bounds(
        self,
        parameter_name: str,
        sweep_params: dict[str, list[str]],
    ) -> list[float]:
        values = [
            self._parse_numeric_value(value, parameter_name=parameter_name)
            for value in sweep_params[parameter_name]
        ]
        lower_bound, upper_bound = min(values), max(values)
        if lower_bound == upper_bound:
            raise ValueError(
                f"sweep parameter '{parameter_name}' must have different "
                f"lower and upper bounds"
            )
        return [lower_bound, upper_bound]

    def _parse_numeric_value(self, value: str, *, parameter_name: str) -> float:
        try:
            return float(value)
        except ValueError as error:
            raise ValueError(
                f"parameter '{parameter_name}' must be numeric "
                f"for fake Satelli generation"
            ) from error

    def _generate_gsa_matrix(
        self,
        parameter_definitions: list[MatrixParameterDefinition],
        fixed_params: dict[str, str],
        sweep_params: dict[str, list[str]],
        sample_size: int,
        repetitions: int,
        calc_second_order: bool,
        seed: int | None = None,
    ) -> pd.DataFrame:
        fixed_df = self._build_fixed_params_frame(
            fixed_params=fixed_params,
            parameter_definitions=parameter_definitions,
        )
        if not sweep_params:
            return self._repeat_frame(fixed_df, repetitions)

        problem = self._build_sweep_problem(sweep_params=sweep_params)
        samples = sobol_sample.sample(
            problem, sample_size, calc_second_order=calc_second_order, seed=seed
        )

        sweep_df = pd.DataFrame(samples, columns=problem["names"])

        parameter_types = {
            p.name: p.type.strip().lower() for p in parameter_definitions
        }
        for col in sweep_df.columns:
            if parameter_types.get(col) == "int":
                sweep_df[col] = np.round(sweep_df[col]).astype(int)

        fixed_df = pd.concat([fixed_df] * len(sweep_df), ignore_index=True)

        return pd.concat([fixed_df, sweep_df], axis=1)

    def _build_fixed_params_frame(
        self,
        fixed_params: dict[str, str],
        parameter_definitions: list[MatrixParameterDefinition],
    ) -> pd.DataFrame:
        parameter_order = [p.name for p in parameter_definitions]
        ordered_fixed_params = {
            name: self._parse_numeric_value(fixed_params[name], parameter_name=name)
            for name in parameter_order
            if name in fixed_params
        }
        extra_fixed_params = {
            name: self._parse_numeric_value(value, parameter_name=name)
            for name, value in fixed_params.items()
            if name not in ordered_fixed_params
        }
        return pd.DataFrame([{**ordered_fixed_params, **extra_fixed_params}])

    def _repeat_frame(self, frame: pd.DataFrame, repetitions: int) -> pd.DataFrame:
        if repetitions <= 1:
            return frame
        return pd.concat([frame] * repetitions, ignore_index=True)

    def _build_matrix_text(
        self,
        matrix_df: pd.DataFrame,
        repetitions: int,
        parameter_definitions: list[MatrixParameterDefinition] | None = None,
    ) -> str:
        parameter_types: dict[str, str] = {}
        if parameter_definitions:
            parameter_types = {
                p.name: p.type.strip().lower() for p in parameter_definitions
            }
        col_names = list(matrix_df.columns)
        rows = []
        for row in matrix_df.itertuples(index=False, name=None):
            parts = []
            for col_idx, value in enumerate(row):
                col_name = col_names[col_idx] if col_idx < len(col_names) else ""
                if parameter_types.get(col_name) == "int":
                    parts.append(str(int(round(float(value)))))
                else:
                    parts.append(str(value))
            rows.append(" ".join(parts))
        return f"{repetitions}\n" + "\n".join(rows) + "\n"
