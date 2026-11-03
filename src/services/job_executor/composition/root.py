from __future__ import annotations

from configuration import load_service_config_into_provider
from services.job_executor.composition.container import Container


def create_container() -> Container:
    container = Container()
    load_service_config_into_provider(container.config, service_name="job_executor")
    return container


def create_executor(container: Container | None = None):
    container = container or create_container()
    return container.executor()


def describe_executor_identity(container: Container) -> str:
    user = container.config.executor.user()
    group = container.config.executor.group()
    return f"Job Executor identity: user={user} group={group}"
