from dependency_injector import containers, providers

from services.simulators_repository.build_worker.details.buildkit_worker import createWorker


class BuildWorkerContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    build_worker_factory = providers.Factory(createWorker,config=config)
