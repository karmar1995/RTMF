from dependency_injector import containers, providers

from services.simulators_repository.core.container import CoreContainer
from services.simulators_repository.core.tests.utils.fake_image_build_worker import FakeImageBuildWorker
from services.simulators_repository.core.tests.utils.fake_simulators_storage import FakeSimulatorsStorage


def default_config(**overrides):
    config = {
        "concurrent_builds": 1,
        "builds_poll_interval": 0.1,
        "storage_poll_interval": 0.1,
    }
    config.update(overrides)
    return config


class FakeRepositoryServiceContainer(containers.DeclarativeContainer):
    config = providers.Configuration()
    fake_build_worker = providers.Singleton(FakeImageBuildWorker)
    fake_storage = providers.Singleton(FakeSimulatorsStorage)

    core = providers.Container(
        CoreContainer,
        build_worker_factory=providers.Object(fake_build_worker),
        simulators_storage_factory=providers.Object(fake_storage),
        config=config,
    )

    abstract_simulator_repository = core.provided.abstract_simulator_repository()
