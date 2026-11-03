from __future__ import annotations

from typing import Any

from adapters.system_discovery_rest_adapter.errors import SystemDiscoveryProtocolError
from use_case_contracts.dtos import (
    SystemDiscoveryParameters,
    SystemDiscoverySimulationStatus,
    SystemDiscoverySimulationSubmission,
    SystemDiscoveryTrainingStatus,
    SystemDiscoveryTrainingSubmission,
)


def serialize_system_parameters(parameters: SystemDiscoveryParameters) -> str:
    wire_parameters = {
        "nlags-x": (
            [list(lags) for lags in parameters.nlags_x]
            if parameters.nlags_x is not None
            else None
        ),
        "nlags-y": parameters.nlags_y,
        "basis": parameters.basis,
        "degree": parameters.degree,
        "model": parameters.model,
    }
    return repr(wire_parameters)


def serialize_initial_conditions(values: tuple[float, ...]) -> str:
    return " ".join(str(value) for value in values)


def parse_training_submission(payload: Any) -> SystemDiscoveryTrainingSubmission:
    if not isinstance(payload, dict):
        raise SystemDiscoveryProtocolError(
            "System Discovery service returned invalid training submission payload"
        )
    training_id = payload.get("sd_training_id")
    status = payload.get("status")
    if training_id is None or status is None:
        raise SystemDiscoveryProtocolError(
            "System Discovery service returned training submission payload without required fields"
        )
    return SystemDiscoveryTrainingSubmission(
        training_id=str(training_id),
        status=str(status),
    )


def parse_training_status(payload: Any, *, requested_training_id: str) -> SystemDiscoveryTrainingStatus:
    if not isinstance(payload, dict):
        raise SystemDiscoveryProtocolError(
            "System Discovery service returned invalid training status payload"
        )
    status = payload.get("status")
    training_status = payload.get("training_status")
    evaluation_status = payload.get("evaluation_status")
    if status is None or training_status is None or evaluation_status is None:
        raise SystemDiscoveryProtocolError(
            "System Discovery service returned training status payload without required fields"
        )
    error = payload.get("error")
    return SystemDiscoveryTrainingStatus(
        training_id=requested_training_id,
        status=str(status),
        training_status=str(training_status),
        evaluation_status=str(evaluation_status),
        error=None if error is None else str(error),
    )


def parse_simulation_submission(payload: Any) -> SystemDiscoverySimulationSubmission:
    if not isinstance(payload, dict):
        raise SystemDiscoveryProtocolError(
            "System Discovery service returned invalid simulation submission payload"
        )
    simulation_id = payload.get("sd_simulation_id")
    status = payload.get("status")
    if simulation_id is None or status is None:
        raise SystemDiscoveryProtocolError(
            "System Discovery service returned simulation submission payload without required fields"
        )
    return SystemDiscoverySimulationSubmission(
        simulation_id=str(simulation_id),
        status=str(status),
    )


def parse_simulation_status(payload: Any) -> SystemDiscoverySimulationStatus:
    if not isinstance(payload, dict):
        raise SystemDiscoveryProtocolError(
            "System Discovery service returned invalid simulation status payload"
        )
    simulation_id = payload.get("sd_simulation_id")
    status = payload.get("status")
    if simulation_id is None or status is None:
        raise SystemDiscoveryProtocolError(
            "System Discovery service returned simulation status payload without required fields"
        )
    error = payload.get("error")
    return SystemDiscoverySimulationStatus(
        simulation_id=str(simulation_id),
        status=str(status),
        error=None if error is None else str(error),
    )
