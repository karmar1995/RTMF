from __future__ import annotations

from dependency_injector import containers, providers

from adapters.system_discovery_aistor_adapter.client import SystemDiscoveryAIStorClient
from adapters.system_discovery_aistor_adapter.config import SystemDiscoveryAIStorConfig
from adapters.system_discovery_training_results_storage.aistor_storage import (
    AIStorSystemDiscoveryTrainingResultsStorage,
)
from use_case_contracts.ports import SystemDiscoveryTrainingResultsStoragePort


class SystemDiscoveryTrainingResultsStorageContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    system_discovery_aistor_config = providers.Factory(
        SystemDiscoveryAIStorConfig,
        endpoint=config.endpoint,
        secure=config.secure,
        access_key=config.access_key,
        secret_key=config.secret_key,
        system_discovery_results_bucket=config.bucket,
    )

    system_discovery_aistor_client = providers.Singleton(
        SystemDiscoveryAIStorClient,
        config=system_discovery_aistor_config,
    )

    system_discovery_training_results_storage = providers.Singleton(
        AIStorSystemDiscoveryTrainingResultsStorage,
        client=system_discovery_aistor_client,
    )

    def storage(self) -> SystemDiscoveryTrainingResultsStoragePort:
        return self.system_discovery_training_results_storage()