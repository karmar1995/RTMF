from __future__ import annotations

import logging
from datetime import timedelta

from services.use_case.ports import Clock
from use_case_contracts.dtos import (
    GetSystemDiscoveryTrainingStatusResult,
    CleanupExpiredSystemDiscoveryTrainingQueueEntriesResult,
    GetSavedSystemDiscoveryModelDetailsResult,
    ListSavedSystemDiscoveryModelsResult,
    ListSystemDiscoveryTrainingsResult,
    OpenSystemDiscoveryTrainingEvaluationResult,
    PlotDiagonalLine,
    PlotSpec,
    RemoveSavedSystemDiscoveryModelResult,
    RemoveSystemDiscoveryTrainingQueueEntryResult,
    SaveSystemDiscoveryModelResult,
    SimulatorBuildRecord,
    SystemDiscoveryParameters,
    SystemDiscoverySavedModelRecord,
    SystemDiscoveryTrainingEvaluationPlot,
    SystemDiscoveryTrainingEvaluationPlotState,
    SystemDiscoveryTrainingEvaluationState,
    SystemDiscoveryTrainingRecord,
    SystemDiscoveryTrainingRefreshFailure,
    SystemDiscoveryTrainingRequest,
    SystemDiscoveryTrainingState,
    SystemDiscoveryTrainingStatus,
    TrainSystemDiscoveryResult,
)
from use_case_contracts.errors import ExternalServiceError, NotFoundError
from use_case_contracts.messages import (
    GetSystemDiscoveryTrainingStatus,
    CleanupExpiredSystemDiscoveryTrainingQueueEntries,
    GetSavedSystemDiscoveryModelDetails,
    ListSavedSystemDiscoveryModels,
    ListSystemDiscoveryTrainings,
    OpenSystemDiscoveryTrainingEvaluation,
    RemoveSavedSystemDiscoveryModel,
    RemoveSystemDiscoveryTrainingQueueEntry,
    SaveSystemDiscoveryModel,
    TrainSystemDiscovery,
)
from use_case_contracts.ports import (
    SimulatorRepository,
    SystemDiscoveryPort,
    SystemDiscoverySavedModelRegistryPort,
    SystemDiscoveryTrainingResultsStoragePort,
    SystemDiscoveryTrainingRegistryPort,
    VisualizationPort,
)
from services.use_case.utils.plot_mapping import PlotMapping
from services.use_case.utils.pagination import paginate

logger = logging.getLogger(__name__)


def handle_train_system_discovery(
    message: TrainSystemDiscovery,
    system_discovery: SystemDiscoveryPort,
    registry: SystemDiscoveryTrainingRegistryPort,
    clock: Clock,
) -> TrainSystemDiscoveryResult:
    parameters = SystemDiscoveryParameters(
        nlags_x=message.nlags_x,
        nlags_y=message.nlags_y,
        basis=message.basis,
        degree=message.degree,
        model=message.model,
    )
    submission = system_discovery.submit_training(
        SystemDiscoveryTrainingRequest(
            training_data_archive=message.training_data_archive,
            system_parameters=parameters,
        )
    )
    now = clock.now()
    initial_state = normalize_system_discovery_training_state(
        status=submission.status,
        error=None,
    )
    registry.register_training(
        SystemDiscoveryTrainingRecord(
            training_id=submission.training_id,
            created_at=now,
            updated_at=now,
            state=initial_state,
            raw_status=submission.status,
            training_status=None,
            evaluation_status=None,
            error=None,
            basis=message.basis,
            degree=message.degree,
            model=message.model,
            nlags_x=message.nlags_x,
            nlags_y=message.nlags_y,
            finished_at=now
            if initial_state
            in {
                SystemDiscoveryTrainingState.COMPLETED,
                SystemDiscoveryTrainingState.FAILED,
            }
            else None,
        )
    )
    return TrainSystemDiscoveryResult(
        training_id=submission.training_id,
        status=submission.status,
    )


def handle_get_system_discovery_training_status(
    message: GetSystemDiscoveryTrainingStatus,
    system_discovery: SystemDiscoveryPort,
    registry: SystemDiscoveryTrainingRegistryPort,
    results_storage: SystemDiscoveryTrainingResultsStoragePort,
    clock: Clock,
) -> GetSystemDiscoveryTrainingStatusResult:
    record = _require_known_training(registry, message.training_id)
    failures: list[SystemDiscoveryTrainingRefreshFailure] = []
    if not _is_finished(record):
        try:
            status = system_discovery.get_training_status(message.training_id)
            record = _update_record_from_status(registry, clock, status)
        except Exception as exc:
            failures.append(_refresh_failure(message.training_id, exc))
    if _requires_results_cache(record):
        record = _cache_completed_results(
            record,
            system_discovery=system_discovery,
            registry=registry,
            results_storage=results_storage,
            clock=clock,
            failures=failures,
        )
    else:
        record = _normalize_cached_archive_reference(record, registry, results_storage)
    return GetSystemDiscoveryTrainingStatusResult(
        training=record,
        failures=failures,
    )


def handle_list_system_discovery_trainings(
    message: ListSystemDiscoveryTrainings,
    system_discovery: SystemDiscoveryPort,
    registry: SystemDiscoveryTrainingRegistryPort,
    results_storage: SystemDiscoveryTrainingResultsStoragePort,
    clock: Clock,
) -> ListSystemDiscoveryTrainingsResult:
    failures: list[SystemDiscoveryTrainingRefreshFailure] = []
    for record in registry.list_trainings():
        current = record
        if not _is_finished(current):
            try:
                status = system_discovery.get_training_status(current.training_id)
                current = _update_record_from_status(registry, clock, status)
            except (
                Exception
            ) as exc:  # Preserve other entries when one remote refresh fails.
                failures.append(_refresh_failure(current.training_id, exc))
        if _requires_results_cache(current):
            _cache_completed_results(
                current,
                system_discovery=system_discovery,
                registry=registry,
                results_storage=results_storage,
                clock=clock,
                failures=failures,
            )
        else:
            _normalize_cached_archive_reference(current, registry, results_storage)
    all_trainings = registry.list_trainings()
    trainings, total = paginate(all_trainings, message.page, message.per_page)
    return ListSystemDiscoveryTrainingsResult(
        trainings=list(trainings),
        failures=failures,
        page=message.page,
        per_page=message.per_page,
        total=total,
    )


def handle_open_system_discovery_training_evaluation(
    message: OpenSystemDiscoveryTrainingEvaluation,
    registry: SystemDiscoveryTrainingRegistryPort,
    results_storage: SystemDiscoveryTrainingResultsStoragePort,
    visualization: VisualizationPort,
    plotsIds: PlotMapping,
    saved_models: SystemDiscoverySavedModelRegistryPort | None = None,
) -> OpenSystemDiscoveryTrainingEvaluationResult:
    record = _require_known_training(registry, message.training_id)
    if record.state != SystemDiscoveryTrainingState.COMPLETED:
        if saved_models is not None:
            saved = saved_models.get_model_by_source_training_id(message.training_id)
            if saved is not None:
                return OpenSystemDiscoveryTrainingEvaluationResult(
                    training=record,
                    state=SystemDiscoveryTrainingEvaluationState.FAILED,
                    message="This training has already been saved as a model.",
                )
        return OpenSystemDiscoveryTrainingEvaluationResult(
            training=record,
            state=SystemDiscoveryTrainingEvaluationState.NOT_COMPLETED,
            message="Model evaluation is available only for completed trainings.",
        )
    if not record.results_archive_path:
        return OpenSystemDiscoveryTrainingEvaluationResult(
            training=record,
            state=SystemDiscoveryTrainingEvaluationState.FAILED,
            message="Completed training results have not been cached yet.",
        )
    record = _normalize_cached_archive_reference(record, registry, results_storage)
    if not record.results_archive_path:
        return OpenSystemDiscoveryTrainingEvaluationResult(
            training=record,
            state=SystemDiscoveryTrainingEvaluationState.FAILED,
            message="Completed training results have not been cached yet.",
        )

    status = results_storage.get_evaluation_postprocessing_status(record.training_id)
    if status != "ready":
        status = results_storage.start_evaluation_postprocessing(
            record.training_id,
            record.results_archive_path,
        )
        return OpenSystemDiscoveryTrainingEvaluationResult(
            training=record,
            state=SystemDiscoveryTrainingEvaluationState.POSTPROCESSING,
            message="Waiting for model evaluation.",
        )

    try:
        metadata = results_storage.get_evaluation_metadata(record.training_id)
    except Exception as exc:
        return OpenSystemDiscoveryTrainingEvaluationResult(
            training=record,
            state=SystemDiscoveryTrainingEvaluationState.FAILED,
            message=str(exc),
        )

    return OpenSystemDiscoveryTrainingEvaluationResult(
        training=record,
        state=SystemDiscoveryTrainingEvaluationState.READY,
        metadata=metadata,
        can_save_model=results_storage.can_save_evaluation_workspace(
            record.training_id,
            record.results_archive_path,
        ),
        results_plot=_evaluation_plot(
            training_id=record.training_id,
            artifact_name="results.csv",
            title="Results",
            plot_type="Line",
            results_storage=results_storage,
            visualization=visualization,
            plotsIds=plotsIds,
        ),
        cdf_plot=_evaluation_plot(
            training_id=record.training_id,
            artifact_name="cdf.csv",
            title="CDF",
            plot_type="Line",
            results_storage=results_storage,
            visualization=visualization,
            plotsIds=plotsIds,
        ),
        scatter_plot=_evaluation_plot(
            training_id=record.training_id,
            artifact_name="scatter.csv",
            title="Predicted vs Observed",
            plot_type="Scatter",
            results_storage=results_storage,
            visualization=visualization,
            plotsIds=plotsIds,
            diagonal_lines=_scatter_diagonal_lines(results_storage, record.training_id),
        ),
    )


def handle_save_system_discovery_model(
    message: SaveSystemDiscoveryModel,
    registry: SystemDiscoveryTrainingRegistryPort,
    saved_models: SystemDiscoverySavedModelRegistryPort,
    results_storage: SystemDiscoveryTrainingResultsStoragePort,
    simulators_repo: SimulatorRepository,
    clock: Clock,
) -> SaveSystemDiscoveryModelResult:
    existing = saved_models.get_model_by_source_training_id(message.training_id)
    if existing is not None:
        registry.archive_training(message.training_id, archived_at=clock.now())
        return SaveSystemDiscoveryModelResult(model_id=existing.model_id)

    record = _require_known_training(registry, message.training_id)
    if record.state != SystemDiscoveryTrainingState.COMPLETED:
        raise ValueError("Only completed System Discovery trainings can be saved.")
    if not record.results_archive_path:
        raise ValueError("Completed training results have not been cached yet.")
    record = _normalize_cached_archive_reference(record, registry, results_storage)
    if not record.results_archive_path:
        raise ValueError("System Discovery model evaluation is not ready to save.")

    model_id = record.training_id
    workspace_archive = results_storage.build_model_simulation_archive(
        record.training_id,
        record.results_archive_path,
    )
    registration_id = _register_saved_model_as_simulator(
        record=record,
        model_id=model_id,
        workspace_archive=workspace_archive,
        simulators_repo=simulators_repo,
        clock=clock,
    )

    saved = SystemDiscoverySavedModelRecord(
        model_id=model_id,
        source_training_id=record.training_id,
        model_name=record.model,
        saved_at=clock.now(),
        nlags_x=record.nlags_x,
        nlags_y=record.nlags_y,
        basis=record.basis,
        degree=record.degree,
    )
    saved_models.save_model(saved)
    registry.archive_training(record.training_id, archived_at=clock.now())
    return SaveSystemDiscoveryModelResult(
        model_id=model_id,
        simulator_registration_id=registration_id,
    )


def _register_saved_model_as_simulator(
    *,
    record: SystemDiscoveryTrainingRecord,
    model_id: str,
    workspace_archive: bytes,
    simulators_repo: SimulatorRepository,
    clock: Clock,
) -> str:
    from services.use_case.handlers.sd_simulator_registration import (
        build_build_spec,
        build_simulator_input_params,
        build_simulator_output_params,
        build_wrapper_archive,
        derive_ic_dimension,
    )

    ic_dimension = derive_ic_dimension(
        workspace_archive,
        fallback_dimension=record.nlags_y,
    )
    wrapper_archive = build_wrapper_archive(
        workspace_archive=workspace_archive,
        ic_dimension=ic_dimension,
    )
    build_record = SimulatorBuildRecord(
        model_name=record.model,
        zip_filename=f"{model_id}.zip",
        zip_bytes=wrapper_archive,
        build_spec=build_build_spec(),
        input_params=build_simulator_input_params(
            ic_dimension, include_horizon=True
        ),
        output_params=build_simulator_output_params(),
        created_at=clock.now(),
    )
    return simulators_repo.register(build_record)


def handle_remove_system_discovery_training_queue_entry(
    message: RemoveSystemDiscoveryTrainingQueueEntry,
    registry: SystemDiscoveryTrainingRegistryPort,
    saved_models: SystemDiscoverySavedModelRegistryPort,
    results_storage: SystemDiscoveryTrainingResultsStoragePort,
    clock: Clock,
) -> RemoveSystemDiscoveryTrainingQueueEntryResult:
    record = registry.get_training(message.training_id)
    if record is None:
        raise NotFoundError(
            f"System Discovery training '{message.training_id}' was not found"
        )
    _remove_training_queue_entry(
        record=record,
        registry=registry,
        saved_models=saved_models,
        results_storage=results_storage,
        clock=clock,
    )
    return RemoveSystemDiscoveryTrainingQueueEntryResult(
        training_id=message.training_id,
        removed=True,
    )


def handle_remove_saved_system_discovery_model(
    message: RemoveSavedSystemDiscoveryModel,
    saved_models: SystemDiscoverySavedModelRegistryPort,
) -> RemoveSavedSystemDiscoveryModelResult:
    model = saved_models.get_model(message.model_id)
    if model is None:
        raise NotFoundError(
            f"System Discovery saved model '{message.model_id}' was not found"
        )
    saved_models.remove_model(model.model_id)
    return RemoveSavedSystemDiscoveryModelResult(
        model_id=message.model_id,
        removed=True,
    )


def handle_cleanup_expired_system_discovery_training_queue_entries(
    message: CleanupExpiredSystemDiscoveryTrainingQueueEntries,
    registry: SystemDiscoveryTrainingRegistryPort,
    saved_models: SystemDiscoverySavedModelRegistryPort,
    results_storage: SystemDiscoveryTrainingResultsStoragePort,
    clock: Clock,
) -> CleanupExpiredSystemDiscoveryTrainingQueueEntriesResult:
    now = clock.now()
    cutoff = now - timedelta(days=message.terminal_retention_days)
    examined = removed = skipped = failed = 0
    for record in registry.list_trainings():
        examined += 1
        if record.state not in {
            SystemDiscoveryTrainingState.COMPLETED,
            SystemDiscoveryTrainingState.FAILED,
        }:
            skipped += 1
            continue
        finished_at = record.finished_at or record.updated_at
        if finished_at is None or finished_at > cutoff:
            skipped += 1
            continue
        if saved_models.get_model_by_source_training_id(record.training_id) is not None:
            skipped += 1
            continue
        try:
            _remove_training_queue_entry(
                record=record,
                registry=registry,
                saved_models=saved_models,
                results_storage=results_storage,
                clock=clock,
            )
            removed += 1
        except Exception:
            failed += 1
            logger.exception(
                "Failed to cleanup expired System Discovery training '%s'",
                record.training_id,
            )
    return CleanupExpiredSystemDiscoveryTrainingQueueEntriesResult(
        examined_count=examined,
        removed_count=removed,
        skipped_count=skipped,
        failed_count=failed,
    )


def _remove_training_queue_entry(
    *,
    record: SystemDiscoveryTrainingRecord,
    registry: SystemDiscoveryTrainingRegistryPort,
    saved_models: SystemDiscoverySavedModelRegistryPort,
    results_storage: SystemDiscoveryTrainingResultsStoragePort,
    clock: Clock,
) -> None:
    saved = saved_models.get_model_by_source_training_id(record.training_id)
    if saved is not None:
        logger.info(
            "Removing System Discovery queue entry '%s' without touching saved model '%s'",
            record.training_id,
            saved.model_id,
        )
    results_storage.remove_training_workspace(record.training_id)
    registry.archive_training(record.training_id, archived_at=clock.now())


def handle_list_saved_system_discovery_models(
    message: ListSavedSystemDiscoveryModels,
    saved_models: SystemDiscoverySavedModelRegistryPort,
) -> ListSavedSystemDiscoveryModelsResult:
    models, total = paginate(saved_models.list_models(), message.page, message.per_page)
    return ListSavedSystemDiscoveryModelsResult(
        models=list(models),
        page=message.page,
        per_page=message.per_page,
        total=total,
    )


def handle_get_saved_system_discovery_model_details(
    message: GetSavedSystemDiscoveryModelDetails,
    saved_models: SystemDiscoverySavedModelRegistryPort,
) -> GetSavedSystemDiscoveryModelDetailsResult:
    model = saved_models.get_model(message.model_id)
    if model is None:
        raise NotFoundError(
            f"System Discovery saved model '{message.model_id}' was not found"
        )
    return GetSavedSystemDiscoveryModelDetailsResult(model=model)


def _cache_completed_results(
    record: SystemDiscoveryTrainingRecord,
    *,
    system_discovery: SystemDiscoveryPort,
    registry: SystemDiscoveryTrainingRegistryPort,
    results_storage: SystemDiscoveryTrainingResultsStoragePort,
    clock: Clock,
    failures: list[SystemDiscoveryTrainingRefreshFailure],
) -> SystemDiscoveryTrainingRecord:
    try:
        archive = system_discovery.download_training_results(record.training_id)
        archive_path = results_storage.store_results_archive(
            record.training_id,
            archive.content,
        )
        return registry.update_training_results_cache(
            record.training_id,
            results_archive_path=archive_path,
            results_cached_at=clock.now(),
            results_cache_error=None,
        )
    except Exception as exc:
        failures.append(_refresh_failure(record.training_id, exc))
        return registry.update_training_results_cache(
            record.training_id,
            results_archive_path=record.results_archive_path,
            results_cached_at=record.results_cached_at,
            results_cache_error=str(exc),
        )


def _requires_results_cache(record: SystemDiscoveryTrainingRecord) -> bool:
    return record.state == SystemDiscoveryTrainingState.COMPLETED and not (
        record.results_archive_path
        and record.results_cached_at is not None
        and not record.results_cache_error
    )


def _normalize_cached_archive_reference(
    record: SystemDiscoveryTrainingRecord,
    registry: SystemDiscoveryTrainingRegistryPort,
    results_storage: SystemDiscoveryTrainingResultsStoragePort,
) -> SystemDiscoveryTrainingRecord:
    if not record.results_archive_path:
        return record
    if not hasattr(results_storage, "normalize_results_archive_key"):
        return record
    normalized = results_storage.normalize_results_archive_key(
        record.training_id,
        record.results_archive_path,
    )
    if normalized == record.results_archive_path:
        return record
    return registry.update_training_results_cache(
        record.training_id,
        results_archive_path=normalized,
        results_cached_at=record.results_cached_at,
        results_cache_error=record.results_cache_error,
    )


def _scatter_diagonal_lines(
    results_storage: SystemDiscoveryTrainingResultsStoragePort,
    training_id: str,
) -> list[PlotDiagonalLine]:
    bounds = results_storage.get_evaluation_artifact_bounds(training_id, "scatter.csv")
    if bounds is None:
        return []
    data_min, data_max = bounds
    return [
        PlotDiagonalLine(
            p_start=(data_min, data_min),
            p_end=(data_max, data_max),
            color="red",
            dash="dot",
        )
    ]


def _evaluation_plot(
    *,
    training_id: str,
    artifact_name: str,
    title: str,
    plot_type: str,
    results_storage: SystemDiscoveryTrainingResultsStoragePort,
    visualization: VisualizationPort,
    plotsIds: PlotMapping,
    diagonal_lines: list[PlotDiagonalLine] | None = None,
) -> SystemDiscoveryTrainingEvaluationPlot:
    plot_spec = PlotSpec(
        plot_type=plot_type,
        vertical_lines=[],
        areas=[],
        annotations=[],
        diagonal_lines=diagonal_lines or [],
    )
    series_id = f"system-discovery-training-evaluation:{training_id}:{artifact_name}"
    try:
        html_id = plotsIds.get(series_id, plot_spec)
        if html_id is None:
            html_id = visualization.render_plot(
                zip_csv_bytes=results_storage.get_evaluation_artifact_zip(
                    training_id,
                    artifact_name,
                ),
                plot_spec=plot_spec,
            )
            plotsIds.store(series_id, plot_spec, html_id)

        status = visualization.get_plot_status(html_id)
        if status != "done":
            return SystemDiscoveryTrainingEvaluationPlot(
                title=title,
                state=SystemDiscoveryTrainingEvaluationPlotState.PENDING,
                plot_html=None,
                waiting_message="Waiting for visualization.",
            )
        return SystemDiscoveryTrainingEvaluationPlot(
            title=title,
            state=SystemDiscoveryTrainingEvaluationPlotState.READY,
            plot_html=visualization.get_plot_html(html_id),
            waiting_message="",
        )
    except ExternalServiceError as exc:
        if not _is_visualization_unavailable(exc):
            raise
        logger.warning(
            "System Discovery evaluation visualization unavailable for training '%s' artifact '%s': %s",
            training_id,
            artifact_name,
            exc,
        )
        return SystemDiscoveryTrainingEvaluationPlot(
            title=title,
            state=SystemDiscoveryTrainingEvaluationPlotState.UNAVAILABLE,
            plot_html=None,
            waiting_message="",
        )


def _is_visualization_unavailable(exc: ExternalServiceError) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "request failed",
            "connection refused",
            "connection reset",
            "timed out",
            "timeout",
            "temporarily unavailable",
            "service unavailable",
            "status=503",
            "status 503",
        )
    )


def _is_finished(record: SystemDiscoveryTrainingRecord) -> bool:
    return record.state in {
        SystemDiscoveryTrainingState.COMPLETED,
        SystemDiscoveryTrainingState.FAILED,
    }


def _refresh_failure(
    training_id: str, exc: Exception
) -> SystemDiscoveryTrainingRefreshFailure:
    return SystemDiscoveryTrainingRefreshFailure(
        training_id=training_id,
        error=str(exc),
    )


def normalize_system_discovery_training_state(
    *,
    status: str | None,
    error: str | None,
) -> SystemDiscoveryTrainingState:
    if error:
        return SystemDiscoveryTrainingState.FAILED

    normalized = (status or "").strip().lower()
    if normalized in {"failed", "error"}:
        return SystemDiscoveryTrainingState.FAILED
    if normalized in {"completed", "success", "succeeded", "finished"}:
        return SystemDiscoveryTrainingState.COMPLETED
    if normalized in {
        "running",
        "in_progress",
        "processing",
        "started",
        "training started",
    }:
        return SystemDiscoveryTrainingState.RUNNING
    if normalized in {"queued", "pending", "created"}:
        return SystemDiscoveryTrainingState.QUEUED
    return SystemDiscoveryTrainingState.QUEUED


def _require_known_training(
    registry: SystemDiscoveryTrainingRegistryPort,
    training_id: str,
) -> SystemDiscoveryTrainingRecord:
    record = registry.get_training(training_id)
    if record is None:
        raise NotFoundError(f"System Discovery training '{training_id}' is not known")
    return record


def _update_record_from_status(
    registry: SystemDiscoveryTrainingRegistryPort,
    clock: Clock,
    status: SystemDiscoveryTrainingStatus,
) -> SystemDiscoveryTrainingRecord:
    return registry.update_training_status(
        status.training_id,
        state=normalize_system_discovery_training_state(
            status=status.status,
            error=status.error,
        ),
        raw_status=status.status,
        training_status=status.training_status,
        evaluation_status=status.evaluation_status,
        error=status.error,
        updated_at=clock.now(),
    )
