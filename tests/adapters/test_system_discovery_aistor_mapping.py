from __future__ import annotations

import pytest

from adapters.system_discovery_aistor_adapter import SystemDiscoveryAIStorInvalidObjectKeyError
from adapters.system_discovery_aistor_adapter.mapping.object_keys import (
    results_archive_key,
    training_results_key,
)


def test_results_archive_key_follows_simulation_results_subfolder() -> None:
    assert (
        results_archive_key("sim-1")
        == "system-discovery/simulations/sim-1/results.zip"
    )


def test_training_results_key_follows_training_results_subfolder() -> None:
    assert (
        training_results_key("train-1")
        == "system-discovery/trainings/train-1/results.zip"
    )


@pytest.mark.parametrize("identifier", ["", ".", "..", "a/b", "a\\b", "  "])
def test_unsafe_identifiers_are_rejected(identifier) -> None:
    with pytest.raises(SystemDiscoveryAIStorInvalidObjectKeyError):
        training_results_key(identifier)
    with pytest.raises(SystemDiscoveryAIStorInvalidObjectKeyError):
        results_archive_key(identifier)


def test_training_results_key_trims_whitespace() -> None:
    assert training_results_key("  train-1  ") == training_results_key("train-1")