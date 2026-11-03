from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SystemDiscoveryAIStorConfig:
    endpoint: str
    secure: bool
    access_key: str
    secret_key: str
    system_discovery_results_bucket: str
