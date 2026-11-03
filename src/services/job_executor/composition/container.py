from __future__ import annotations

from dependency_injector import containers, providers

from services.job_executor.aistor_adapter.results_repository import AIStorResultsRepository
from services.job_executor.aistor_adapter.matrix_source import AIStorMatrixSource
from services.job_executor.infra.simulator_subprocess import SubprocessSimulator
from services.job_executor.postgres_adapter.jobs_repository import PostgresJobsRepository
from services.job_executor.core.execute_subjob import ExecuteSubjob


class Container(containers.DeclarativeContainer):
    config = providers.Configuration(strict=True)

    simulator = providers.Singleton(
        SubprocessSimulator,
        executor_user=config.executor.user,
        executor_group=config.executor.group,
    )

    results_repository = providers.Singleton(
        AIStorResultsRepository,
        endpoint=config.aistor.endpoint,
        access_key=config.aistor.access_key,
        secret_key=config.aistor.secret_key,
        secure=config.aistor.secure,
        bucket=config.aistor.bucket,
    )

    matrix_source = providers.Singleton(
        AIStorMatrixSource,
        endpoint=config.aistor.endpoint,
        access_key=config.aistor.access_key,
        secret_key=config.aistor.secret_key,
        secure=config.aistor.secure,
    )

    jobs_repository = providers.Singleton(
        PostgresJobsRepository,
        dsn=config.postgres.jobs_repository.dsn,
    )

    executor = providers.Factory(
        ExecuteSubjob,
        simulator=simulator,
        results_repo=results_repository,
        matrix_source=matrix_source,
        jobs_repo=jobs_repository
    )
