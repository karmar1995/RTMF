from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

ParameterScalarValue = str | int | float | bool | None
ParameterKey = tuple[str, str]
ParameterValueList = list[ParameterScalarValue]
ParameterValuesMap = dict[ParameterKey, ParameterValueList]

def parameter_key_is_time_series(parameter: ParameterKey):
    return parameter_name_is_time_series(parameter[1])

def parameter_name_is_time_series(parameter_name: str):
    return parameter_name.endswith("_ts")

def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


@dataclass(frozen=True)
class JobResult:
    """Immutable in-memory representation of one initialized analytics job result."""

    job_id: str
    main_results: str
    input_parameters: ParameterValuesMap
    output_parameters: ParameterValuesMap
    job_root_url: str
    creation_time: datetime
    repetitions: ParameterValueList

    def __post_init__(self) -> None:
        if not self.job_id:
            raise ValueError("job_id must not be empty")
        if self.creation_time.tzinfo is None or self.creation_time.utcoffset() is None:
            raise ValueError("creation_time must be timezone-aware")
        object.__setattr__(self, "creation_time", self.creation_time.astimezone(UTC))
        object.__setattr__(self, "input_parameters", _copy_parameter_values_map(self.input_parameters))
        object.__setattr__(self, "output_parameters", _copy_parameter_values_map(self.output_parameters))


def _copy_parameter_values_map(values_map: ParameterValuesMap) -> ParameterValuesMap:
    return {
        (name, parameter_type): list(values)
        for (name, parameter_type), values in values_map.items()
    }
