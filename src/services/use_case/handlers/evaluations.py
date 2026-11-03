from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timezone
from typing import Any

from services.use_case.utils.plot_mapping import PlotMapping
from services.use_case.utils.pagination import paginate
from use_case_contracts.dtos import (
    EvaluationProgress,
    EvaluationResult,
    EvaluationSummary,
    EvaluationVisualization,
    EvaluationVisualizationState,
    GetEvaluationDetailsResult,
    ListEvaluationsResult,
    PlotSpec,
)
from use_case_contracts.errors import (
    ConflictError,
    ExternalServiceError,
    NotFoundError,
)
from use_case_contracts.messages import (
    GetEvaluationDetails,
    ListEvaluations,
    RunEvaluation,
)
from use_case_contracts.ports import EvaluatorPort, VisualizationPort

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({"success", "failed"})

_MIN_DATETIME = datetime.min.replace(tzinfo=timezone.utc)


def handle_run_evaluation(
    message: RunEvaluation,
    evaluator: EvaluatorPort,
) -> EvaluationSummary:
    evaluation_id = evaluator.evaluate(
        message.simulator_id,
        number_of_repetitions=message.number_of_repetitions,
        kmax=message.kmax,
        epsilon=message.epsilon,
        batch_size=message.batch_size,
        lhs_candidates=message.lhs_candidates,
        random_state=message.random_state,
        problem=message.problem,
        aggregation=message.aggregation,
    )
    status = evaluator.get_evaluation_status(evaluation_id)
    return EvaluationSummary(
        evaluation_id=evaluation_id,
        simulator_id=message.simulator_id,
        status=status,
    )


def handle_list_evaluations(
    message: ListEvaluations,
    evaluator: EvaluatorPort,
) -> ListEvaluationsResult:
    all_evaluations = evaluator.list_evaluations()
    all_evaluations = sorted(
        all_evaluations,
        key=lambda item: item.created_at or _MIN_DATETIME,
        reverse=True,
    )
    evaluations, total = paginate(all_evaluations, message.page, message.per_page)
    return ListEvaluationsResult(
        evaluations=list(evaluations),
        page=message.page,
        per_page=message.per_page,
        total=total,
    )


def handle_get_evaluation_details(
    message: GetEvaluationDetails,
    evaluator: EvaluatorPort,
    visualization: VisualizationPort,
    plotsIds: PlotMapping,
) -> GetEvaluationDetailsResult:
    status = evaluator.get_evaluation_status(message.evaluation_id)
    summaries = {item.evaluation_id: item for item in evaluator.list_evaluations()}
    summary = summaries.get(message.evaluation_id)

    result: EvaluationResult | None = None
    if status in _TERMINAL_STATUSES:
        try:
            result = evaluator.get_evaluation_results(message.evaluation_id)
        except ConflictError:
            result = None

    progress = _evaluation_progress(evaluator, message.evaluation_id)
    history = _ssbo_history(progress, result)
    parameters = _important_parameters(progress, result)

    return GetEvaluationDetailsResult(
        evaluation_id=message.evaluation_id,
        simulator_id=summary.simulator_id if summary is not None else "",
        status=status,
        created_at=summary.created_at if summary is not None else None,
        result=result,
        convergence_visualization=_convergence_visualization(
            message.evaluation_id,
            history=history,
            visualization=visualization,
            plotsIds=plotsIds,
        ),
        exploration_visualization=_exploration_visualization(
            message.evaluation_id,
            history=history,
            parameters=parameters,
            visualization=visualization,
            plotsIds=plotsIds,
        ),
        progress=progress,
    )


def _evaluation_progress(
    evaluator: EvaluatorPort, evaluation_id: str
) -> EvaluationProgress | None:
    """Read live progress, tolerating evaluators that do not expose it."""
    try:
        return evaluator.get_evaluation_progress(evaluation_id)
    except (ConflictError, NotFoundError, ExternalServiceError) as exc:
        logger.info(
            "No live progress available for evaluation '%s': %s", evaluation_id, exc
        )
        return None
    except Exception:
        logger.exception(
            "Unexpected failure reading progress for evaluation '%s'", evaluation_id
        )
        return None


def _ssbo_history(
    progress: EvaluationProgress | None, result: EvaluationResult | None
) -> list[dict]:
    """Prefer the live history, falling back to the archived one."""
    if progress is not None and progress.ssbo_history:
        return list(progress.ssbo_history)
    if result is not None and result.details:
        history = result.details.get("history") or []
        if isinstance(history, list):
            return [entry for entry in history if isinstance(entry, dict)]
    return []


def _important_parameters(
    progress: EvaluationProgress | None, result: EvaluationResult | None
) -> list[str]:
    if progress is not None and progress.important_parameters:
        return list(progress.important_parameters)
    if result is not None and result.details:
        names = result.details.get("important_parameters") or []
        if isinstance(names, list):
            return [str(name) for name in names]
    return []


def _convergence_points(history: list[dict]) -> list[tuple[float, float]]:
    return [
        (float(entry["iteration"]), float(entry["best_value"]))
        for entry in history
        if entry.get("iteration") is not None and entry.get("best_value") is not None
    ]


def _convergence_visualization(
    evaluation_id: str,
    *,
    history: list[dict],
    visualization: VisualizationPort,
    plotsIds: PlotMapping,
) -> EvaluationVisualization:
    points = _convergence_points(history)
    if not points:
        return EvaluationVisualization(state=EvaluationVisualizationState.NOT_READY)

    plot_spec = PlotSpec(
        plot_type="Line",
        vertical_lines=[],
        areas=[],
        annotations=[],
        diagonal_lines=[],
        xaxis_title="Iteration",
        yaxis_title="Best value",
        title="SSBO convergence",
    )
    # The plot grows with every iteration, so the cache key carries the length
    # to make sure a newer history is never served from a stale render.
    series_id = f"evaluation:{evaluation_id}:convergence:{len(points)}"
    return _render_evaluation_plot(
        series_id=series_id,
        zip_csv_bytes=_convergence_zip_bytes(points),
        plot_spec=plot_spec,
        label="convergence",
        visualization=visualization,
        plotsIds=plotsIds,
    )


def _exploration_points(
    history: list[dict],
) -> list[tuple[float, float]]:
    """Objective value of each evaluated point, against its first coordinate.

    An SSBO iteration evaluates a batch of candidates, so the history stores
    parallel ``new_points``/``new_values`` lists. Older rows only carry the
    single ``new_point``/``new_value`` pair, which is handled as a fallback.
    """
    points: list[tuple[float, float]] = []
    for entry in history:
        if entry.get("skipped"):
            continue
        for point, value in _iter_evaluated_points(entry):
            if point:
                try:
                    points.append((float(point[0]), float(value)))
                except (TypeError, ValueError):
                    continue
    return points


def _iter_evaluated_points(entry: dict) -> list[tuple[list, float]]:
    points = entry.get("new_points")
    values = entry.get("new_values")
    if isinstance(points, list) and isinstance(values, list) and len(points) == len(values):
        return [(point, value) for point, value in zip(points, values)]

    point = entry.get("new_point")
    value = entry.get("new_value")
    if point is None or value is None:
        return []
    # The legacy record stores a 2-D batch with a single scalar value that
    # belongs to the last candidate, so only that one can be paired up.
    if isinstance(point, list) and point and isinstance(point[0], list):
        return [(point[-1], value)] if point[-1] else []
    if isinstance(value, list):
        value = value[-1] if value else None
    if value is None:
        return []
    return [(point, value)]


def _exploration_visualization(
    evaluation_id: str,
    *,
    history: list[dict],
    parameters: list[str],
    visualization: VisualizationPort,
    plotsIds: PlotMapping,
) -> EvaluationVisualization:
    points = _exploration_points(history)
    if not points:
        return EvaluationVisualization(state=EvaluationVisualizationState.NOT_READY)

    # The scatter renderer treats the first CSV column as x and the rest as y
    # series, so exactly two columns are emitted here.
    x_name = parameters[0] if parameters else "point[0]"
    remaining = parameters[1:] if len(parameters) > 1 else []
    subtitle = (
        f" (also optimising: {', '.join(remaining)})" if remaining else ""
    )
    plot_spec = PlotSpec(
        plot_type="Scatter",
        vertical_lines=[],
        areas=[],
        annotations=[],
        diagonal_lines=[],
        xaxis_title=x_name,
        yaxis_title="Objective value",
        title=f"Explored points{subtitle}",
    )
    series_id = f"evaluation:{evaluation_id}:exploration:{len(points)}"
    return _render_evaluation_plot(
        series_id=series_id,
        zip_csv_bytes=_exploration_zip_bytes(points, x_name),
        plot_spec=plot_spec,
        label="exploration",
        visualization=visualization,
        plotsIds=plotsIds,
    )


def _render_evaluation_plot(
    *,
    series_id: str,
    zip_csv_bytes: bytes,
    plot_spec: PlotSpec,
    label: str,
    visualization: VisualizationPort,
    plotsIds: PlotMapping,
) -> EvaluationVisualization:
    try:
        html_id = plotsIds.get(series_id, plot_spec)
        if html_id is None:
            html_id = visualization.render_plot(
                zip_csv_bytes=zip_csv_bytes,
                plot_spec=plot_spec,
            )
            plotsIds.store(series_id, plot_spec, html_id)
        status = visualization.get_plot_status(html_id)
        if status != "done":
            return EvaluationVisualization(
                state=EvaluationVisualizationState.PENDING,
                waiting_message=f"Waiting for visualization, current status: {status}",
            )
        return EvaluationVisualization(
            state=EvaluationVisualizationState.READY,
            plot_html=visualization.get_plot_html(html_id),
        )
    except ExternalServiceError as exc:
        logger.warning(
            "Evaluation %s visualization unavailable for '%s': %s",
            label,
            series_id,
            exc,
        )
        return EvaluationVisualization(state=EvaluationVisualizationState.UNAVAILABLE)


def _convergence_zip_bytes(points: list[tuple[float, float]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["iteration", "best_value"])
    for iteration, best_value in points:
        writer.writerow((iteration, best_value))
    return _zip_single_csv(buffer.getvalue())


def _exploration_zip_bytes(
    points: list[tuple[float, float]], x_name: str
) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([x_name, "objective"])
    for x_value, y_value in points:
        writer.writerow((x_value, y_value))
    return _zip_single_csv(buffer.getvalue())


def _zip_single_csv(content: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("series.csv", content)
    return out.getvalue()
