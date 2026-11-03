from __future__ import annotations

from dependency_injector import containers, providers

from adapters.simulators_repo_rest_adapter.config import SimulatorsRepoConfig
from adapters.simulators_repo_rest_adapter.rest_adapter import RestSimulatorsRepositoryAdapter
from use_case_contracts.ports import SimulatorRepository


class SimulatorsRepoAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    repo_config = providers.Factory(
        SimulatorsRepoConfig,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        auth_token=config.auth_token,
    )

    simulators_repo = providers.Singleton(
        RestSimulatorsRepositoryAdapter,
        config=repo_config,
        http_client=None,
    )


class SimulatorsRepoAdapterRoot:
    def __init__(self, container: SimulatorsRepoAdapterContainer) -> None:
        self._c = container

    def simulators_repository(self) -> SimulatorRepository:
        return self._c.simulators_repo()
