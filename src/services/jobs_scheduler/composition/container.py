from __future__ import annotations

from dependency_injector import containers, providers

from services.jobs_scheduler.composition.config import RestServerSettings, Settings
from services.jobs_scheduler.core.details.jobs_scheduler_controller import JobsSchedulerController
from adapters.postgres_jobs_repository.composition_root import (
    PostgresJobsRepositoryContainer,
    PostgresJobsRepositoryRoot,
)
from services.jobs_scheduler.rest_api.app import create_app
from adapters.slurm_adapter import SlurmAdapterContainer, SlurmAdapterRoot


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class Container(containers.DeclarativeContainer):
    config = providers.Configuration(strict=True)

    rest_settings = providers.Singleton(
        RestServerSettings,
        host=config.rest.host,
        port=config.rest.port.as_int(),
        reload=config.rest.reload.as_(_as_bool),
    )

    settings = providers.Singleton(
        Settings,
        service_name=providers.Object("jobs_scheduler"),
        rest=rest_settings,
    )

    slurm_adapter = providers.Container(
        SlurmAdapterContainer,
        config=config.slurm,
    )

    postgres_jobs_repository = providers.Container(
        PostgresJobsRepositoryContainer,
        config=config.postgres.jobs_repository,
    )

    jobs_scheduler_port = providers.Callable(
        lambda adapter: SlurmAdapterRoot(adapter).jobs_scheduler(),
        slurm_adapter,
    )

    jobs_repository = providers.Callable(
        lambda repository: PostgresJobsRepositoryRoot(repository).jobs_repository_writer(),
        postgres_jobs_repository,
    )

    jobs_scheduler_service = providers.Factory(
        JobsSchedulerController,
        jobs_scheduler=jobs_scheduler_port,
        jobs_repository=jobs_repository,
    )

    app = providers.Factory(
        create_app,
        controller=jobs_scheduler_service,
    )
