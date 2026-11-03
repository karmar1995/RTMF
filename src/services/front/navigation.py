from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from use_case_contracts.permissions import (
    JOB_CREATE,
    JOB_READ,
    SIMULATOR_READ,
    SIMULATOR_WRITE,
    SYSTEM_DISCOVERY_MODEL_READ,
    SYSTEM_DISCOVERY_SIMULATION_READ,
    SYSTEM_DISCOVERY_TRAINING_READ,
    SYSTEM_DISCOVERY_TRAINING_WRITE,
)

PermissionMode = Literal["all", "any"]


@dataclass(frozen=True)
class SidebarItem:
    key: str
    label: str
    endpoint: str
    required_permissions: frozenset[str] = frozenset()
    permission_mode: PermissionMode = "all"
    icon: str | None = None


@dataclass(frozen=True)
class SidebarGroup:
    key: str
    label: str | None
    items: tuple[SidebarItem, ...]


SIDEBAR_GROUPS: tuple[SidebarGroup, ...] = (
    SidebarGroup(
        key="home",
        label=None,
        items=(
            SidebarItem(
                key="home",
                label="Home",
                endpoint="onIndex",
            ),
        ),
    ),
    SidebarGroup(
        key="simulators",
        label="Simulators",
        items=(
            SidebarItem(
                key="register_model",
                label="Register",
                endpoint="onRegisterModel",
                required_permissions=frozenset({SIMULATOR_WRITE}),
            ),
            SidebarItem(
                key="recent_registrations",
                label="Recent Registrations",
                endpoint="onSimulatorRegistrationMonitor",
                required_permissions=frozenset({SIMULATOR_READ}),
            ),
            SidebarItem(
                key="simulators_browse",
                label="Browse Simulators",
                endpoint="onSimulatorsBrowse",
                required_permissions=frozenset({SIMULATOR_READ}),
            ),
        ),
    ),
    SidebarGroup(
        key="simulation",
        label="Simulation",
        items=(
            SidebarItem(
                key="run_simulation",
                label="Run Simulation",
                endpoint="onRunSimulation",
                required_permissions=frozenset({SIMULATOR_READ, JOB_CREATE}),
                permission_mode="all",
            ),
            SidebarItem(
                key="sim_monitor",
                label="Monitor",
                endpoint="onSimulationMonitor",
                required_permissions=frozenset({JOB_READ}),
            ),
            SidebarItem(
                key="visualization",
                label="Visualization",
                endpoint="onSimulationVisualization",
                required_permissions=frozenset({JOB_READ}),
            ),
        ),
    ),
    SidebarGroup(
        key="system_discovery",
        label="System Discovery",
        items=(
            SidebarItem(
                key="system_discovery_train",
                label="Train Model",
                endpoint="onSystemDiscoveryTrain",
                required_permissions=frozenset({SYSTEM_DISCOVERY_TRAINING_WRITE}),
            ),
            SidebarItem(
                key="system_discovery_training_queue",
                label="Training queue",
                endpoint="onSystemDiscoveryTrainingQueue",
                required_permissions=frozenset({SYSTEM_DISCOVERY_TRAINING_READ}),
            ),
            SidebarItem(
                key="system_discovery_saved_models",
                label="Saved models",
                endpoint="onSystemDiscoverySavedModels",
                required_permissions=frozenset({SYSTEM_DISCOVERY_MODEL_READ}),
            ),
            SidebarItem(
                key="system_discovery_simulations",
                label="System Discovery Simulations",
                endpoint="onSystemDiscoverySimulations",
                required_permissions=frozenset({SYSTEM_DISCOVERY_SIMULATION_READ}),
            ),
        ),
    ),
    SidebarGroup(
        key="evaluation",
        label="Evaluation",
        items=(
            SidebarItem(
                key="evaluation_run",
                label="Run Evaluation",
                endpoint="onEvaluationRun",
                required_permissions=frozenset({SIMULATOR_READ, JOB_CREATE}),
                permission_mode="all",
            ),
            SidebarItem(
                key="evaluation_queue",
                label="Evaluation Queue",
                endpoint="onEvaluationQueue",
                required_permissions=frozenset({JOB_READ}),
            ),
        ),
    ),
)


def is_sidebar_item_visible(
    item: SidebarItem,
    granted_permissions: frozenset[str],
) -> bool:
    if not item.required_permissions:
        return True
    if item.permission_mode == "all":
        return item.required_permissions.issubset(granted_permissions)
    if item.permission_mode == "any":
        return bool(item.required_permissions & granted_permissions)
    raise ValueError(f"Unsupported sidebar permission mode: {item.permission_mode}")


def visible_sidebar_groups(
    granted_permissions: frozenset[str],
    groups: tuple[SidebarGroup, ...] = SIDEBAR_GROUPS,
) -> tuple[SidebarGroup, ...]:
    visible_groups: list[SidebarGroup] = []
    for group in groups:
        visible_items = tuple(
            item for item in group.items if is_sidebar_item_visible(item, granted_permissions)
        )
        if visible_items:
            visible_groups.append(
                SidebarGroup(key=group.key, label=group.label, items=visible_items)
            )
    return tuple(visible_groups)


def all_sidebar_permissions(
    groups: tuple[SidebarGroup, ...] = SIDEBAR_GROUPS,
) -> frozenset[str]:
    return frozenset(
        permission
        for group in groups
        for item in group.items
        for permission in item.required_permissions
    )
