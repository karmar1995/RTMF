from dependency_injector import containers, providers

from configuration import load_service_config_into_provider
from services.simulators_repository.build_worker.container import BuildWorkerContainer
from services.simulators_repository.core.container import CoreContainer
from services.simulators_repository.storage.container import StorageContainer


def _initialize_build_worker(build_worker: BuildWorkerContainer, config_provider) -> None:
    build_worker.config.from_dict(config_provider.build_worker())


def _initialize_storage(storage: StorageContainer, config_provider) -> None:
    storage.config.from_dict(config_provider.postgres.simulators_repository())


def _initialize_services(
    build_worker: BuildWorkerContainer,
    storage: StorageContainer,
    core: CoreContainer,
    config_provider,
) -> None:
    load_service_config_into_provider(
        config_provider,
        service_name="simulators_repository",
    )
    _initialize_build_worker(build_worker, config_provider)
    _initialize_storage(storage, config_provider)
    core.config.from_dict(config_provider.core())


class RepositoryServiceContainer(containers.DeclarativeContainer):
    config = providers.Configuration(strict=True)
    build_worker = providers.Container(BuildWorkerContainer)
    storage = providers.Container(StorageContainer)
    core = providers.Container(
        CoreContainer,
        build_worker_factory=build_worker.provided.build_worker_factory,
        simulators_storage_factory=storage.provided.simulators_storage_factory,
        config=config.core,
    )
    initialize = providers.Callable(
        _initialize_services,
        build_worker=build_worker,
        storage=storage,
        core=core,
        config_provider=config.provider,
    )
    abstract_simulator_repository = core.provided.abstract_simulator_repository()
