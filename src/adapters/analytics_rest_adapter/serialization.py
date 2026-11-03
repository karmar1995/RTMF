from __future__ import annotations

from typing import Any

from use_case_contracts.dtos import ParameterValues, ResultRef
from use_case_contracts.errors import ExternalServiceError


def serialize_result_urls(results_urls: list[ResultRef]) -> list[str]:
    return [ref.url for ref in results_urls]


def serialize_parameter_defs(parameters: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"name": name, "type": param_type} for name, param_type in parameters]


def serialize_constant_params(constants: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"name": name, "value": value} for name, value in constants]


def parse_parameter_values_list(payload: Any) -> list[ParameterValues] | None:
    if payload is None:
        return None
    if not isinstance(payload, list):
        raise ExternalServiceError("Analytics service returned invalid parameter values payload")
    result: list[ParameterValues] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ExternalServiceError("Analytics service returned invalid parameter values item")
        name = item.get("name")
        values = item.get("value", item.get("values"))
        if name is None:
            raise ExternalServiceError("Analytics service parameter values item missing name")
        if values is not None and not isinstance(values, list):
            raise ExternalServiceError("Analytics service parameter values item has invalid values field")
        result.append(ParameterValues(name=str(name), value=values))
    return result


def parse_status(payload: Any, *, field_name: str = "status") -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        value = payload.get(field_name)
        if value is None and field_name != "status":
            value = payload.get("status")
        if value is None:
            raise ExternalServiceError("Analytics service returned status payload without status field")
        return str(value)
    raise ExternalServiceError("Analytics service returned invalid status payload")


def parse_optional_message(payload: Any, *, message_field: str = "message") -> str | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        value = payload.get(message_field)
        if value is None:
            return None
        return str(value)
    raise ExternalServiceError("Analytics service returned invalid message payload")


def parse_series_id(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("series_id", "seriesId", "id"):
            value = payload.get(key)
            if value:
                return str(value)
    raise ExternalServiceError("Analytics service returned invalid series preparation payload")


def parse_supported_statistics(payload: Any) -> list[str]:
    if isinstance(payload, list):
        return [str(item) for item in payload]
    if isinstance(payload, dict):
        values = payload.get("statistics")
        if isinstance(values, list):
            return [str(item) for item in values]
    raise ExternalServiceError("Analytics service returned invalid statistics payload")
