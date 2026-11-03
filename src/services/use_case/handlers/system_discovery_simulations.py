from __future__ import annotations

import logging

from services.use_case.ports import Clock
from services.use_case.utils.plot_mapping import PlotMapping
from services.use_case.utils.pagination import paginate
from use_case_contracts.dtos import (
    GetSystemDiscoverySimulationDetailsResult,
    ListSystemDiscoverySimulationsResult,
    PlotSpec,
    SystemDiscoverySimulationRecord,
    SystemDiscoverySimulationRefreshFailure,
    SystemDiscoverySimulationRequest,
    SystemDiscoverySimulationState,
    SystemDiscoverySimulationStatus,
    SystemDiscoverySimulationVisualization,
    SystemDiscoverySimulationVisualizationState,
    SystemDiscoverySimulationResultsArchive,
)
from use_case_contracts.errors import ExternalServiceError, NotFoundError
from use_case_contracts.messages import (
    GetSystemDiscoverySimulationDetails,
    ListSystemDiscoverySimulations,
)
from use_case_contracts.ports import (
    SystemDiscoveryAIStorPort,
    SystemDiscoveryPort,
    SystemDiscoverySimulationRegistryPort,
    SystemDiscoverySimulationResultsArchivePostprocessorPort,
    SystemDiscoverySimulationResultsPreparerPort,
    VisualizationPort,
)

logger = logging.getLogger(__name__)


def handle_list_system_discovery_simulations(
    message: ListSystemDiscoverySimulations,
    *,
    system_discovery: SystemDiscoveryPort,
    registry: SystemDiscoverySimulationRegistryPort,
    aistor: SystemDiscoveryAIStorPort,
    results_postprocessor: SystemDiscoverySimulationResultsArchivePostprocessorPort,
    clock: Clock,
) -> ListSystemDiscoverySimulationsResult:
    failures: list[SystemDiscoverySimulationRefreshFailure] = []
    for record in registry.list_simulations():
        current = record
        if not _is_finished(current):
            try:
                status = system_discovery.get_system_discovery_simulation_status(
                    current.simulation_id
                )
                current = _update_record_from_status(registry, clock, status)
            except Exception as exc:
                failures.append(_refresh_failure(current.simulation_id, exc))
        if _requires_result_transfer(current):
            _transfer_completed_results(
                current,
                system_discovery=system_discovery,
                registry=registry,
                aistor=aistor,
                results_postprocessor=results_postprocessor,
                clock=clock,
                failures=failures,
            )
    all_simulations = registry.list_simulations()
    simulations, total = paginate(all_simulations, message.page, message.per_page)
    return ListSystemDiscoverySimulationsResult(
        simulations=list(simulations),
        failures=failures,
        page=message.page,
        per_page=message.per_page,
        total=total,
    )


def handle_get_system_discovery_simulation_details(
    message: GetSystemDiscoverySimulationDetails,
    *,
    system_discovery: SystemDiscoveryPort,
    registry: SystemDiscoverySimulationRegistryPort,
    aistor: SystemDiscoveryAIStorPort,
    results_postprocessor: SystemDiscoverySimulationResultsArchivePostprocessorPort,
    results_preparer: SystemDiscoverySimulationResultsPreparerPort,
    visualization: VisualizationPort,
    plotsIds: PlotMapping,
    clock: Clock,
) -> GetSystemDiscoverySimulationDetailsResult:
    record = _require_known_simulation(registry, message.simulation_id)
    failures: list[SystemDiscoverySimulationRefreshFailure] = []
    if not _is_finished(record):
        try:
            status = system_discovery.get_system_discovery_simulation_status(
                record.simulation_id
            )
            record = _update_record_from_status(registry, clock, status)
        except Exception as exc:
            failures.append(_refresh_failure(record.simulation_id, exc))
    if _requires_result_transfer(record):
        record = _transfer_completed_results(
            record,
            system_discovery=system_discovery,
            registry=registry,
            aistor=aistor,
            results_postprocessor=results_postprocessor,
            clock=clock,
            failures=failures,
        )
    return GetSystemDiscoverySimulationDetailsResult(
        simulation=record,
        visualization=_simulation_plot(
            record,
            registry=registry,
            aistor=aistor,
            results_postprocessor=results_postprocessor,
            results_preparer=results_preparer,
            visualization=visualization,
            plotsIds=plotsIds,
            failures=failures,
        ),
        failures=failures,
    )


def normalize_system_discovery_simulation_state(
    *,
    status: str | None,
    error: str | None,
) -> SystemDiscoverySimulationState:
    if error:
        return SystemDiscoverySimulationState.FAILED
    normalized = (status or "").strip().lower()
    if normalized in {"failed", "error"}:
        return SystemDiscoverySimulationState.FAILED
    if normalized in {"completed", "success", "succeeded", "finished"}:
        return SystemDiscoverySimulationState.COMPLETED
    if normalized in {
        "simulation started",
        "running",
        "started",
        "processing",
        "in_progress",
    }:
        return SystemDiscoverySimulationState.RUNNING
    if normalized in {"queued", "pending", "created"}:
        return SystemDiscoverySimulationState.QUEUED
    return SystemDiscoverySimulationState.QUEUED


def _update_record_from_status(
    registry: SystemDiscoverySimulationRegistryPort,
    clock: Clock,
    status: SystemDiscoverySimulationStatus,
) -> SystemDiscoverySimulationRecord:
    return registry.update_simulation_status(
        status.simulation_id,
        state=normalize_system_discovery_simulation_state(
            status=status.status,
            error=status.error,
        ),
        raw_status=status.status,
        error=status.error,
        updated_at=clock.now(),
    )


def _transfer_completed_results(
    record: SystemDiscoverySimulationRecord,
    *,
    system_discovery: SystemDiscoveryPort,
    registry: SystemDiscoverySimulationRegistryPort,
    aistor: SystemDiscoveryAIStorPort,
    results_postprocessor: SystemDiscoverySimulationResultsArchivePostprocessorPort,
    clock: Clock,
    failures: list[SystemDiscoverySimulationRefreshFailure],
) -> SystemDiscoverySimulationRecord:
    try:
        archive = system_discovery.download_system_discovery_simulation_results(
            record.simulation_id
        )
        postprocessed = results_postprocessor.postprocess(archive)
        stored = aistor.upload_results_archive(
            simulation_id=record.simulation_id,
            content=postprocessed.archive.content,
        )
        return registry.update_simulation_aistor_result(
            record.simulation_id,
            aistor_object_key=stored.storage_reference,
            aistor_uploaded_at=clock.now(),
            aistor_upload_error=None,
        )
    except Exception as exc:
        failures.append(_refresh_failure(record.simulation_id, exc))
        return registry.update_simulation_aistor_result(
            record.simulation_id,
            aistor_object_key=record.aistor_object_key,
            aistor_uploaded_at=record.aistor_uploaded_at,
            aistor_upload_error=str(exc),
        )


def _simulation_plot(
    record: SystemDiscoverySimulationRecord,
    *,
    registry: SystemDiscoverySimulationRegistryPort,
    aistor: SystemDiscoveryAIStorPort,
    results_postprocessor: SystemDiscoverySimulationResultsArchivePostprocessorPort,
    results_preparer: SystemDiscoverySimulationResultsPreparerPort,
    visualization: VisualizationPort,
    plotsIds: PlotMapping,
    failures: list[SystemDiscoverySimulationRefreshFailure],
) -> SystemDiscoverySimulationVisualization:
    if record.state != SystemDiscoverySimulationState.COMPLETED or not record.aistor_object_key:
        return SystemDiscoverySimulationVisualization(
            state=SystemDiscoverySimulationVisualizationState.NOT_READY
        )
    plot_spec = PlotSpec(plot_type="Line", vertical_lines=[], areas=[], annotations=[], diagonal_lines=[])
    series_id = f"system-discovery-simulation:{record.simulation_id}:results.csv"
    try:
        try:
            results_archive = _canonical_stored_results_archive(
                record,
                registry=registry,
                aistor=aistor,
                results_postprocessor=results_postprocessor,
            )
        except Exception as exc:
            failures.append(_refresh_failure(record.simulation_id, exc))
            return SystemDiscoverySimulationVisualization(
                state=SystemDiscoverySimulationVisualizationState.UNAVAILABLE
            )
        html_id = record.visualization_plot_id or plotsIds.get(series_id, plot_spec)
        if html_id is None:
            html_id = visualization.render_plot(
                zip_csv_bytes=results_preparer.prepare_results_csv_zip(
                    results_archive
                ),
                plot_spec=plot_spec,
            )
            plotsIds.store(series_id, plot_spec, html_id)
            registry.update_simulation_visualization(
                record.simulation_id,
                visualization_plot_id=html_id,
            )
        status = visualization.get_plot_status(html_id)
        if status != "done":
            return SystemDiscoverySimulationVisualization(
                state=SystemDiscoverySimulationVisualizationState.PENDING,
                waiting_message="Waiting for visualization.",
            )
        return SystemDiscoverySimulationVisualization(
            state=SystemDiscoverySimulationVisualizationState.READY,
            plot_html=visualization.get_plot_html(html_id),
        )
    except ExternalServiceError as exc:
        if not _is_visualization_unavailable(exc):
            raise
        logger.warning(
            "System Discovery simulation visualization unavailable for '%s': %s",
            record.simulation_id,
            exc,
        )
        return SystemDiscoverySimulationVisualization(
            state=SystemDiscoverySimulationVisualizationState.UNAVAILABLE
        )


def _canonical_stored_results_archive(
    record: SystemDiscoverySimulationRecord,
    *,
    registry: SystemDiscoverySimulationRegistryPort,
    aistor: SystemDiscoveryAIStorPort,
    results_postprocessor: SystemDiscoverySimulationResultsArchivePostprocessorPort,
) -> bytes:
    raw_archive = aistor.download_results_archive(record.simulation_id)
    postprocessed = results_postprocessor.postprocess(
        SystemDiscoverySimulationResultsArchive(content=raw_archive)
    )
    if postprocessed.was_modified:
        stored = aistor.upload_results_archive(
            simulation_id=record.simulation_id,
            content=postprocessed.archive.content,
        )
        registry.update_simulation_aistor_result(
            record.simulation_id,
            aistor_object_key=stored.storage_reference,
            aistor_uploaded_at=record.aistor_uploaded_at,
            aistor_upload_error=record.aistor_upload_error,
        )
    return postprocessed.archive.content


def _requires_result_transfer(record: SystemDiscoverySimulationRecord) -> bool:
    return (
        record.state == SystemDiscoverySimulationState.COMPLETED
        and not (
            record.aistor_object_key
            and record.aistor_uploaded_at is not None
            and not record.aistor_upload_error
        )
    )


def _is_finished(record: SystemDiscoverySimulationRecord) -> bool:
    return record.state in {
        SystemDiscoverySimulationState.COMPLETED,
        SystemDiscoverySimulationState.FAILED,
    }


def _require_known_simulation(
    registry: SystemDiscoverySimulationRegistryPort,
    simulation_id: str,
) -> SystemDiscoverySimulationRecord:
    record = registry.get_simulation(simulation_id)
    if record is None:
        raise NotFoundError(
            f"System Discovery simulation '{simulation_id}' is not known"
        )
    return record


def _refresh_failure(
    simulation_id: str,
    exc: Exception,
) -> SystemDiscoverySimulationRefreshFailure:
    return SystemDiscoverySimulationRefreshFailure(
        simulation_id=simulation_id,
        error=str(exc),
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
