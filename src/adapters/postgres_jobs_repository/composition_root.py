from __future__ import annotations

from dependency_injector import containers, providers

from adapters.postgres_jobs_repository.repository_reader import PostgresJobsRepositoryReader
from adapters.postgres_jobs_repository.repository_writer import (
    PostgresJobsRepository as PostgresJobsRepositoryWriter,
)
from adapters.postgres_evaluations_store.evaluations_store import (
    PostgresEvaluationsStore,
)
from use_case_contracts.ports import (
    JobsRepositoryReaderPort,
    JobsRepositoryWriterPort,
)


class PostgresJobsRepositoryContainer(containers.DeclarativeContainer):
    config = providers.Configuration()
    # Lets the reader resolve an evaluation id into one aggregated plot
    # source, so an evaluation can be visualized as a single big job. Built
    # here from the same DSN; the store is stateless, so a second instance is
    # harmless and keeps this container self-contained.
    evaluations_store = providers.Singleton(
        PostgresEvaluationsStore,
        dsn=config.dsn,
    )

    jobs_repo_reader = providers.Singleton(
        PostgresJobsRepositoryReader,
        dsn=config.dsn,
        evaluations_store=evaluations_store,
    )
    jobs_repo = jobs_repo_reader

    jobs_repo_writer = providers.Singleton(
        PostgresJobsRepositoryWriter,
        dsn=config.dsn
    )


class PostgresJobsRepositoryRoot:
    def __init__(self, container: PostgresJobsRepositoryContainer) -> None:
        self._c = container

    def jobs_repository_reader(self) -> JobsRepositoryReaderPort:
        return self._c.jobs_repo_reader()

    def jobs_repository(self) -> JobsRepositoryReaderPort:
        return self.jobs_repository_reader()

    def jobs_repository_writer(self) -> JobsRepositoryWriterPort:
        return self._c.jobs_repo_writer()
