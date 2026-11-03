from __future__ import annotations

import dataclasses
import json
import pathlib
from datetime import date, datetime
from enum import Enum
from typing import Any

from use_case_contracts.dtos import (
    BuildSpec,
    ParameterSpec,
    RegistrationDetails,
    RegistrationSummary,
    SimulatorDetails,
    SimulatorSummary,
)


def serialize_build_spec(build_spec: BuildSpec | None) -> str:
    if build_spec is None:
        return "{}"
    return json.dumps(_to_jsonable(build_spec.spec))


def serialize_params(params: list[ParameterSpec] | None) -> str:
    if not params:
        return "[]"
    payload = [
        {"name": p.name, "type": str(getattr(p.type, "value", p.type))}
        for p in params
    ]
    return json.dumps(payload)


def parse_simulator_summary(payload: dict[str, Any]) -> SimulatorSummary:
    return SimulatorSummary(
        simulator_id=str(payload.get("simulator_id", "")),
        model_name=str(payload.get("model_name", "")),
        version=str(payload.get("version", "")),
        created_at=str(payload.get("created_at", "")),
    )


def parse_simulator_details(payload: dict[str, Any]) -> SimulatorDetails:
    build_spec = payload.get("build_spec")
    return SimulatorDetails(
        model_name=str(payload.get("model_name", "")),
        version=str(payload.get("version", "")),
        created_at=str(payload.get("created_at", "")),
        bin_url=str(payload.get("bin_url", "")),
        build_spec=BuildSpec(spec=build_spec) if isinstance(build_spec, dict) else None,
        input_params=_parse_params(payload.get("input_params")),
        output_params=_parse_params(payload.get("output_params")),
    )


def parse_registration_summary(payload: dict[str, Any]) -> RegistrationSummary:
    return RegistrationSummary(
        registration_id=str(payload.get("registration_id", "")),
        model_name=str(payload.get("model_name", "")),
        status=str(payload.get("status", "")),
        created_at=str(payload.get("created_at", "")),
    )


def parse_registration_details(payload: dict[str, Any]) -> RegistrationDetails:
    return RegistrationDetails(
        registration_id=str(payload.get("registration_id", "")),
        model_name=str(payload.get("model_name", "")),
        status=str(payload.get("status", "")),
        created_at=str(payload.get("created_at", "")),
        version=_optional_str(payload.get("version")),
        build_id=_optional_str(payload.get("build_id")),
    )


def _parse_params(raw: Any) -> list[ParameterSpec] | None:
    if not raw:
        return None
    params = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name")
            p_type = item.get("type")
        else:
            name = getattr(item, "name", None)
            p_type = getattr(item, "type", None)
        if name and p_type:
            params.append(ParameterSpec(name=str(name), type=p_type))
    return params or None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, pathlib.Path):
        return str(value)
    if dataclasses.is_dataclass(value):
        return _to_jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump())
    if hasattr(value, "dict"):
        return _to_jsonable(value.dict())
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
