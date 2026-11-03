from typing import Any
import json

from dependency_injector.errors import Error as DependencyInjectorError
from fastapi import FastAPI, Form, UploadFile, File
from pydantic import BaseModel
import uvicorn

from services.simulators_repository.core.abstract_simulator_repository import (
    AbstractSimulatorRepository,
    BuildSpec,
    ParamType,
    ParameterSpec,
    RegistrationSummary,
    SimulatorDetails,
    SimulatorSummary,
    SimulatorRegistrationRequest,
)


class ParamSpecModel(BaseModel):
    name: str
    type: str


class RegistrationRequestModel(BaseModel):
    model_name: str
    zip_filename: str
    input_params: list[ParamSpecModel] = []
    output_params: list[ParamSpecModel] = []
    build_spec: dict


class RegistrationIdsRequest(BaseModel):
    registration_ids: list[str]


class ModelIdsRequest(BaseModel):
    model_ids: list[str]


class RestRepositoryService:
    def __init__(self, repository: AbstractSimulatorRepository, config) -> None:
        if repository is None:
            raise ValueError("repository is required")
        if config is None:
            raise ValueError("config is required")
        self._repository = repository
        self._config = config
        self.app = FastAPI(title="RTMF Simulators Repository Service")
        self._register_routes()

    def _register_routes(self) -> None:
        @self.app.post("/simulators/register")
        async def register_simulator(
            model_name: str = Form(...),
            build: str = Form(...),
            zip_file: UploadFile = File(...),
            zip_filename: str | None = Form(None),
            input_params: str | None = Form(None),
            output_params: str | None = Form(None),
        ) -> dict[str, Any]:
            request = await _to_registration_request(
                model_name=model_name,
                build_json=build,
                zip_file=zip_file,
                zip_filename=zip_filename,
                input_params_json=input_params,
                output_params_json=output_params,
            )
            registration_id = self._repository.submit_simulator_registration(request)
            return {"registration_id": registration_id}

        @self.app.post("/registrations/status")
        async def get_registration_status(
                request: RegistrationIdsRequest,
        ) -> list[dict[str, Any]]:
            results = self._repository.get_registration_status(request.registration_ids)

            # TODO: Replace with real timestamps once registrations track created_at.
            hardcoded_created_at = "2026-02-24T00:00:00Z"  # ISO-8601 UTC

            return [
                {
                    "model_name": result.model_name,
                    "version": result.version,
                    "build_id": result.build_id,
                    "status": result.status,
                    "created_at": hardcoded_created_at,
                }
                for result in results
            ]

        @self.app.get("/simulators")
        async def list_simulators() -> list[dict[str, Any]]:
            results = self._repository.list_simulators()
            return [_simulator_summary_to_dict(item) for item in results]

        @self.app.post("/simulators/data")
        async def get_simulator_data(
            request: ModelIdsRequest,
        ) -> list[dict[str, Any]]:
            results = self._repository.get_simulators_details(request.model_ids)
            return [
                {
                    "model_name": result.model_name,
                    "bin_url": result.bin_url,
                    "version": result.version,
                }
                for result in results
            ]

        @self.app.post("/simulators/details")
        async def get_simulator_details(
            request: ModelIdsRequest,
        ) -> list[dict[str, Any]]:
            results = self._repository.get_simulators_details(request.model_ids)
            return [_simulator_details_to_dict(item) for item in results]

        @self.app.get("/registrations/recent")
        async def list_recent_registrations(limit: int = 100) -> list[dict[str, Any]]:
            limit_value = _clamp_limit(limit)
            results = self._repository.list_recent_registrations(limit=limit_value)
            return [_registration_summary_to_dict(item) for item in results]

    def run(self) -> None:
        host_value = _required_config_value(self._config, "host", str)
        port_value = _required_config_value(self._config, "port", int)
        config = uvicorn.Config(self.app, host=host_value, port=port_value)
        server = uvicorn.Server(config)
        server.run()


async def _to_registration_request(
    model_name: str,
    build_json: str,
    zip_file: UploadFile,
    zip_filename: str | None,
    input_params_json: str | None,
    output_params_json: str | None,
) -> SimulatorRegistrationRequest:
    build_spec = _parse_json(build_json, "build")
    input_params = _parse_params(input_params_json)
    output_params = _parse_params(output_params_json)
    zip_bytes = await zip_file.read()
    filename = zip_filename or zip_file.filename or "upload.zip"
    return SimulatorRegistrationRequest(
        model_name=model_name,
        zip_filename=filename,
        zip_bytes=zip_bytes,
        input_params=input_params,
        output_params=output_params,
        build=BuildSpec(build_spec),
    )


def _to_param_spec(item: ParamSpecModel) -> ParameterSpec:
    return ParameterSpec(name=item.name, type=ParamType(item.type))


def _parse_json(value: str, field_name: str) -> dict:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for '{field_name}'") from exc
    if not isinstance(data, dict):
        raise ValueError(f"'{field_name}' must be a JSON object")
    return data


def _parse_params(value: str | None) -> list[ParameterSpec]:
    if value is None:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON for params") from exc
    if not isinstance(data, list):
        raise ValueError("Params must be a JSON array")
    return [_to_param_spec(ParamSpecModel(**item)) for item in data]


def _required_config_value(config, name: str, cast_type):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("config name must be a non-empty string")
    value = getattr(config, name, None)
    if callable(value):
        try:
            value = value()
        except DependencyInjectorError as exc:
            raise ValueError(f"Missing required config value: {name}") from exc
    if value is None:
        raise ValueError(f"Missing required config value: {name}")
    try:
        return cast_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid config value for {name}: {value!r}") from exc


def _parameter_spec_to_dict(param: ParameterSpec) -> dict[str, Any]:
    return {"name": param.name, "type": param.type.value}


def _simulator_details_to_dict(detail: SimulatorDetails) -> dict[str, Any]:
    return {
        "model_name": detail.model_name,
        "version": detail.version,
        "created_at": detail.created_at.isoformat(),
        "bin_url": detail.bin_url,
        "build_spec": detail.build_spec,
        "input_params": (
            [_parameter_spec_to_dict(item) for item in detail.input_params]
            if detail.input_params is not None
            else None
        ),
        "output_params": (
            [_parameter_spec_to_dict(item) for item in detail.output_params]
            if detail.output_params is not None
            else None
        ),
    }


def _simulator_summary_to_dict(summary: SimulatorSummary) -> dict[str, Any]:
    return {
        "simulator_id": summary.simulator_id,
        "model_name": summary.model_name,
        "version": summary.version,
        "created_at": summary.created_at.isoformat(),
    }


def _registration_summary_to_dict(summary: RegistrationSummary) -> dict[str, Any]:
    return {
        "registration_id": summary.registration_id,
        "model_name": summary.model_name,
        "status": summary.status,
        "created_at": summary.created_at.isoformat(),
    }


def _clamp_limit(value: int) -> int:
    if value < 1:
        return 1
    if value > 1000:
        return 1000
    return value
