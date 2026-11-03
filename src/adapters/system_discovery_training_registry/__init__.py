from adapters.system_discovery_training_registry.composition_root import (
    SystemDiscoveryTrainingRegistryContainer,
)
from adapters.system_discovery_training_registry.postgres_registry import (
    PostgresSystemDiscoverySavedModelRegistry,
    PostgresSystemDiscoveryTrainingRegistry,
)

__all__ = [
    "PostgresSystemDiscoveryTrainingRegistry",
    "PostgresSystemDiscoverySavedModelRegistry",
    "SystemDiscoveryTrainingRegistryContainer",
]
