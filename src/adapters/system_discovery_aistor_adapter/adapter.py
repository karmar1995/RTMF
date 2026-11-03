from __future__ import annotations

from adapters.system_discovery_aistor_adapter.client import SystemDiscoveryAIStorClient
from adapters.system_discovery_aistor_adapter.mapping import results_archive_key
from use_case_contracts.dtos import SystemDiscoveryStoredResultsArchive
from use_case_contracts.ports import SystemDiscoveryAIStorPort


class SystemDiscoveryAIStorAdapter(SystemDiscoveryAIStorPort):
    def __init__(self, client: SystemDiscoveryAIStorClient) -> None:
        self._client = client

    def upload_results_archive(
        self,
        simulation_id: str,
        content: bytes,
    ) -> SystemDiscoveryStoredResultsArchive:
        key = results_archive_key(simulation_id)
        self._client.upload_bytes(
            key=key,
            content=content,
            content_type="application/zip",
        )
        return SystemDiscoveryStoredResultsArchive(
            simulation_id=simulation_id,
            storage_reference=key,
        )

    def download_results_archive(self, simulation_id: str) -> bytes:
        return self._client.download_bytes(key=results_archive_key(simulation_id))
