from __future__ import annotations

from typing import Any

from use_case_contracts.errors import BrowserLoginFailedError


def map_permissions(
    access_claims: dict[str, Any],
    *,
    permissions_client_id: str,
) -> frozenset[str]:
    resource_access = access_claims.get("resource_access")
    if resource_access is None:
        return frozenset()
    if not isinstance(resource_access, dict):
        raise BrowserLoginFailedError("Login failed.")
    client_access = resource_access.get(permissions_client_id)
    if client_access is None:
        return frozenset()
    if not isinstance(client_access, dict):
        raise BrowserLoginFailedError("Login failed.")
    roles = client_access.get("roles")
    if roles is None:
        return frozenset()
    if not isinstance(roles, list):
        raise BrowserLoginFailedError("Login failed.")
    return frozenset(role for role in roles if isinstance(role, str) and role in _known_permissions())


def _known_permissions() -> frozenset[str]:
    return frozenset(
        {
            "system.read",
            "simulator.write",
            "simulator.read",
            "job.create",
            "job.read",
            "simulation.read",
            "system_discovery.training.write",
            "system_discovery.training.read",
            "system_discovery.model.write",
            "system_discovery.model.read",
            "system_discovery.simulation.write",
            "system_discovery.simulation.read",
        }
    )
