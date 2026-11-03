from __future__ import annotations

from typing import Dict

from services.use_case.ports import Clock
from use_case_contracts.ports import SimulatorRepository
from use_case_contracts.dtos import BuildSpec, SimulatorRegistrationResult, SimulatorBuildRecord
from use_case_contracts.messages import RegisterSimulator


def handle_register_simulator(
    message: RegisterSimulator,
    repo: SimulatorRepository,
    clock: Clock,
) -> SimulatorRegistrationResult:
    build_spec: Dict[str, object] = {
        "platform": message.platform,
        "technology": message.technology,
    }
    zip_filename = message.model_file.filename if message.model_file else ""
    zip_bytes = message.model_file.bytes if message.model_file else b""
    record = SimulatorBuildRecord(
        model_name=message.name,
        zip_filename=zip_filename,
        zip_bytes=zip_bytes,
        build_spec=BuildSpec(spec=build_spec),
        input_params=message.input_params,
        output_params=message.output_params,
        created_at=clock.now(),
    )
    registration_id = repo.register(record)
    return SimulatorRegistrationResult(
        model_name=message.name,
        version="unknown",
        build_id=registration_id,
        status=repo.registration_status(registration_id),
    )
