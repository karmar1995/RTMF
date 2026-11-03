from dataclasses import dataclass

from services.simulators_repository.core.abstract_simulator_repository import SimulatorRegistrationRequest


@dataclass(frozen=True)
class VersionedSimulatorRegistrationRequest(SimulatorRegistrationRequest):
    version: str
