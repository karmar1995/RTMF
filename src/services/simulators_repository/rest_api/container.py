from dependency_injector import containers, providers

from services.simulators_repository.composition.container import RepositoryServiceContainer
from services.simulators_repository.rest_api.details.rest_repository_service import RestRepositoryService


class RestRepositoryServiceContainer(containers.DeclarativeContainer):
    composition = providers.Container(RepositoryServiceContainer)
    rest_service = providers.Singleton(
        RestRepositoryService,
        repository=composition.provided.abstract_simulator_repository(),
        config=composition.provided.config.rest,
    )
    run = providers.Callable(lambda service: service.run(), rest_service)
