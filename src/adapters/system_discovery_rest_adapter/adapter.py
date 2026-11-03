from __future__ import annotations

from adapters.system_discovery_rest_adapter.client import SystemDiscoveryRestClient
from use_case_contracts.dtos import (
    SystemDiscoverySimulationRequest,
    SystemDiscoverySimulationResultsArchive,
    SystemDiscoverySimulationStatus,
    SystemDiscoverySimulationSubmission,
    SystemDiscoveryTrainingRequest,
    SystemDiscoveryTrainingResultsArchive,
    SystemDiscoveryTrainingStatus,
    SystemDiscoveryTrainingSubmission,
)
from use_case_contracts.ports import SystemDiscoveryPort


class RestSystemDiscoveryAdapter(SystemDiscoveryPort):
    def __init__(self, client: SystemDiscoveryRestClient) -> None:
        self._client = client

    def submit_training(
        self,
        request: SystemDiscoveryTrainingRequest,
    ) -> SystemDiscoveryTrainingSubmission:
        return self._client.submit_training(request)

    def get_training_status(self, training_id: str) -> SystemDiscoveryTrainingStatus:
        return self._client.get_training_status(training_id)

    def download_training_results(
        self,
        training_id: str,
    ) -> SystemDiscoveryTrainingResultsArchive:
        return self._client.download_training_results(training_id)

    def submit_system_discovery_simulation(
        self,
        request: SystemDiscoverySimulationRequest,
    ) -> SystemDiscoverySimulationSubmission:
        return self._client.submit_system_discovery_simulation(request)

    def get_system_discovery_simulation_status(
        self,
        simulation_id: str,
    ) -> SystemDiscoverySimulationStatus:
        return self._client.get_system_discovery_simulation_status(simulation_id)

    def download_system_discovery_simulation_results(
        self,
        simulation_id: str,
    ) -> SystemDiscoverySimulationResultsArchive:
        return self._client.download_system_discovery_simulation_results(simulation_id)
