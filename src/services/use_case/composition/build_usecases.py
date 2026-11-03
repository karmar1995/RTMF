from __future__ import annotations

from functools import partial

from dependency_injector import containers, providers

from adapters.keycloak_identity_adapter.composition import KeycloakIdentityAdapterContainer
from adapters.use_case_adapter import TimingMiddleware
from adapters.analytics_rest_adapter.composition_root import AnalyticsRestAdapterContainer
from adapters.visualization_rest_adapter.composition_root import VisualizationRestAdapterContainer
from adapters.jobs_scheduler_rest_adapter.composition_root import (
    JobsSchedulerAdapterContainer,
    JobsSchedulerAdapterRoot,
)
from adapters.matrix_generator_rest_adapter.composition_root import MatrixGeneratorAdapterContainer
from adapters.parser_rest_adapter.composition_root import ParserRestAdapterContainer
from adapters.evaluator_rest_adapter.composition_root import EvaluatorRestAdapterContainer
from adapters.postgres_evaluations_store.composition_root import (
    PostgresEvaluationsStoreContainer,
)
from adapters.postgres_jobs_repository.composition_root import PostgresJobsRepositoryContainer
from adapters.simulators_repo_rest_adapter.composition_root import SimulatorsRepoAdapterContainer
from adapters.system_discovery_rest_adapter.composition_root import (
    SystemDiscoveryRestAdapterContainer,
)
from adapters.system_discovery_aistor_adapter.composition import (
    SystemDiscoveryAIStorAdapterContainer,
)
from adapters.system_discovery_simulation_results_postprocessor import (
    SystemDiscoverySimulationResultsArchivePostprocessor,
)
from adapters.system_discovery_training_results_storage.composition_root import (
    SystemDiscoveryTrainingResultsStorageContainer,
)
from adapters.system_discovery_training_registry.composition_root import (
    SystemDiscoveryTrainingRegistryContainer,
)
from configuration import load_service_config_into_provider
from services.use_case.bus import InProcessBus
from services.use_case.cleanup_scheduler import (
    PeriodicSystemDiscoveryTrainingQueueCleanup,
)
from services.use_case.security.api import DefaultRequestUseCaseAPIProvider
from services.use_case.security.authorization import MessagePermissionAuthorizer
from services.use_case.security.sessions import (
    InMemorySessionStore,
    SessionCredentialCodec,
    SessionService,
)
from services.use_case.handlers import handle_echo
from services.use_case.handlers.authentication import (
    handle_begin_browser_login,
    handle_complete_browser_login,
    handle_logout,
    handle_open_register_simulator_form,
    handle_open_simulation_run_form,
    handle_open_evaluation_run_form,
    handle_open_system_discovery_training_form,
    handle_require_authenticated_session,
)
from services.use_case.handlers.health import handle_health_check
from services.use_case.handlers.registrations import (
    handle_get_registration_details,
    handle_list_recent_registrations,
)
from services.use_case.utils import SystemClock
from services.use_case.handlers import (
    handle_get_job,
    handle_get_job_sub_jobs,
    handle_get_sub_job_details,
    handle_list_jobs,
    handle_list_monitor_entries,
    handle_list_visualization_jobs,
    handle_schedule_simulation_run
)
from services.use_case.handlers.visualizations import (
    handle_begin_job_visualization,
    handle_get_monte_carlo_filtering_plot_state,
    handle_get_visualization_constant_params,
    handle_job_visualization,
    handle_get_job_repetitions,
    handle_get_job_visualization_status,
    handle_retry_job_results,
    handle_visualize_disaster_stages,
    handle_visualize_monte_carlo_filtering
)
from services.use_case.handlers.simulators_browse import (
    handle_get_simulator_details,
    handle_list_simulators,
)
from services.use_case.handlers.simulators import handle_register_simulator
from services.use_case.handlers.system_discovery_training import (
    handle_cleanup_expired_system_discovery_training_queue_entries,
    handle_get_saved_system_discovery_model_details,
    handle_get_system_discovery_training_status,
    handle_list_system_discovery_trainings,
    handle_list_saved_system_discovery_models,
    handle_open_system_discovery_training_evaluation,
    handle_remove_saved_system_discovery_model,
    handle_remove_system_discovery_training_queue_entry,
    handle_save_system_discovery_model,
    handle_train_system_discovery,
)
from services.use_case.handlers.system_discovery_simulations import (
    handle_get_system_discovery_simulation_details,
    handle_list_system_discovery_simulations,
)
from services.use_case.handlers.evaluations import (
    handle_get_evaluation_details,
    handle_list_evaluations,
    handle_run_evaluation,
)
from use_case_contracts.messages import *
from use_case_contracts.ports import UseCaseAPI
from services.use_case.utils.plot_mapping import ParserRecognitionMapping, PlotMapping


def _validate_identity_provider_mode(provider_name: str) -> None:
    if provider_name != "keycloak":
        raise RuntimeError(
            f"Unsupported identity provider: {provider_name}. Runtime authentication uses Keycloak only."
        )


class UseCaseContainer(containers.DeclarativeContainer):
    config = providers.Configuration(strict=True)

    clock = providers.Singleton(SystemClock)
    plot_mapping = providers.Singleton(PlotMapping)
    parser_recognition_mapping = providers.Singleton(ParserRecognitionMapping)
    jobs_scheduler_adapter = providers.Container(
        JobsSchedulerAdapterContainer,
        config=config.clients.jobs_scheduler,
    )
    simulators_repo_adapter = providers.Container(
        SimulatorsRepoAdapterContainer,
        config=config.clients.simulators_repository,
    )
    analytics_adapter = providers.Container(
        AnalyticsRestAdapterContainer,
        config=config.clients.analytics,
    )
    visualization_adapter = providers.Container(
        VisualizationRestAdapterContainer,
        config=config.clients.visualization,
    )
    system_discovery_aistor_adapter = providers.Container(
        SystemDiscoveryAIStorAdapterContainer,
        config=config.adapters.system_discovery_aistor,
    )
    parser_adapter = providers.Container(
        ParserRestAdapterContainer,
        config=config.clients.parser,
    )
    matrix_generator_adapter = providers.Container(
        MatrixGeneratorAdapterContainer,
        config=config.clients.matrix_generator,
    )
    evaluator_adapter = providers.Container(
        EvaluatorRestAdapterContainer,
        config=config.clients.evaluator,
    )
    system_discovery_adapter = providers.Container(
        SystemDiscoveryRestAdapterContainer,
        config=config.clients.system_discovery,
    )
    postgres_jobs_repository = providers.Container(
        PostgresJobsRepositoryContainer,
        config=config.postgres.jobs_repository,
    )
    # Read side of the evaluations store, so the monitor can collapse the many
    # SSBO Slurm jobs of an evaluation into a single parent entry.
    postgres_evaluations_store = providers.Container(
        PostgresEvaluationsStoreContainer,
        config=config.postgres.evaluations_store,
    )
    system_discovery_training_registry_adapter = providers.Container(
        SystemDiscoveryTrainingRegistryContainer,
        config=config.postgres.jobs_repository,
    )
    system_discovery_training_results_storage_adapter = providers.Container(
        SystemDiscoveryTrainingResultsStorageContainer,
        config=config.storage.system_discovery_training_results,
    )
    keycloak_identity_provider_adapter = providers.Container(
        KeycloakIdentityAdapterContainer,
        config=config.authentication.keycloak,
        clock=clock,
    )
    simulators_repo = simulators_repo_adapter.simulators_repo
    evaluations_store = postgres_evaluations_store.evaluations_store
    jobs_repo = postgres_jobs_repository.jobs_repo
    analytics = analytics_adapter.analytics_port
    parser = parser_adapter.parser_port
    visualization = visualization_adapter.visualization_port
    matrix_generator = matrix_generator_adapter.matrix_generation_port
    evaluator = evaluator_adapter.evaluator_port
    system_discovery = system_discovery_adapter.system_discovery_port
    system_discovery_training_registry = (
        system_discovery_training_registry_adapter.system_discovery_training_registry
    )
    system_discovery_saved_model_registry = (
        system_discovery_training_registry_adapter.system_discovery_saved_model_registry
    )
    system_discovery_simulation_registry = (
        system_discovery_training_registry_adapter.system_discovery_simulation_registry
    )
    system_discovery_training_results_storage = (
        system_discovery_training_results_storage_adapter.system_discovery_training_results_storage
    )
    system_discovery_simulation_results_preparer = (
        system_discovery_training_results_storage_adapter.system_discovery_training_results_storage
    )
    system_discovery_simulation_results_postprocessor = providers.Singleton(
        SystemDiscoverySimulationResultsArchivePostprocessor
    )
    system_discovery_aistor = (
        system_discovery_aistor_adapter.system_discovery_aistor_port
    )
    jobs_scheduler = providers.Callable(
        lambda adapter: JobsSchedulerAdapterRoot(adapter).jobs_scheduler_port(),
        jobs_scheduler_adapter,
    )
    session_store = providers.Singleton(InMemorySessionStore)
    session_codec = providers.Singleton(
        SessionCredentialCodec,
        pepper=config.authentication.session.token_pepper,
    )
    authorizer = providers.Singleton(MessagePermissionAuthorizer)
    identity_provider_mode_validation = providers.Callable(
        _validate_identity_provider_mode,
        config.authentication.identity_provider,
    )
    identity_provider = keycloak_identity_provider_adapter.identity_provider
    session_service = providers.Singleton(
        SessionService,
        store=session_store,
        codec=session_codec,
        clock=clock,
        idle_timeout_seconds=config.authentication.session.idle_timeout_seconds.as_int(),
        absolute_timeout_seconds=config.authentication.session.absolute_timeout_seconds.as_int(),
        refresh_skew_seconds=config.authentication.session.refresh_skew_seconds.as_int(),
        identity_provider=keycloak_identity_provider_adapter.identity_provider,
    )

    bus = providers.Singleton(InProcessBus)


def build_usecases() -> InProcessBus:
    container = UseCaseContainer()
    load_service_config_into_provider(container.config, service_name="use_case")
    container.identity_provider_mode_validation()
    bus = container.bus()
    _register_authentication_handlers(container, bus)
    _register_application_handlers(container, bus)
    _start_system_discovery_training_cleanup(container, bus)
    return bus


def build_request_usecase_api_provider(inner: UseCaseAPI | None = None) -> DefaultRequestUseCaseAPIProvider:
    container = UseCaseContainer()
    load_service_config_into_provider(container.config, service_name="use_case")
    container.identity_provider_mode_validation()
    bus = container.bus()
    _register_authentication_handlers(container, bus)
    _register_application_handlers(container, bus)
    cleanup = _start_system_discovery_training_cleanup(container, bus)
    inner_api = inner or TimingMiddleware(bus)
    provider = DefaultRequestUseCaseAPIProvider(
        inner=inner_api,
        sessions=container.session_service(),
        authorizer=container.authorizer(),
    )
    provider.system_discovery_training_cleanup = cleanup
    return provider


def _register_authentication_handlers(container: UseCaseContainer, bus: InProcessBus) -> None:
    bus.register(
        BeginBrowserLogin,
        partial(
            handle_begin_browser_login,
            identity_provider=container.identity_provider(),
        ),
    )
    bus.register(
        CompleteBrowserLogin,
        partial(
            handle_complete_browser_login,
            identity_provider=container.identity_provider(),
            sessions=container.session_service(),
        ),
    )
    bus.register(Logout, handle_logout)
    bus.register(RequireAuthenticatedSession, handle_require_authenticated_session)
    bus.register(OpenRegisterSimulatorForm, handle_open_register_simulator_form)
    bus.register(OpenSimulationRunForm, handle_open_simulation_run_form)
    bus.register(OpenEvaluationRunForm, handle_open_evaluation_run_form)
    bus.register(
        OpenSystemDiscoveryTrainingForm,
        handle_open_system_discovery_training_form,
    )


def _register_application_handlers(container: UseCaseContainer, bus: InProcessBus) -> InProcessBus:
    bus.register(HealthCheck, handle_health_check)
    bus.register(Echo, handle_echo)
    bus.register(
        ListRecentRegistrations,
        partial(
            handle_list_recent_registrations,
            repo=container.simulators_repo(),
        ),
    )
    bus.register(
        GetRegistrationDetails,
        partial(
            handle_get_registration_details,
            repo=container.simulators_repo(),
        ),
    )
    bus.register(
        ListSimulators,
        partial(
            handle_list_simulators,
            repo=container.simulators_repo(),
        ),
    )
    bus.register(
        GetSimulatorDetails,
        partial(
            handle_get_simulator_details,
            repo=container.simulators_repo(),
        ),
    )
    bus.register(
        ScheduleSimulationRun,
        partial(
            handle_schedule_simulation_run,
            repo=container.simulators_repo(),
            scheduler=container.jobs_scheduler(),
            matrix_generator=container.matrix_generator(),
        ),
    )
    bus.register(
        GetJob,
        partial(
            handle_get_job,
            scheduler=container.jobs_scheduler(),
        ),
    )
    bus.register(
        GetJobSubJobs,
        partial(
            handle_get_job_sub_jobs,
            scheduler=container.jobs_scheduler(),
        ),
    )
    bus.register(
        GetSubJobDetails,
        partial(
            handle_get_sub_job_details,
            scheduler=container.jobs_scheduler(),
        ),
    )
    bus.register(
        ListJobs,
        partial(
            handle_list_jobs,
            scheduler=container.jobs_scheduler(),
        ),
    )

    bus.register(
        ListMonitorEntries,
        partial(
            handle_list_monitor_entries,
            scheduler=container.jobs_scheduler(),
            evaluations_store=container.evaluations_store(),
        ),
    )

    bus.register(
        ListVisualizationJobs,
        partial(
            handle_list_visualization_jobs,
            jobsRepo=container.jobs_repo(),
            simulatorsRepo=container.simulators_repo()
        )
    )

    bus.register(
        RegisterSimulator,
        partial(
            handle_register_simulator,
            repo=container.simulators_repo(),
            clock=container.clock(),
        ),
    )

    bus.register(
        BeginJobVisualization,
        partial(
            handle_begin_job_visualization,
            jobs_repo=container.jobs_repo(),
            simulators_repo=container.simulators_repo(),
            analytics=container.analytics(),
            visualization=container.visualization(),
        )
    )

    bus.register(
        RetryJobResults,
        partial(
            handle_retry_job_results,
            jobs_repo=container.jobs_repo(),
            simulators_repo=container.simulators_repo(),
            analytics=container.analytics(),
        )
    )

    bus.register(
        GetVisualizationConstantParams,
        partial(
            handle_get_visualization_constant_params,
            analytics=container.analytics()
        )
    )

    bus.register(
        GetJobRepetitions,
        partial(
            handle_get_job_repetitions,
            analytics=container.analytics()
        )
    )

    bus.register(
        GetJobVisualizationStatus,
        partial(
            handle_get_job_visualization_status,
            analytics=container.analytics()
        )
    )

    bus.register(
        VisualizeJob,
        partial(
            handle_job_visualization,
            analytics=container.analytics(),
            visualization=container.visualization(),
            plotsIds=container.plot_mapping()
        )
    )

    bus.register(
        VisualizeDisasterStages,
        partial(
            handle_visualize_disaster_stages,
            analytics=container.analytics(),
            visualization=container.visualization(),
            plotsIds=container.plot_mapping(),
            parser=container.parser(),
            parserRecognitionIds=container.parser_recognition_mapping()
        )
    )

    bus.register(
        VisualizeMonteCarloFiltering,
        partial(
            handle_visualize_monte_carlo_filtering,
            jobs_repo=container.jobs_repo(),
            simulators_repo=container.simulators_repo(),
            analytics=container.analytics(),
            visualization=container.visualization(),
        )
    )

    bus.register(
        GetMonteCarloFilteringPlotState,
        partial(
            handle_get_monte_carlo_filtering_plot_state,
            visualization=container.visualization(),
        )
    )

    bus.register(
        TrainSystemDiscovery,
        partial(
            handle_train_system_discovery,
            system_discovery=container.system_discovery(),
            registry=container.system_discovery_training_registry(),
            clock=container.clock(),
        ),
    )
    bus.register(
        GetSystemDiscoveryTrainingStatus,
        partial(
            handle_get_system_discovery_training_status,
            system_discovery=container.system_discovery(),
            registry=container.system_discovery_training_registry(),
            results_storage=container.system_discovery_training_results_storage(),
            clock=container.clock(),
        ),
    )
    bus.register(
        ListSystemDiscoveryTrainings,
        partial(
            handle_list_system_discovery_trainings,
            system_discovery=container.system_discovery(),
            registry=container.system_discovery_training_registry(),
            results_storage=container.system_discovery_training_results_storage(),
            clock=container.clock(),
        ),
    )
    bus.register(
        OpenSystemDiscoveryTrainingEvaluation,
        partial(
            handle_open_system_discovery_training_evaluation,
            registry=container.system_discovery_training_registry(),
            results_storage=container.system_discovery_training_results_storage(),
            visualization=container.visualization(),
            plotsIds=container.plot_mapping(),
            saved_models=container.system_discovery_saved_model_registry(),
        ),
    )
    bus.register(
        SaveSystemDiscoveryModel,
        partial(
            handle_save_system_discovery_model,
            registry=container.system_discovery_training_registry(),
            saved_models=container.system_discovery_saved_model_registry(),
            results_storage=container.system_discovery_training_results_storage(),
            simulators_repo=container.simulators_repo(),
            clock=container.clock(),
        ),
    )
    bus.register(
        RemoveSystemDiscoveryTrainingQueueEntry,
        partial(
            handle_remove_system_discovery_training_queue_entry,
            registry=container.system_discovery_training_registry(),
            saved_models=container.system_discovery_saved_model_registry(),
            results_storage=container.system_discovery_training_results_storage(),
            clock=container.clock(),
        ),
    )
    bus.register(
        ListSavedSystemDiscoveryModels,
        partial(
            handle_list_saved_system_discovery_models,
            saved_models=container.system_discovery_saved_model_registry(),
        ),
    )
    bus.register(
        RemoveSavedSystemDiscoveryModel,
        partial(
            handle_remove_saved_system_discovery_model,
            saved_models=container.system_discovery_saved_model_registry(),
        ),
    )
    bus.register(
        CleanupExpiredSystemDiscoveryTrainingQueueEntries,
        partial(
            handle_cleanup_expired_system_discovery_training_queue_entries,
            registry=container.system_discovery_training_registry(),
            saved_models=container.system_discovery_saved_model_registry(),
            results_storage=container.system_discovery_training_results_storage(),
            clock=container.clock(),
        ),
    )
    bus.register(
        GetSavedSystemDiscoveryModelDetails,
        partial(
            handle_get_saved_system_discovery_model_details,
            saved_models=container.system_discovery_saved_model_registry(),
        ),
    )
    bus.register(
        ListSystemDiscoverySimulations,
        partial(
            handle_list_system_discovery_simulations,
            system_discovery=container.system_discovery(),
            registry=container.system_discovery_simulation_registry(),
            results_postprocessor=(
                container.system_discovery_simulation_results_postprocessor()
            ),
            aistor=container.system_discovery_aistor(),
            clock=container.clock(),
        ),
    )
    bus.register(
        GetSystemDiscoverySimulationDetails,
        partial(
            handle_get_system_discovery_simulation_details,
            system_discovery=container.system_discovery(),
            registry=container.system_discovery_simulation_registry(),
            aistor=container.system_discovery_aistor(),
            results_postprocessor=(
                container.system_discovery_simulation_results_postprocessor()
            ),
            results_preparer=container.system_discovery_simulation_results_preparer(),
            visualization=container.visualization(),
            plotsIds=container.plot_mapping(),
            clock=container.clock(),
        ),
    )

    bus.register(
        RunEvaluation,
        partial(
            handle_run_evaluation,
            evaluator=container.evaluator(),
        ),
    )
    bus.register(
        ListEvaluations,
        partial(
            handle_list_evaluations,
            evaluator=container.evaluator(),
        ),
    )
    bus.register(
        GetEvaluationDetails,
        partial(
            handle_get_evaluation_details,
            evaluator=container.evaluator(),
            visualization=container.visualization(),
            plotsIds=container.plot_mapping(),
        ),
    )

    return bus


def _start_system_discovery_training_cleanup(
    container: UseCaseContainer,
    bus: InProcessBus,
) -> PeriodicSystemDiscoveryTrainingQueueCleanup | None:
    try:
        settings = container.config.system_discovery.training_queue_cleanup()
    except Exception:
        settings = {}
    if not settings.get("enabled", True):
        return None
    cleanup = PeriodicSystemDiscoveryTrainingQueueCleanup(
        usecases=bus,
        interval_seconds=float(settings.get("interval_seconds", 86400)),
        terminal_retention_days=int(settings.get("terminal_retention_days", 30)),
    )
    cleanup.start()
    return cleanup
