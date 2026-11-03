from __future__ import annotations

from dataclasses import dataclass
import io

import pandas as pd
from pandas.errors import EmptyDataError

from services.analytics.core.model import (
    ParameterKey,
    ParameterScalarValue,
    ParameterValueList,
    ParameterValuesMap,
    parameter_key_is_time_series
)


@dataclass(frozen=True)
class EvaluatedParameters:
    """Input and output parameter values derived from one job result CSV."""

    input_parameters: ParameterValuesMap
    output_parameters: ParameterValuesMap


class JobResultParametersEvaluator:
    """Evaluate parameter value maps from a job result's in-memory CSV artifact."""

    def __init__(self, job_id, main_results) -> None:
        self._job_id = job_id
        self._main_results = main_results
        self._dataframe = None

    def evaluateParameters(
        self,
        input_params: list[tuple[str, str]],
        output_params: list[tuple[str, str]],
    ) -> EvaluatedParameters:
        """Load the job CSV and build input/output parameter maps."""

        dataframe = self._load_dataframe()
        input_values = self._extract_parameter_values_map(dataframe, input_params)
        output_values = self._extract_parameter_values_map(dataframe, output_params)
        return EvaluatedParameters(
            input_parameters=input_values,
            output_parameters=output_values,
        )

    def getRepetitions(self) -> ParameterValueList:
        dataframe = self._load_dataframe()

        column_name = "repetition"
        if column_name not in dataframe.columns:
            raise ValueError(
                f"Missing expected column {column_name!r} for job_id={self._job_id}"
            )

        return self._extract_column_values(dataframe[column_name])

    def _load_dataframe(self) -> pd.DataFrame:
        if self._dataframe is None:
            try:
                self._dataframe = pd.read_csv(io.StringIO(self._main_results), delimiter=';')
            except EmptyDataError as exc:
                raise ValueError(
                    f"Job result CSV is empty for job_id={self._job_id}"
                ) from exc
            if self._dataframe.empty and len(self._dataframe.columns) == 0:
                raise ValueError(f"Job result CSV has no columns for job_id={self._job_id}")
        return self._dataframe

    def _extract_parameter_values_map(
        self,
        dataframe: pd.DataFrame,
        parameters: list[ParameterKey]
    ) -> ParameterValuesMap:
        values_map: ParameterValuesMap = {}
        for parameter_key in parameters:
            parameter_name = parameter_key[0]
            if parameter_name == 'time':
                continue

            if parameter_name not in dataframe.columns:
                raise ValueError(
                    f"Missing expected column {parameter_name!r} for parameter {parameter_key!r}"
                )
            if not self._is_time_series_output(parameter_key):
                values_map[parameter_key] = self._extract_column_values(dataframe[parameter_name])
            else:
                values_map[parameter_key] = []
        return values_map

    def _extract_column_values(self, series: pd.Series) -> ParameterValueList:
        normalized_values = [
            self._normalize_scalar_value(value)
            for value in series.tolist()
        ]

        unique_values: ParameterValueList = []
        seen: set[str | int | float | bool | None] = set()

        for value in normalized_values:
            if value not in seen:
                seen.add(value)
                unique_values.append(value)

        return unique_values

    def _normalize_scalar_value(self, value: object) -> ParameterScalarValue:
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

    def _is_time_series_output(self, parameter_key: ParameterKey) -> bool:
        return parameter_key_is_time_series(parameter_key)
