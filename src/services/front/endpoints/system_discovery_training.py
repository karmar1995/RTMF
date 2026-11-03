from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timezone

from flask import current_app, flash, redirect, render_template, request, url_for

from use_case_contracts.dtos import SystemDiscoveryTrainingRecord
from use_case_contracts.dtos import SystemDiscoverySavedModelRecord
from use_case_contracts.dtos import SystemDiscoverySimulationRecord
from use_case_contracts.dtos import SystemDiscoveryTrainingEvaluationState
from use_case_contracts.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from use_case_contracts.messages import (
    GetSystemDiscoveryTrainingStatus,
    GetSavedSystemDiscoveryModelDetails,
    GetSystemDiscoverySimulationDetails,
    ListSavedSystemDiscoveryModels,
    ListSystemDiscoverySimulations,
    ListSystemDiscoveryTrainings,
    OpenSystemDiscoveryTrainingForm,
    OpenSystemDiscoveryTrainingEvaluation,
    RemoveSavedSystemDiscoveryModel,
    RemoveSystemDiscoveryTrainingQueueEntry,
    SaveSystemDiscoveryModel,
    TrainSystemDiscovery,
)
from services.front.pagination import (
    build_page_items,
    parse_per_page,
    parse_positive_int,
    total_pages as _compute_total_pages,
)


@dataclass(frozen=True)
class TrainingView:
    training_id: str
    created_at: str
    updated_at: str
    state: str
    state_label: str
    badge_class: str
    training_status: str
    evaluation_status: str
    error: str
    basis: str
    degree: int
    model: str
    nlags_x: str
    nlags_y: int
    detail_url: str
    can_evaluate: bool
    evaluation_url: str | None
    remove_url: str


@dataclass(frozen=True)
class SavedModelView:
    model_id: str
    source_training_id: str
    model_name: str
    saved_at: str
    basis: str
    degree: int
    nlags_x: str
    nlags_y: int
    detail_url: str
    remove_url: str


@dataclass(frozen=True)
class SimulationView:
    simulation_id: str
    source_model_name: str
    created_at: str
    updated_at: str
    state: str
    state_label: str
    badge_class: str
    horizon: str
    initial_conditions: str
    external_control_signals: str
    error: str
    detail_url: str


def show_training_form():
    usecases = _require_usecases()
    usecases.handle(OpenSystemDiscoveryTrainingForm())
    return render_template(
        "system_discovery_train.html",
        active_page="system_discovery_train",
        form_values={},
    )


def submit_training_form():
    form_values = _safe_training_form_values()
    try:
        message = _parse_training_message()
        usecases = _require_usecases()
        result = usecases.handle(message)
        flash(f"System Discovery training {result.training_id} was submitted.", "success")
        return redirect(
            url_for("onSystemDiscoveryTrainingDetails", training_id=result.training_id)
        )
    except (ValueError, ValidationError) as exc:
        flash(str(exc), "danger")
        return render_template(
            "system_discovery_train.html",
            active_page="system_discovery_train",
            form_values=form_values,
        ), 400
    except (AuthenticationError, ExternalServiceError) as exc:
        flash(str(exc), "warning")
        return render_template(
            "system_discovery_train.html",
            active_page="system_discovery_train",
            form_values=form_values,
        ), 502


def list_training_queue():
    usecases = _require_usecases()
    page = parse_positive_int(request.args.get("page"), default=1)
    per_page = parse_per_page(request.args.get("per_page"), default=20)
    try:
        result = usecases.handle(
            ListSystemDiscoveryTrainings(page=page, per_page=per_page)
        )
        if result.failures:
            flash(
                f"{len(result.failures)} System Discovery training update failed.",
                "warning",
            )
        trainings = [_training_view(record) for record in result.trainings]
        total_pages = _compute_total_pages(result.total, per_page)
        return render_template(
            "system_discovery_training_queue.html",
            active_page="system_discovery_training_queue",
            trainings=trainings,
            page=page,
            per_page=per_page,
            total=result.total,
            total_pages=total_pages,
            page_items=build_page_items(total_pages, page),
        )
    except (AuthenticationError, ExternalServiceError) as exc:
        flash(str(exc), "warning")
        return render_template(
            "system_discovery_training_queue.html",
            active_page="system_discovery_training_queue",
            trainings=[],
            page=page,
            per_page=per_page,
            total=0,
            total_pages=0,
            page_items=[],
        ), 502


def training_details(training_id: str):
    usecases = _require_usecases()
    try:
        result = usecases.handle(GetSystemDiscoveryTrainingStatus(training_id=training_id))
        if result.failures:
            flash("System Discovery training update failed.", "warning")
        return render_template(
            "system_discovery_training_detail.html",
            active_page="system_discovery_training_queue",
            training=_training_view(result.training),
        )
    except NotFoundError as exc:
        flash(str(exc), "warning")
        return render_template(
            "system_discovery_training_detail.html",
            active_page="system_discovery_training_queue",
            training=None,
        ), 404
    except (AuthenticationError, ExternalServiceError) as exc:
        flash(str(exc), "warning")
        return render_template(
            "system_discovery_training_detail.html",
            active_page="system_discovery_training_queue",
            training=None,
        ), 502


def training_evaluation(training_id: str):
    usecases = _require_usecases()
    try:
        result = usecases.handle(
            OpenSystemDiscoveryTrainingEvaluation(training_id=training_id)
        )
        if result.state == SystemDiscoveryTrainingEvaluationState.NOT_COMPLETED:
            flash(result.message or "Model evaluation is available only for completed trainings.", "warning")
            return render_template(
                "system_discovery_training_evaluation.html",
                active_page="system_discovery_training_queue",
                result=result,
                training=_training_view(result.training),
            ), 400
        return render_template(
            "system_discovery_training_evaluation.html",
            active_page="system_discovery_training_queue",
            result=result,
            training=_training_view(result.training),
        )
    except NotFoundError as exc:
        flash(str(exc), "warning")
        return render_template(
            "system_discovery_training_evaluation.html",
            active_page="system_discovery_training_queue",
            result=None,
            training=None,
        ), 404
    except (AuthenticationError, ExternalServiceError) as exc:
        flash(str(exc), "warning")
        return render_template(
            "system_discovery_training_evaluation.html",
            active_page="system_discovery_training_queue",
            result=None,
            training=None,
        ), 502


def save_training_model(training_id: str):
    usecases = _require_usecases()
    try:
        result = usecases.handle(SaveSystemDiscoveryModel(training_id=training_id))
        if result.simulator_registration_id:
            flash(
                "System Discovery model was saved and simulator registration submitted (build in progress).",
                "success",
            )
        else:
            flash("System Discovery model was saved.", "success")
        return redirect(
            url_for("onSystemDiscoverySavedModelDetails", model_id=result.model_id)
        )
    except (ValueError, ValidationError) as exc:
        flash(str(exc), "warning")
        return redirect(
            url_for("onSystemDiscoveryTrainingEvaluation", training_id=training_id)
        )
    except NotFoundError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("onSystemDiscoveryTrainingQueue"))
    except (AuthenticationError, ExternalServiceError) as exc:
        flash(str(exc), "warning")
        return redirect(
            url_for("onSystemDiscoveryTrainingEvaluation", training_id=training_id)
        )


def remove_training_queue_entry(training_id: str):
    usecases = _require_usecases()
    try:
        usecases.handle(RemoveSystemDiscoveryTrainingQueueEntry(training_id=training_id))
        flash("System Discovery training was removed from the local queue.", "success")
    except NotFoundError as exc:
        flash(str(exc), "warning")
    except (AuthenticationError, ExternalServiceError) as exc:
        flash(str(exc), "warning")
    return redirect(url_for("onSystemDiscoveryTrainingQueue"))


def list_saved_models():
    usecases = _require_usecases()
    page = parse_positive_int(request.args.get("page"), default=1)
    per_page = parse_per_page(request.args.get("per_page"), default=20)
    try:
        result = usecases.handle(
            ListSavedSystemDiscoveryModels(page=page, per_page=per_page)
        )
        total_pages = _compute_total_pages(result.total, per_page)
        return render_template(
            "system_discovery_saved_models.html",
            active_page="system_discovery_saved_models",
            models=[_saved_model_view(model) for model in result.models],
            page=page,
            per_page=per_page,
            total=result.total,
            total_pages=total_pages,
            page_items=build_page_items(total_pages, page),
        )
    except (AuthenticationError, ExternalServiceError) as exc:
        flash(str(exc), "warning")
        return render_template(
            "system_discovery_saved_models.html",
            active_page="system_discovery_saved_models",
            models=[],
            page=page,
            per_page=per_page,
            total=0,
            total_pages=0,
            page_items=[],
        ), 502


def saved_model_details(model_id: str):
    usecases = _require_usecases()
    try:
        result = usecases.handle(GetSavedSystemDiscoveryModelDetails(model_id=model_id))
        return render_template(
            "system_discovery_saved_model_detail.html",
            active_page="system_discovery_saved_models",
            result=result,
            model=_saved_model_view(result.model),
        )
    except NotFoundError as exc:
        flash(str(exc), "warning")
        return render_template(
            "system_discovery_saved_model_detail.html",
            active_page="system_discovery_saved_models",
            result=None,
            model=None,
        ), 404
    except (AuthenticationError, ExternalServiceError) as exc:
        flash(str(exc), "warning")
        return render_template(
            "system_discovery_saved_model_detail.html",
            active_page="system_discovery_saved_models",
            result=None,
            model=None,
        ), 502


def remove_saved_model(model_id: str):
    usecases = _require_usecases()
    try:
        usecases.handle(RemoveSavedSystemDiscoveryModel(model_id=model_id))
        flash("System Discovery saved model was removed.", "success")
    except NotFoundError as exc:
        flash(str(exc), "warning")
    except (AuthenticationError, ExternalServiceError) as exc:
        flash(str(exc), "warning")
    return redirect(url_for("onSystemDiscoverySavedModels"))


def list_system_discovery_simulations():
    usecases = _require_usecases()
    page = parse_positive_int(request.args.get("page"), default=1)
    per_page = parse_per_page(request.args.get("per_page"), default=20)
    try:
        result = usecases.handle(
            ListSystemDiscoverySimulations(page=page, per_page=per_page)
        )
        if result.failures:
            flash(
                f"{len(result.failures)} System Discovery Simulations update failed.",
                "warning",
            )
        total_pages = _compute_total_pages(result.total, per_page)
        return render_template(
            "system_discovery_simulations.html",
            active_page="system_discovery_simulations",
            simulations=[_simulation_view(record) for record in result.simulations],
            page=page,
            per_page=per_page,
            total=result.total,
            total_pages=total_pages,
            page_items=build_page_items(total_pages, page),
        )
    except (AuthenticationError, ExternalServiceError) as exc:
        flash(str(exc), "warning")
        return render_template(
            "system_discovery_simulations.html",
            active_page="system_discovery_simulations",
            simulations=[],
            page=page,
            per_page=per_page,
            total=0,
            total_pages=0,
            page_items=[],
        ), 502


def system_discovery_simulation_details(simulation_id: str):
    usecases = _require_usecases()
    try:
        result = usecases.handle(
            GetSystemDiscoverySimulationDetails(simulation_id=simulation_id)
        )
        if result.failures:
            flash("System Discovery Simulations update failed.", "warning")
        return render_template(
            "system_discovery_simulation_detail.html",
            active_page="system_discovery_simulations",
            simulation=_simulation_view(result.simulation),
            visualization=result.visualization,
        )
    except NotFoundError as exc:
        flash(str(exc), "warning")
        return render_template(
            "system_discovery_simulation_detail.html",
            active_page="system_discovery_simulations",
            simulation=None,
            visualization=None,
        ), 404
    except (AuthenticationError, ExternalServiceError) as exc:
        flash(str(exc), "warning")
        return render_template(
            "system_discovery_simulation_detail.html",
            active_page="system_discovery_simulations",
            simulation=None,
            visualization=None,
        ), 502


def _training_view(record: SystemDiscoveryTrainingRecord) -> TrainingView:
    state = record.state.value
    can_evaluate = state == "completed"
    return TrainingView(
        training_id=record.training_id,
        created_at=_format_datetime(record.created_at),
        updated_at=_format_datetime(record.updated_at),
        state=state,
        state_label=state.capitalize(),
        badge_class=_state_badge_class(state),
        training_status=record.training_status or "",
        evaluation_status=record.evaluation_status or "",
        error=record.error or "",
        basis=record.basis,
        degree=record.degree,
        model=record.model,
        nlags_x=_format_nlags_x(record.nlags_x),
        nlags_y=record.nlags_y,
        detail_url=url_for(
            "onSystemDiscoveryTrainingDetails",
            training_id=record.training_id,
        ),
        can_evaluate=can_evaluate,
        evaluation_url=url_for(
            "onSystemDiscoveryTrainingEvaluation",
            training_id=record.training_id,
        )
        if can_evaluate
        else None,
        remove_url=url_for(
            "onSystemDiscoveryTrainingRemove",
            training_id=record.training_id,
        ),
    )


def _saved_model_view(record: SystemDiscoverySavedModelRecord) -> SavedModelView:
    return SavedModelView(
        model_id=record.model_id,
        source_training_id=record.source_training_id,
        model_name=record.model_name,
        saved_at=_format_datetime(record.saved_at),
        basis=record.basis,
        degree=record.degree,
        nlags_x=_format_nlags_x(record.nlags_x),
        nlags_y=record.nlags_y,
        detail_url=url_for(
            "onSystemDiscoverySavedModelDetails",
            model_id=record.model_id,
        ),
        remove_url=url_for(
            "onSystemDiscoverySavedModelRemove",
            model_id=record.model_id,
        ),
    )


def _simulation_view(record: SystemDiscoverySimulationRecord) -> SimulationView:
    state = record.state.value
    return SimulationView(
        simulation_id=record.simulation_id,
        source_model_name=record.source_model_name,
        created_at=_format_datetime(record.created_at),
        updated_at=_format_datetime(record.updated_at),
        state=state,
        state_label=state.capitalize(),
        badge_class=_state_badge_class(state),
        horizon="—" if record.horizon is None else str(record.horizon),
        initial_conditions=_format_initial_conditions(record.initial_conditions),
        external_control_signals="Yes" if record.uses_external_control_signals else "No",
        error=record.error or "",
        detail_url=url_for(
            "onSystemDiscoverySimulationDetails",
            simulation_id=record.simulation_id,
        ),
    )


def _state_badge_class(state: str) -> str:
    return {
        "queued": "secondary",
        "running": "warning",
        "completed": "success",
        "failed": "danger",
    }.get(state, "secondary")


def _format_datetime(value) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    utc_value = value.astimezone(timezone.utc)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_usecases():
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        raise ExternalServiceError("Use-case adapter is not configured.")
    return usecases


def _parse_training_message() -> TrainSystemDiscovery:
    archive = request.files.get("training_archive")
    if archive is None or not archive.filename:
        raise ValueError("Training ZIP archive is required.")
    archive_bytes = archive.read()
    if not archive_bytes:
        raise ValueError("Training ZIP archive must not be empty.")

    return TrainSystemDiscovery(
        training_data_archive=archive_bytes,
        nlags_x=_parse_nlags_x(request.form.get("nlags-x") or ""),
        nlags_y=_parse_required_int("nlags-y"),
        basis=_parse_required_text("basis"),
        degree=_parse_required_int("degree"),
        model=_parse_required_text("model"),
    )


def _parse_nlags_x(raw: str) -> tuple[tuple[int, ...], ...] | None:
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("nlags-x must be strict JSON, for example [[1, 2], [1, 2]].") from exc
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("nlags-x must be a non-empty nested integer array.")
    rows = []
    for row in parsed:
        if not isinstance(row, list) or not row:
            raise ValueError("nlags-x must be a non-empty nested integer array.")
        values = []
        for value in row:
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("nlags-x must contain integers only.")
            values.append(value)
        rows.append(tuple(values))
    return tuple(rows)


def _parse_required_int(name: str) -> int:
    raw = (request.form.get(name) or "").strip()
    if not raw:
        raise ValueError(f"{name} is required.")
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _parse_required_text(name: str) -> str:
    value = (request.form.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required.")
    return value


def _parse_required_int(name: str) -> int:
    raw = (request.form.get(name) or "").strip()
    if not raw:
        raise ValueError(f"{name} is required.")
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _parse_required_text(name: str) -> str:
    value = (request.form.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required.")
    return value


def _format_initial_conditions(values: tuple[float, ...] | None) -> str:
    if values is None:
        return "—"
    return " ".join(str(value) for value in values)


def _format_nlags_x(values: tuple[tuple[int, ...], ...] | None) -> str:
    if values is None:
        return "—"
    return json.dumps([list(row) for row in values])


def _safe_training_form_values() -> dict[str, str]:
    return {
        "nlags-x": request.form.get("nlags-x", ""),
        "nlags-y": request.form.get("nlags-y", ""),
        "basis": request.form.get("basis", ""),
        "degree": request.form.get("degree", ""),
        "model": request.form.get("model", ""),
    }
