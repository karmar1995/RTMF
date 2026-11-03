from __future__ import annotations

from dependency_injector import containers, providers

from adapters.slurm_adapter.slurm_job_submit_request_builder import (
    SlurmJobSubmitDefaults,
    SlurmJobSubmitRequestBuilder,
)
from adapters.slurm_adapter.slurm_jobs_scheduler import SlurmJobsScheduler
from adapters.slurm_adapter.slurm_request_info import SlurmRequestInfo
from adapters.slurm_adapter.slurm_rest_client import SlurmRestClient
from adapters.slurm_adapter.slurm_token_refresher import SlurmTokenRefresher
from services.jobs_scheduler.core.ports import JobsSchedulerPort


class SlurmAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration(
        default={
            "base_url": None,
            "address": "",
            "scheme": "http",
            "slurm_port": 6820,
            "api_version": "",
            "user_name": "",
            "request_timeout_seconds": 10.0,
            "token_timeout_seconds": 10.0,
            "docker_username": "",
            "docker_password": "",
            "minio_endpoint": "",
            "minio_user": "",
            "minio_password": "",
            "job_executor_user": "",
            "job_executor_group": "",
            "working_directory": "/tmp/workspace",
            "job_name_prefix": "simu",
            "partition": None,
            "stdout": None,
            "stderr": None,
            "postgres_dsn": "",
        }
    )

    token_refresher = providers.Singleton(
        SlurmTokenRefresher,
        username=config.user_name,
        command_timeout_seconds=config.token_timeout_seconds.as_float(),
    )

    rest_client = providers.Singleton(
        SlurmRestClient,
        base_url=config.base_url,
        address=config.address,
        scheme=config.scheme,
        slurm_port=config.slurm_port,
        api_version=config.api_version,
        username=config.user_name,
        token_refresher=token_refresher,
        timeout_seconds=config.request_timeout_seconds.as_float(),
    )

    request_info = providers.Singleton(
        SlurmRequestInfo,
        docker_username=config.docker_username,
        docker_password=config.docker_password,
        minio_endpoint=config.minio_endpoint,
        minio_user=config.minio_user,
        minio_password=config.minio_password,
        job_executor_user=config.job_executor_user,
        job_executor_group=config.job_executor_group,
        postgres_dsn=config.postgres_dsn
    )

    submit_defaults = providers.Singleton(
        SlurmJobSubmitDefaults,
        working_directory=config.working_directory,
        partition=config.partition,
        standard_output=config.stdout,
        standard_error=config.stderr,
    )

    submit_builder = providers.Singleton(
        SlurmJobSubmitRequestBuilder,
        rest_client=rest_client,
        defaults=submit_defaults,
    )

    jobs_scheduler = providers.Singleton(
        SlurmJobsScheduler,
        request_info=request_info,
        builder=submit_builder,
        rest_client=rest_client,
        working_directory=config.working_directory,
        job_name_prefix=config.job_name_prefix,
        partition=config.partition,
        standard_output=config.stdout,
        standard_error=config.stderr,
    )


class SlurmAdapterRoot:
    def __init__(self, container: SlurmAdapterContainer) -> None:
        self._c = container

    def jobs_scheduler(self) -> JobsSchedulerPort:
        return self._c.jobs_scheduler()
