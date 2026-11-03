from services.simulators_repository.core.abstract_simulators_storage import AbstractSimulatorsStorage
from services.simulators_repository.core.abstract_simulator_repository import SimulatorRegistrationRequest
from services.simulators_repository.core.details.versioned_simulator_registration_request import (
    VersionedSimulatorRegistrationRequest,
)


class VersioningHelper:
    def __init__(self, simulators_storage: AbstractSimulatorsStorage) -> None:
        if simulators_storage is None:
            raise ValueError("simulators_storage is required")
        self._simulators_storage = simulators_storage

    def create_versioned_request(
        self, request: SimulatorRegistrationRequest
    ) -> VersionedSimulatorRegistrationRequest:
        existing = self._simulators_storage.get_latest_simulator_by_model_name(request.model_name)
        version = self._bump_minor_version_or_default(existing)
        return VersionedSimulatorRegistrationRequest(
            model_name=request.model_name,
            zip_filename=request.zip_filename,
            zip_bytes=request.zip_bytes,
            input_params=request.input_params,
            output_params=request.output_params,
            build=request.build,
            version=version,
        )

    def _bump_minor_version_or_default(self, simulator_data):
        if simulator_data is None:
            return "1.0.0"
        version_text = getattr(simulator_data, "version", None)
        if not isinstance(version_text, str) or not version_text.strip():
            return "1.0.0"
        parts = version_text.strip().split(".")
        if len(parts) != 3:
            return "1.0.0"
        try:
            major, minor, patch = (int(part) for part in parts)
        except ValueError:
            return "1.0.0"
        if major < 0 or minor < 0 or patch < 0:
            return "1.0.0"
        return f"{major}.{minor + 1}.0"
