from dependency_injector import containers, providers

from services.simulators_repository.storage.details.simulators_storage import createStorage


class StorageContainer(containers.DeclarativeContainer):
    config = providers.Configuration()
    simulators_storage_factory = providers.Factory(createStorage, config=config)
