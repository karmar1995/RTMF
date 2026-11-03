from __future__ import annotations

from dependency_injector import containers, providers

from adapters.system_discovery_training_registry.postgres_registry import (
    PostgresSystemDiscoverySavedModelRegistry,
    PostgresSystemDiscoverySimulationRegistry,
    PostgresSystemDiscoveryTrainingRegistry,
)
from use_case_contracts.ports import (
    SystemDiscoverySavedModelRegistryPort,
    SystemDiscoverySimulationRegistryPort,
    SystemDiscoveryTrainingRegistryPort,
)


class SystemDiscoveryTrainingRegistryContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    system_discovery_training_registry = providers.Singleton(
        PostgresSystemDiscoveryTrainingRegistry,
        dsn=config.dsn,
    )
    system_discovery_saved_model_registry = providers.Singleton(
        PostgresSystemDiscoverySavedModelRegistry,
        dsn=config.dsn,
    )
    system_discovery_simulation_registry = providers.Singleton(
        PostgresSystemDiscoverySimulationRegistry,
        dsn=config.dsn,
    )

    def registry(self) -> SystemDiscoveryTrainingRegistryPort:
        return self.system_discovery_training_registry()

    def saved_model_registry(self) -> SystemDiscoverySavedModelRegistryPort:
        return self.system_discovery_saved_model_registry()

    def simulation_registry(self) -> SystemDiscoverySimulationRegistryPort:
        return self.system_discovery_simulation_registry()
