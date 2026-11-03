from __future__ import annotations

from decimal import Decimal, InvalidOperation
from itertools import product
from numbers import Real

import numpy as np
from SALib.sample import saltelli

from services.matrix_generation.core.dto import (
    GenerateLinearCombinationsRequest,
    GenerateSensitivityAnalysisRequest,
    GeneratedMatrixFile,
    MATRIX_CONTENT_TYPE,
    SensitivityAnalysisParameter,
    UploadMatrixRequest,
)
from services.matrix_generation.core.errors import (
    InvalidMatrixGenerationRequest,
    MatrixUploadFailed,
    SatelliCombinationsGenerationFailed,
    SensitivityAnalysisGenerationFailed,
)
from services.matrix_generation.core.ports import MatrixGenerationPort, MatrixUploader


class MatrixGenerationService(MatrixGenerationPort):
    def __init__(
        self,
        matrix_uploader: MatrixUploader,
        matrix_bucket: str,
        matrix_output_prefix: str = "",
    ) -> None:
        self._matrix_uploader = matrix_uploader
        self._matrix_bucket = matrix_bucket
        self._matrix_output_prefix = matrix_output_prefix

    def generate_linear_combinations(
        self,
        request: GenerateLinearCombinationsRequest,
    ) -> GeneratedMatrixFile:
        if request.repetitions < 1:
            raise InvalidMatrixGenerationRequest("repetitions must be greater than or equal to 1")

        fixed_params = request.fixed_params or {}
        sweep_params = request.sweep_params or {}
        overlapping_params = set(fixed_params) & set(sweep_params)
        if overlapping_params:
            raise InvalidMatrixGenerationRequest(
                f"parameters cannot be both fixed and sweep: {', '.join(sorted(overlapping_params))}"
            )

        parameter_order = [definition.name for definition in request.parameter_definitions]
        parameter_types = {
            definition.name: definition.type
            for definition in request.parameter_definitions
        }
        known_parameters = set(parameter_types)

        unknown_params = (set(fixed_params) | set(sweep_params)) - known_parameters
        if unknown_params:
            raise InvalidMatrixGenerationRequest(
                f"unknown parameters: {', '.join(sorted(unknown_params))}"
            )

        for parameter_name, sweep_values in sweep_params.items():
            if not sweep_values:
                raise InvalidMatrixGenerationRequest(
                    f"sweep parameter '{parameter_name}' must contain at least one value"
                )

        missing_params = [
            parameter_name
            for parameter_name in parameter_order
            if parameter_name not in fixed_params and parameter_name not in sweep_params
        ]
        if missing_params:
            raise InvalidMatrixGenerationRequest(
                f"missing values for parameters: {', '.join(missing_params)}"
            )

        sweep_names = [name for name in parameter_order if name in sweep_params]
        sweep_lists = [
            [
                _serialize_value(parameter_types[name], raw_value, parameter_name=name)
                for raw_value in sweep_params[name]
            ]
            for name in sweep_names
        ]
        serialized_fixed_params = {
            name: _serialize_value(parameter_types[name], value, parameter_name=name)
            for name, value in fixed_params.items()
        }

        combinations = product(*sweep_lists) if sweep_lists else [()]
        rows: list[str] = []
        for combination in combinations:
            sweep_values_by_name = dict(zip(sweep_names, combination, strict=True))
            row_values: list[str] = []
            for name in parameter_order:
                if name in sweep_values_by_name:
                    row_values.append(sweep_values_by_name[name])
                else:
                    row_values.append(serialized_fixed_params[name])
            rows.append(" ".join(row_values))

        deduped_rows = _dedupe_rows(rows)
        if not deduped_rows:
            raise InvalidMatrixGenerationRequest("no matrix rows were generated")

        matrix_text = _build_matrix_text(request.repetitions, deduped_rows)
        return self._upload_generated_matrix(matrix_id=request.matrix_id, matrix_text=matrix_text)

    def generate_sensitivity_analysis(
        self,
        request: GenerateSensitivityAnalysisRequest,
    ) -> GeneratedMatrixFile:
        if request.sample_size < 1:
            raise InvalidMatrixGenerationRequest("sample_size must be greater than or equal to 1")
        if not request.parameters:
            raise InvalidMatrixGenerationRequest("parameters must not be empty")

        _validate_sensitivity_parameters(request.parameters)

        problem = {
            "num_vars": len(request.parameters),
            "names": [parameter.name for parameter in request.parameters],
            "bounds": [
                [parameter.lower_bound, parameter.upper_bound]
                for parameter in request.parameters
            ],
        }

        try:
            sampled_values = saltelli.sample(
                problem,
                request.sample_size,
                calc_second_order=request.calc_second_order,
            )
        except Exception as error:
            raise SensitivityAnalysisGenerationFailed(
                "sensitivity analysis matrix generation failed"
            ) from error

        matrix_text = _build_sensitivity_analysis_matrix_text(
            sampled_values=sampled_values,
            round_to_int=request.round_to_int,
        )
        return self._upload_generated_matrix(matrix_id=request.matrix_id, matrix_text=matrix_text)

    def generate_satelli_matrix_combinations(
        self,
        request: GenerateLinearCombinationsRequest,
    ) -> GeneratedMatrixFile:
        if request.repetitions < 1:
            raise InvalidMatrixGenerationRequest("repetitions must be greater than or equal to 1")

        fixed_params = request.fixed_params or {}
        sweep_params = request.sweep_params or {}
        overlapping_params = set(fixed_params) & set(sweep_params)
        if overlapping_params:
            raise InvalidMatrixGenerationRequest(
                f"parameters cannot be both fixed and sweep: {', '.join(sorted(overlapping_params))}"
            )

        parameter_order = [definition.name for definition in request.parameter_definitions]
        parameter_types = {
            definition.name: definition.type
            for definition in request.parameter_definitions
        }
        known_parameters = set(parameter_types)

        unknown_params = (set(fixed_params) | set(sweep_params)) - known_parameters
        if unknown_params:
            raise InvalidMatrixGenerationRequest(
                f"unknown parameters: {', '.join(sorted(unknown_params))}"
            )

        missing_params = [
            parameter_name
            for parameter_name in parameter_order
            if parameter_name not in fixed_params and parameter_name not in sweep_params
        ]
        if missing_params:
            raise InvalidMatrixGenerationRequest(
                f"missing values for parameters: {', '.join(missing_params)}"
            )

        serialized_fixed_params = {
            name: _serialize_value(parameter_types[name], value, parameter_name=name)
            for name, value in fixed_params.items()
        }

        if not sweep_params:
            fixed_row = " ".join(serialized_fixed_params[name] for name in parameter_order)
            matrix_text = _build_matrix_text(request.repetitions, [fixed_row])
            return self._upload_generated_matrix(matrix_id=request.matrix_id, matrix_text=matrix_text)

        sweep_names = list(sweep_params)
        sweep_values = {
            name: [
                float(v)
                for v in sweep_params[name]
            ]
            for name in sweep_names
        }

        problem = {
            "num_vars": len(sweep_names),
            "names": sweep_names,
            "bounds": [
                [min(sweep_values[name]), max(sweep_values[name])]
                for name in sweep_names
            ],
        }

        calc_second_order = False

        try:
            if request.seed is not None:
                sampled_values = saltelli.sample(
                    problem,
                    request.sample_size,
                    calc_second_order=calc_second_order,
                    seed=request.seed,
                )
            else:
                sampled_values = saltelli.sample(
                    problem,
                    request.sample_size,
                    calc_second_order=calc_second_order,
                )
        except Exception as error:
            raise SatelliCombinationsGenerationFailed(
                f"satelli matrix combination generation failed: {error}"
            ) from error

        rows: list[str] = []
        for sample_row in sampled_values:
            row_values: list[str] = []
            for name in parameter_order:
                if name in serialized_fixed_params:
                    row_values.append(serialized_fixed_params[name])
                else:
                    idx = sweep_names.index(name)
                    raw = sample_row[idx]
                    ptype = parameter_types[name].strip().lower()
                    if ptype == "int":
                        row_values.append(str(int(round(raw))))
                    else:
                        row_values.append(_format_decimal(Decimal(str(raw))))
            rows.append(" ".join(row_values))

        if not rows:
            raise InvalidMatrixGenerationRequest("no matrix rows were generated")

        matrix_text = _build_matrix_text(request.repetitions, rows)
        return self._upload_generated_matrix(matrix_id=request.matrix_id, matrix_text=matrix_text)

    def upload_matrix(
        self,
        request: UploadMatrixRequest,
    ) -> GeneratedMatrixFile:
        if not request.matrix_text.strip():
            raise InvalidMatrixGenerationRequest("matrix_text must not be empty")

        return self._upload_generated_matrix(
            matrix_id=request.matrix_id,
            matrix_text=request.matrix_text,
        )

    def _upload_generated_matrix(
        self,
        *,
        matrix_id: str,
        matrix_text: str,
    ) -> GeneratedMatrixFile:
        matrix_key = _build_matrix_object_key(
            output_prefix=self._matrix_output_prefix,
            filename=f"{matrix_id}.txt",
        )

        try:
            upload_result = self._matrix_uploader.upload_text(
                bucket=self._matrix_bucket,
                key=matrix_key,
                content=matrix_text,
                content_type=MATRIX_CONTENT_TYPE,
            )
        except Exception as error:
            raise MatrixUploadFailed("matrix upload failed") from error

        return GeneratedMatrixFile(matrix_url=upload_result.url)


def _serialize_value(parameter_type: str, value: object, *, parameter_name: str) -> str:
    normalized_type = parameter_type.strip().lower()
    raw_value = str(value).strip()

    if normalized_type in {"str", "string"}:
        if not raw_value:
            raise InvalidMatrixGenerationRequest(
                f"parameter '{parameter_name}' cannot be empty"
            )
        if " " in raw_value:
            raise InvalidMatrixGenerationRequest(
                f"parameter '{parameter_name}' cannot contain spaces"
            )
        return raw_value

    if normalized_type == "bool":
        lowered = raw_value.lower()
        if lowered in {"true", "1", "yes"}:
            return "true"
        if lowered in {"false", "0", "no"}:
            return "false"
        raise InvalidMatrixGenerationRequest(
            f"parameter '{parameter_name}' must be a valid bool"
        )

    if normalized_type == "int":
        try:
            return str(int(raw_value))
        except ValueError as error:
            raise InvalidMatrixGenerationRequest(
                f"parameter '{parameter_name}' must be a valid int"
            ) from error

    if normalized_type == "float":
        try:
            return _format_decimal(Decimal(raw_value))
        except InvalidOperation as error:
            raise InvalidMatrixGenerationRequest(
                f"parameter '{parameter_name}' must be a valid float"
            ) from error

    raise InvalidMatrixGenerationRequest(
        f"parameter '{parameter_name}' uses unsupported type '{parameter_type}'"
    )


def _format_decimal(value: Decimal) -> str:
    if value.is_zero():
        return "0"

    normalized = format(value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _dedupe_rows(rows: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped_rows: list[str] = []
    for row in rows:
        if row in seen:
            continue
        seen.add(row)
        deduped_rows.append(row)
    return deduped_rows


def _build_matrix_text(repetitions: int, rows: list[str]) -> str:
    return f"{repetitions}\n" + "\n".join(rows) + "\n"


def _validate_sensitivity_parameters(
    parameters: list[SensitivityAnalysisParameter],
) -> None:
    seen_names: set[str] = set()
    for parameter in parameters:
        name = parameter.name.strip()
        if not name:
            raise InvalidMatrixGenerationRequest("parameter names must be non-empty")
        if name in seen_names:
            raise InvalidMatrixGenerationRequest(
                f"duplicate sensitivity-analysis parameter name: {name}"
            )
        seen_names.add(name)
        if (
            isinstance(parameter.lower_bound, bool)
            or isinstance(parameter.upper_bound, bool)
            or not isinstance(parameter.lower_bound, Real)
            or not isinstance(parameter.upper_bound, Real)
        ):
            raise InvalidMatrixGenerationRequest(
                f"parameter '{name}' bounds must be numeric"
            )
        if parameter.lower_bound > parameter.upper_bound:
            raise InvalidMatrixGenerationRequest(
                f"parameter '{name}' lower_bound must be less than or equal to upper_bound"
            )


def _build_sensitivity_analysis_matrix_text(
    *,
    sampled_values: np.ndarray,
    round_to_int: bool,
) -> str:
    if sampled_values.size == 0:
        raise SensitivityAnalysisGenerationFailed(
            "sensitivity analysis did not produce any samples"
        )

    if round_to_int:
        discrete_values = np.round(sampled_values).astype(int)
        rows = [
            " ".join(str(int(value)) for value in row)
            for row in discrete_values
        ]
    else:
        rows = [
            " ".join(_format_decimal(Decimal(str(value))) for value in row)
            for row in sampled_values
        ]

    return "\n".join(rows) + "\n"


def _build_matrix_object_key(*, output_prefix: str, filename: str) -> str:
    normalized_prefix = output_prefix.strip().strip("/")
    return f"{normalized_prefix}/{filename}"
