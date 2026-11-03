"""Core domain models."""

from services.analytics.core.model.data_series import DataSeries, DataSeriesXValue, MultiDataSeries
from services.analytics.core.model.job_result import (
    JobResult,
    ParameterKey,
    ParameterScalarValue,
    ParameterValueList,
    ParameterValuesMap,
    parameter_key_is_time_series,
    parameter_name_is_time_series
)

__all__ = [
    "DataSeries",
    "DataSeriesXValue",
    "MultiDataSeries",
    "JobResult",
    "ParameterKey",
    "ParameterScalarValue",
    "ParameterValueList",
    "ParameterValuesMap",
    "parameter_key_is_time_series",
    "parameter_name_is_time_series"
]
