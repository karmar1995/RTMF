from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Dict, List

from flask import current_app, render_template, request, jsonify, redirect, url_for

from use_case_contracts.dtos import SubJobInfo
from use_case_contracts.errors import (
    AuthenticationError,
    ExternalServiceError,
    ValidationError,
    NotFoundError,
)
from use_case_contracts.messages import (
    GetJobSubJobs,
    GetSubJobDetails,
    GetSimulatorDetails,
    GetJob,
    ListSimulators,
    OpenSimulationRunForm,
    ScheduleSimulationRun,
)


def run_simulation():
    usecases = current_app.extensions.get("usecases")
    if usecases is not None:
        usecases.handle(OpenSimulationRunForm())
    models = _load_models()
    return render_template(
        "run_simulation.html",
        models=models,
        active_page="run_simulation",
        batch=None,
    )


def get_model_input_params(model_id: str):
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return jsonify({"params": []})
    details = usecases.handle(GetSimulatorDetails(simulator_id=model_id))
    params = _extract_input_params(details.input_params or [])
    return jsonify({"params": params})


def run_simulation_submit():
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return render_template(
            "run_simulation.html",
            models=_load_models(),
            active_page="run_simulation",
            batch=None,
            error_message="Use-case adapter is not configured.",
        )

    try:
        message = _parse_schedule_message()
        batch = usecases.handle(message)
        return redirect(url_for("onSimulationMonitor", job_id=batch.job_id))
    except (ValidationError, NotFoundError, AuthenticationError, ExternalServiceError) as exc:
        return render_template(
            "run_simulation.html",
            models=_load_models(),
            active_page="run_simulation",
            error_message=str(exc),
        )


def get_job_group_status(group_id: str):
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        return jsonify({"jobs": []})
    jobs = usecases.handle(GetJobSubJobs(job_id=group_id))
    return jsonify({"jobs": [_job_to_dict(job) for job in jobs]})


def get_simulation_group_details(group_id: str):
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        subjobs: List[SubJobInfo] = []
        created_at = None
    else:
        subjobs = usecases.handle(GetJobSubJobs(job_id=group_id))
        job = usecases.handle(GetJob(job_id=group_id))
        created_at = job.created_at
    return render_template(
        "simulation_group.html",
        active_page="sim_monitor",
        group_id=group_id,
        jobs=subjobs,
        created_at=created_at,
    )


def get_simulation_sub_job_details(job_id: str, sub_job_id: str):
    context = {
        "active_page": "sim_monitor",
        "job_id": job_id,
        "sub_job_id": sub_job_id,
        "status": "",
        "standard_output": "",
        "standard_error": "",
        "error_message": None,
        "back_url": url_for("onSimulationGroupDetails", group_id=job_id),
    }
    usecases = current_app.extensions.get("usecases")
    if usecases is None:
        context["error_message"] = "Use-case adapter is not configured."
        return render_template("simulation_sub_job_detail.html", **context), 503

    try:
        details = usecases.handle(GetSubJobDetails(job_id=job_id, sub_job_id=sub_job_id))
        context.update(
            {
                "status": details.status,
                "standard_output": details.standard_output,
                "standard_error": details.standard_error,
            }
        )
        return render_template("simulation_sub_job_detail.html", **context)
    except NotFoundError as exc:
        context["error_message"] = str(exc)
        return render_template("simulation_sub_job_detail.html", **context), 404
    except ValidationError as exc:
        context["error_message"] = str(exc)
        return render_template("simulation_sub_job_detail.html", **context), 400
    except AuthenticationError as exc:
        context["error_message"] = str(exc)
        return render_template("simulation_sub_job_detail.html", **context), 502
    except ExternalServiceError as exc:
        context["error_message"] = str(exc)
        return render_template("simulation_sub_job_detail.html", **context), 502

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


def _extract_input_params(raw: List | None) -> List[Dict[str, str]]:
    params = []
    for item in raw or []:
        if isinstance(item, dict):
            name = item.get("name")
            p_type = item.get("type")
        else:
            name = getattr(item, "name", None)
            p_type = getattr(item, "type", None)
        if name and p_type:
            params.append({"name": name, "type": p_type})
    return params


def _parse_schedule_message() -> ScheduleSimulationRun:
    form = request.form
    simulator_id = (form.get("model") or "").strip()
    repetitions = int(form.get("repetitions") or 1)

    sweep_params: Dict[str, List[str]] = {}

    for key, value in form.items():
        if not key.startswith("params["):
            continue
        if key.endswith("][list]"):
            name = key.split("[", 1)[1].split("]")[0]
            values = _split_list(value)
            if values:
                sweep_params[name] = values
        if key.endswith("][min]"):
            name = key.split("[", 1)[1].split("]")[0]
            min_val = value
            max_val = form.get(f"params[{name}][max]", "")
            step_val = form.get(f"params[{name}][step]", "")
            if min_val.strip() and max_val.strip() and step_val.strip():
                sweep_params[name] = _range_values(min_val, max_val, step_val)

    return ScheduleSimulationRun(
        simulator_id=simulator_id,
        repetitions=repetitions,
        fixed_params={},
        sweep_params=sweep_params,
    )


def _split_list(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _range_values(min_val: str, max_val: str, step_val: str) -> List[str]:
    try:
        start = Decimal(min_val)
        stop = Decimal(max_val)
        step = Decimal(step_val)
    except InvalidOperation:
        return []
    if step == 0:
        return []
    values = []
    current = start
    while current <= stop:
        values.append(str(current))
        current += step
    return values


def _job_to_dict(job) -> Dict[str, str]:
    return {
        "job_id": job.job_id,
        "sub_job_id": job.sub_job_id,
        "status": job.status,
    }
