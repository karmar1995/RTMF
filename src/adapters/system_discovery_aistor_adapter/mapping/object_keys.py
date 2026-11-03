from __future__ import annotations

from adapters.system_discovery_aistor_adapter.errors import (
    SystemDiscoveryAIStorInvalidObjectKeyError,
)

_TRAINING_RESULTS_PREFIX = "system-discovery/trainings"


def results_archive_key(simulation_id: str) -> str:
    normalized = _normalized_identifier(simulation_id, "simulation identifier")
    return f"system-discovery/simulations/{normalized}/results.zip"


def training_results_key(training_id: str) -> str:
    normalized = _normalized_identifier(training_id, "training identifier")
    return f"{_TRAINING_RESULTS_PREFIX}/{normalized}/results.zip"


def _normalized_identifier(identifier: str, label: str) -> str:
    normalized = identifier.strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
    ):
        raise SystemDiscoveryAIStorInvalidObjectKeyError(
            f"Unsafe System Discovery {label}"
        )
    return normalized