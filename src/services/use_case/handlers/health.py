from __future__ import annotations

from use_case_contracts.dtos import HealthStatus
from use_case_contracts.messages import HealthCheck


def handle_health_check(_: HealthCheck) -> HealthStatus:
    return HealthStatus(status="ok")
