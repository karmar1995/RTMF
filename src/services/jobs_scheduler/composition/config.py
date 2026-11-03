from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RestServerSettings:
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str = "JobsSchedulerService"
    rest: RestServerSettings = RestServerSettings()
