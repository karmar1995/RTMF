from dependency_injector import containers, providers
from services.parser.core.service import ParserService

class ApplicationContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    parser_service = providers.Singleton(
        ParserService,
        tasks_dir=config.jobs.workspace,
    )
