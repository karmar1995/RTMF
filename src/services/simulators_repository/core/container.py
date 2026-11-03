from dependency_injector import containers, providers

from services.simulators_repository.core.details.simulator_repository_controller import SimulatorRepositoryController


class CoreContainer(containers.DeclarativeContainer):
    build_worker_factory = providers.Dependency()
    simulators_storage_factory = providers.Dependency()
    config = providers.Configuration()
    simulator_repository = providers.Singleton(
        SimulatorRepositoryController,
        build_worker_factory=build_worker_factory,
        simulators_storage_factory=simulators_storage_factory,
        config=config,
    )
    abstract_simulator_repository = simulator_repository
