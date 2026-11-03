from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SystemDiscoveryConfig:
    base_url: str
    timeout_seconds: int | None = 10
    auth_token: str | None = None
