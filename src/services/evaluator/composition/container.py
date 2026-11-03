from __future__ import annotations

from dependency_injector import containers, providers

from adapters.analytics_rest_adapter.composition_root import (
    AnalyticsRestAdapterContainer,
)
from adapters.aistor_results_repository.composition_root import (
    AIStorAdapterContainer,
)
from adapters.jobs_scheduler_rest_adapter.composition_root import (
    JobsSchedulerAdapterContainer,
)
from adapters.matrix_generator_rest_adapter.composition_root import (
    MatrixGeneratorAdapterContainer,
)
from adapters.parser_rest_adapter.composition_root import ParserRestAdapterContainer
from adapters.postgres_evaluations_store.composition_root import (
    PostgresEvaluationsStoreContainer,
)
from adapters.postgres_jobs_repository.composition_root import (
    PostgresJobsRepositoryContainer,
)
from adapters.simulators_repo_rest_adapter.composition_root import (
    SimulatorsRepoAdapterContainer,
)
from services.evaluator.core.evaluator_service import EvaluatorService
from services.evaluator.rest_api.app import create_app


class ApplicationContainer(containers.DeclarativeContainer):
    config = providers.Configuration(strict=True)

    analytics = providers.Container(
        AnalyticsRestAdapterContainer,
        config=config.clients.analytics,
    )
    jobs_scheduler = providers.Container(
        JobsSchedulerAdapterContainer,
        config=config.clients.jobs_scheduler,
    )
    simulators_repo = providers.Container(
        SimulatorsRepoAdapterContainer,
        config=config.clients.simulators_repository,
    )
    parser = providers.Container(
        ParserRestAdapterContainer,
        config=config.clients.parser,
    )
    matrix_generator = providers.Container(
        MatrixGeneratorAdapterContainer,
        config=config.clients.matrix_generator,
    )
    jobs_repository = providers.Container(
        PostgresJobsRepositoryContainer,
        config=config.postgres.jobs_repository,
    )
    results_repository = providers.Container(
        AIStorAdapterContainer,
        config=config.clients.aistor_results,
    )

    evaluations_store_adapter = providers.Container(
        PostgresEvaluationsStoreContainer,
        config=config.postgres.evaluations_store,
    )

    evaluator_service = providers.Singleton(
        EvaluatorService,
        jobs_scheduler=jobs_scheduler.provided.jobs_scheduler_port(),
        simulator_repository=simulators_repo.provided.simulators_repo(),
        jobs_repository=jobs_repository.provided.jobs_repo_reader(),
        results_repository=results_repository.provided.results_repo(),
        analytics=analytics.provided.analytics_port(),
        parser=parser.provided.parser_port(),
        matrix_generator=matrix_generator.provided.matrix_generation_port(),
        state_store=evaluations_store_adapter.provided.evaluations_store(),
    )
    evaluator_port = evaluator_service

    app = providers.Factory(
        create_app,
        port=evaluator_port,
    )
