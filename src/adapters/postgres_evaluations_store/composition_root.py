from __future__ import annotations

from dependency_injector import containers, providers

from adapters.postgres_evaluations_store.evaluations_store import (
    PostgresEvaluationsStore,
)


class PostgresEvaluationsStoreContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    evaluations_store = providers.Singleton(
        PostgresEvaluationsStore,
        dsn=config.dsn,
    )


class PostgresEvaluationsStoreRoot:
    def __init__(self, container: PostgresEvaluationsStoreContainer) -> None:
        self._c = container

    def evaluations_store(self) -> PostgresEvaluationsStore:
        return self._c.evaluations_store()