from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from use_case_contracts.dtos import EvaluationSummary
from use_case_contracts.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from use_case_contracts.messages import (
    GetEvaluationDetails,
    GetSimulatorDetails,
    ListEvaluations,
    ListSimulators,
    OpenEvaluationRunForm,
    RunEvaluation,
)
from services.front.pagination import (
    build_page_items,
    parse_per_page,
    parse_positive_int,
    total_pages as _compute_total_pages,
)

_STATUS_LABELS = {
    "queued": "Queued",
    "running": "Running",
    "simulating": "Simulating",
    "sensitivity_analysis": "Sensitivity analysis",
    "optimizing": "Optimizing",
    "success": "Success",
    "failed": "Failed",
}

_STATUS_BADGES = {
    "queued": "secondary",
    "running": "warning",
    "simulating": "info",
    "sensitivity_analysis": "info",
    "optimizing": "info",
    "success": "success",
    "failed": "danger",
}

_TERMINAL_STATUSES = frozenset({"success", "failed"})

_NUMERIC_TYPES = frozenset({"int", "float", "number"})


def evaluation_run():
    usecases = current_app.extensions.get("usecases")
    if usecases is not None:
        usecases.handle(OpenEvaluationRunForm())
    models = _load_models()
    return render_template(
        "evaluation_run.html",
        models=models,
        active_page="evaluation_run",
        error_message=None,
    )


def evaluation_params(model_id: str):
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return jsonify({"input_params": [], "output_params": []})
    details = usecases.handle(GetSimulatorDetails(simulator_id=model_id))
    return jsonify(
        {
            "input_params": _extract_params(details.input_params or []),
            "output_params": _extract_params(details.output_params or []),
        }
    )


def evaluation_submit():
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return render_template(
            "evaluation_run.html",
            models=_load_models(),
            active_page="evaluation_run",
            error_message="Use-case adapter is not configured.",
        )
    try:
        message = _parse_run_evaluation()
        summary = usecases.handle(message)
        return redirect(
            url_for("onEvaluationDetails", evaluation_id=summary.evaluation_id)
        )
    except (ValidationError, NotFoundError, AuthenticationError, ExternalServiceError) as exc:
        return render_template(
            "evaluation_run.html",
            models=_load_models(),
            active_page="evaluation_run",
            error_message=str(exc),
        )


def evaluation_queue():
    usecases = current_app.extensions.get("usecases")
    page = parse_positive_int(request.args.get("page"), default=1)
    per_page = parse_per_page(request.args.get("per_page"), default=20)
    items: list[EvaluationSummary] = []
    total = 0
    if usecases is not None:
        try:
            result = usecases.handle(ListEvaluations(page=page, per_page=per_page))
            items = result.evaluations
            total = result.total
        except (AuthenticationError, ExternalServiceError) as exc:
            flash(str(exc), "warning")
    rows = [_summary_to_row(item) for item in items]
    total_pages = _compute_total_pages(total, per_page)
    return render_template(
        "evaluation_queue.html",
        evaluations=rows,
        active_page="evaluation_queue",
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        page_items=build_page_items(total_pages, page),
    )


def evaluation_details(evaluation_id: str):
    usecases = current_app.extensions.get("usecases")
    context: Dict[str, Any] = {
        "active_page": "evaluation_queue",
        "evaluation_id": evaluation_id,
        "simulator_id": "",
        "status": "",
        "status_label": "",
        "badge_class": "",
        "created_at": None,
        "result": None,
        "convergence_state": "not_ready",
        "convergence_html": None,
        "convergence_message": "",
        "exploration_state": "not_ready",
        "exploration_html": None,
        "exploration_message": "",
        "progress": None,
        "is_running": False,
        "error_message": None,
    }
    if usecases is None:
        context["error_message"] = "Use-case adapter is not configured."
        return render_template("evaluation_detail.html", **context), 503
    try:
        details = usecases.handle(GetEvaluationDetails(evaluation_id=evaluation_id))
        convergence = details.convergence_visualization
        exploration = details.exploration_visualization
        context.update(
            {
                "simulator_id": details.simulator_id,
                "status": details.status,
                "status_label": _status_label(details.status),
                "badge_class": _badge_class(details.status),
                "created_at": _format_datetime(details.created_at),
                "result": details.result,
                "convergence_state": _plot_state(convergence),
                "convergence_html": (
                    convergence.plot_html if convergence is not None else None
                ),
                "convergence_message": _plot_message(convergence),
                "exploration_state": _plot_state(exploration),
                "exploration_html": (
                    exploration.plot_html if exploration is not None else None
                ),
                "exploration_message": _plot_message(exploration),
                "progress": _progress_view(details.progress),
                "is_running": details.status not in _TERMINAL_STATUSES,
            }
        )
        return render_template("evaluation_detail.html", **context)
    except NotFoundError as exc:
        context["error_message"] = str(exc)
        return render_template("evaluation_detail.html", **context), 404
    except ValidationError as exc:
        context["error_message"] = str(exc)
        return render_template("evaluation_detail.html", **context), 400
    except AuthenticationError as exc:
        context["error_message"] = str(exc)
        return render_template("evaluation_detail.html", **context), 502
    except ExternalServiceError as exc:
        context["error_message"] = str(exc)
        return render_template("evaluation_detail.html", **context), 502


def _plot_state(visualization) -> str:
    if visualization is None:
        return "not_ready"
    return visualization.state.value


def _plot_message(visualization) -> str:
    if visualization is None or not visualization.waiting_message:
        return "Waiting for visualization."
    return visualization.waiting_message


def _progress_view(progress) -> Dict[str, Any] | None:
    if progress is None:
        return None
    return {
        "stage": progress.stage or "-",
        "iteration": progress.iteration,
        "kmax": progress.kmax,
        "best_value": progress.best_value,
        "important_parameters": progress.important_parameters or [],
        "jobs_submitted": progress.jobs_submitted,
        "jobs_by_stage": progress.jobs_by_stage or {},
    }


def _load_models() -> List[Dict[str, str]]:
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return []
    items = usecases.handle(ListSimulators(query=None)).simulators
    return [{"id": item.simulator_id, "display": _display_name(item)} for item in items]


def _display_name(item) -> str:
    version = getattr(item, "version", "") or ""
    if version and version != "unknown":
        return f"{item.model_name} ({version})"
    return item.model_name


def _extract_params(raw: List | None) -> List[Dict[str, str]]:
    params = []
    for item in raw or []:
        if isinstance(item, dict):
            name = item.get("name")
            p_type = item.get("type")
        else:
            name = getattr(item, "name", None)
            p_type = getattr(item, "type", None)
        if name and p_type:
            params.append({"name": name, "type": str(p_type)})
    return params


def _parse_run_evaluation() -> RunEvaluation:
    form = request.form
    simulator_id = (form.get("model") or "").strip()
    output = (form.get("output") or "").strip()
    aggregation = (form.get("aggregation") or "").strip() or None

    names: List[str] = []
    bounds: List[List[float]] = []
    for key, value in form.items():
        if not key.startswith("params["):
            continue
        if not key.endswith("][min]"):
            continue
        name = key.split("[", 1)[1].split("]")[0]
        min_val = value.strip()
        max_val = (form.get(f"params[{name}][max]") or "").strip()
        if min_val and max_val:
            names.append(name)
            bounds.append([float(min_val), float(max_val)])

    problem: Dict[str, Any] | None = None
    if names and output:
        problem = {"names": names, "bounds": bounds, "output": output}

    return RunEvaluation(
        simulator_id=simulator_id,
        number_of_repetitions=int(form.get("repetitions") or 128),
        kmax=int(form.get("kmax") or 30),
        epsilon=float(form.get("epsilon") or 1e-3),
        batch_size=int(form.get("batch_size") or 1),
        lhs_candidates=int(form.get("lhs_candidates") or 1500),
        random_state=int(form.get("random_state") or 42),
        problem=problem,
        aggregation=aggregation,
    )


def _summary_to_row(summary: EvaluationSummary) -> Dict[str, Any]:
    return {
        "evaluation_id": summary.evaluation_id,
        "simulator_id": summary.simulator_id,
        "status": summary.status,
        "status_label": _status_label(summary.status),
        "badge_class": _badge_class(summary.status),
        "created_at": _format_datetime(summary.created_at),
        "detail_url": url_for(
            "onEvaluationDetails", evaluation_id=summary.evaluation_id
        ),
    }


def _status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status)


def _badge_class(status: str) -> str:
    return _STATUS_BADGES.get(status, "secondary")


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    utc_value = value.astimezone(timezone.utc)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
