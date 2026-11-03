from __future__ import annotations

from dependency_injector import containers, providers

from adapters.jobs_scheduler_rest_adapter.adapter import RestJobsSchedulerAdapter
from adapters.jobs_scheduler_rest_adapter.config import JobsSchedulerConfig
from use_case_contracts.ports import JobsSchedulerPort


class JobsSchedulerAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    jobs_scheduler_config = providers.Factory(
        JobsSchedulerConfig,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        auth_token=config.auth_token,
    )

    jobs_scheduler_port = providers.Singleton(
        RestJobsSchedulerAdapter,
        config=jobs_scheduler_config,
        http_client=None,
    )


class JobsSchedulerAdapterRoot:
    def __init__(self, container: JobsSchedulerAdapterContainer) -> None:
        self._c = container

    def jobs_scheduler_port(self) -> JobsSchedulerPort:
        return self._c.jobs_scheduler_port()
