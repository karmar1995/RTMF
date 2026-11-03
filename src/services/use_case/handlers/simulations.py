from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Tuple

from use_case_contracts.ports import SimulatorRepository, JobsSchedulerPort, JobsRepositoryReaderPort, MatrixGenerationPort, EvaluationMonitorStorePort

from use_case_contracts.dtos import (
    EvaluationMonitorEntry,
    JobInfo,
    JobResultRef,
    JobSummary,
    MonitorEntries,
    ScheduledBatchInfo,
    SubJobDetailsDto,
    SubJobInfo,
    JobVisualizationPage,
    MatrixParameterDefinition
)
import logging
import uuid
from datetime import datetime

from use_case_contracts.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from use_case_contracts.messages import (
    GetJob,
    GetJobSubJobs,
    GetSubJobDetails,
    ListJobs,
    ListMonitorEntries,
    ListVisualizationJobs,
    ScheduleSimulationRun,
)


def handle_schedule_simulation_run(
    message: ScheduleSimulationRun,
    repo: SimulatorRepository,
    scheduler: JobsSchedulerPort,
    matrix_generator: MatrixGenerationPort,
) -> ScheduledBatchInfo:
    record = repo.get(message.simulator_id)
    if record is None:
        raise NotFoundError(f"Simulator '{message.simulator_id}' not found")
    if message.repetitions < 1:
        raise ValidationError("Repetitions must be >= 1")

    input_params = _extract_input_params(record.input_params)

    fixed_params = message.fixed_params or {}
    sweep_params = message.sweep_params or {}

    overlap = set(fixed_params.keys()) & set(sweep_params.keys())
    if overlap:
        raise ValidationError(f"Params cannot be both fixed and sweep: {', '.join(sorted(overlap))}")

    param_names = {name for name, _ in input_params}
    unknown_params = (set(fixed_params.keys()) | set(sweep_params.keys())) - param_names
    if unknown_params:
        raise ValidationError(f"Unknown parameter: {', '.join(sorted(unknown_params))}")

    missing = [
        name for name, _ in input_params
        if name not in fixed_params and name not in sweep_params
    ]
    if missing:
        raise ValidationError(f"Missing values for params: {', '.join(missing)}")

    combinations = 1
    for name, values in sweep_params.items():
        if not values:
            raise ValidationError(f"Sweep values for '{name}' are empty")
        combinations *= len(values)

    try:
        generated_matrix = matrix_generator.generate_linear_combinations(
            matrix_id=uuid.uuid4().hex[:8],
            repetitions=message.repetitions,
            parameter_definitions=[
                MatrixParameterDefinition(name=name, type=p_type)
                for name, p_type in input_params
            ],
            fixed_params=fixed_params,
            sweep_params=sweep_params,
        )

        simulator_uri = f"docker://{record.bin_url}"

        return scheduler.submit_simulation_batch(
            simulator_uri=simulator_uri,
            matrix_uri=generated_matrix.matrix_url,
            combinations=combinations,
            simulator_id=message.simulator_id
        )
    except Exception as exc:  # noqa: BLE001
        _raise_if_auth_failure(
            exc,
            "Jobs scheduler authentication failed.",
        )
        raise


def handle_get_job(message: GetJob, scheduler: JobsSchedulerPort) -> JobInfo | None:
    try:
        return scheduler.get_job(message.job_id)
    except Exception as exc:  # noqa: BLE001
        _raise_if_auth_failure(exc, "Could not query jobs scheduler. Authentication failed.")
        _raise_external_service_error(exc, "Could not query jobs scheduler.")
        raise


def handle_get_job_sub_jobs(message: GetJobSubJobs, scheduler: JobsSchedulerPort) -> list[SubJobInfo]:
    try:
        return scheduler.get_job_sub_jobs(message.job_id)
    except Exception as exc:  # noqa: BLE001
        _raise_if_auth_failure(exc, "Could not query jobs scheduler. Authentication failed.")
        _raise_external_service_error(exc, "Could not query jobs scheduler.")
        raise


def handle_get_sub_job_details(
    message: GetSubJobDetails,
    scheduler: JobsSchedulerPort,
) -> SubJobDetailsDto:
    job_id = (message.job_id or "").strip()
    sub_job_id = (message.sub_job_id or "").strip()
    if not job_id:
        raise ValidationError("Job ID must not be empty")
    if not sub_job_id:
        raise ValidationError("Sub-job ID must not be empty")

    try:
        sub_jobs = scheduler.get_job_sub_jobs(job_id)
        sub_job = next((item for item in sub_jobs if item.sub_job_id == sub_job_id), None)
        if sub_job is None:
            raise NotFoundError(f"Sub-job '{sub_job_id}' for job '{job_id}' not found")

        return SubJobDetailsDto(
            job_id=job_id,
            sub_job_id=sub_job_id,
            status=sub_job.status or "",
            standard_output=_load_sub_job_log(
                scheduler.get_sub_job_stdout,
                job_id,
                sub_job_id,
            ),
            standard_error=_load_sub_job_log(
                scheduler.get_sub_job_stderr,
                job_id,
                sub_job_id,
            ),
        )
    except (ValidationError, NotFoundError):
        raise
    except Exception as exc:  # noqa: BLE001
        _raise_if_auth_failure(exc, "Could not query jobs scheduler. Authentication failed.")
        _raise_external_service_error(exc, "Could not query jobs scheduler.")
        raise


def handle_list_jobs(_: ListJobs, scheduler: JobsSchedulerPort) -> list[JobSummary]:
    try:
        return scheduler.list_jobs()
    except Exception as exc:  # noqa: BLE001
        _raise_if_auth_failure(exc, "Could not query jobs scheduler. Authentication failed.")
        _raise_external_service_error(exc, "Could not query jobs scheduler.")
        raise


# Evaluation status -> monitor column. Anything still in flight counts as
# running so the card keeps auto-refreshing with SSBO progress.
_MONITOR_WAITING_STATES = frozenset({"queued"})
_MONITOR_RUNNING_STATES = frozenset(
    {"running", "simulating", "sensitivity_analysis", "optimizing"}
)
_MONITOR_TERMINAL_STATES = frozenset({"success", "failed"})


def _evaluation_monitor_entry(summary: dict) -> EvaluationMonitorEntry:
    status = str(summary.get("status") or "queued").lower()
    if status in _MONITOR_WAITING_STATES:
        state = "waiting"
    elif status in _MONITOR_TERMINAL_STATES:
        state = "finished"
    else:
        # Unknown/future statuses stay visible as running rather than being
        # hidden from the operator.
        state = "running"

    success: bool | None = None
    if state == "finished":
        success = status == "success"

    progress: int | None = None
    if state == "running":
        iteration = _as_int(summary.get("iteration"))
        kmax = _as_int(summary.get("kmax"))
        if kmax > 0:
            progress = max(0, min(100, round(iteration / kmax * 100)))

    created_at = summary.get("created_at")
    if isinstance(created_at, datetime):
        created_at = created_at.timestamp()

    return EvaluationMonitorEntry(
        evaluation_id=str(summary.get("evaluation_id") or ""),
        model_name=str(summary.get("model_name") or ""),
        state=state,
        status=status,
        success=success,
        progress=progress,
        created_at=float(created_at) if created_at is not None else None,
    )


def _evaluation_is_live(
    summary: dict,
    linked_job_ids: set[str],
    live_job_ids: set[str],
) -> bool:
    """Whether an evaluation still belongs on the live monitor.

    Non-terminal evaluations are always live. A finished evaluation is kept
    only while Slurm still tracks one of its jobs, so it ages out of the
    monitor on the same schedule as the simulation jobs it spawned.
    """

    status = str(summary.get("status") or "queued").lower()
    if status not in _MONITOR_TERMINAL_STATES:
        return True
    return bool(linked_job_ids & live_job_ids)


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _raise_store_failure(exc: Exception, message: str) -> None:
    """A store failure is an external service failure for the monitor.

    The evaluations adapter wraps database errors in RuntimeError, so without
    this the front would render a 500 instead of flashing a warning.
    """
    _raise_if_auth_failure(exc, message)
    logging.getLogger(__name__).warning("Evaluations store error: %s", exc)
    raise ExternalServiceError(message) from None


def handle_list_monitor_entries(
    _: ListMonitorEntries,
    scheduler: JobsSchedulerPort,
    evaluations_store: EvaluationMonitorStorePort,
) -> MonitorEntries:
    """List what the monitor should show: simulation groups plus evaluations.

    An evaluation submits one Slurm job per SSBO point, so those individual
    jobs are removed from the simulation list and the evaluation appears once,
    as a synthetic parent. Evaluations are trimmed to the same live window as
    the scheduler: a finished evaluation disappears once Slurm stops tracking
    its jobs, so stale evaluations do not pile up on the monitor.
    """

    try:
        links = evaluations_store.list_evaluation_job_links()
    except Exception as exc:  # noqa: BLE001
        # Without the link table we cannot tell evaluation jobs apart, and
        # showing them individually would flood the monitor. Fail loudly
        # instead of guessing.
        _raise_store_failure(exc, "Could not read evaluation job links.")

    try:
        jobs = scheduler.list_jobs()
    except Exception as exc:  # noqa: BLE001
        _raise_if_auth_failure(exc, "Could not query jobs scheduler. Authentication failed.")
        _raise_external_service_error(exc, "Could not query jobs scheduler.")
        raise

    live_job_ids = {str(job.job_id) for job in jobs}
    owned_job_ids = set().union(*links.values()) if links else set()
    group_ids = [job.job_id for job in jobs if str(job.job_id) not in owned_job_ids]

    try:
        summaries = evaluations_store.list_summaries()
    except Exception as exc:  # noqa: BLE001
        _raise_store_failure(exc, "Could not read evaluation summaries.")

    live_summaries = [
        summary
        for summary in summaries
        if _evaluation_is_live(
            summary,
            links.get(str(summary.get("evaluation_id") or ""), set()),
            live_job_ids,
        )
    ]

    return MonitorEntries(
        simulation_group_ids=group_ids,
        evaluations=[_evaluation_monitor_entry(item) for item in live_summaries],
    )


def handle_list_visualization_jobs(message: ListVisualizationJobs, jobsRepo: JobsRepositoryReaderPort, simulatorsRepo: SimulatorRepository) -> JobVisualizationPage:
    try:
        return jobsRepo.list_jobs_for_visualization(page=message.page, per_page=message.per_page)
    except Exception as exc:
        raise


def _load_sub_job_log(loader, job_id: str, sub_job_id: str) -> str:
    try:
        return loader(job_id, sub_job_id) or ""
    except NotFoundError:
        return ""


def _raise_if_auth_failure(exc: Exception, message: str) -> None:
    name = exc.__class__.__name__
    module = getattr(exc.__class__, "__module__", "")
    text = str(exc)
    if (
        name == "SlurmAuthError"
        or ("Auth" in name and ("slurm_adapter" in module or "jobs_scheduler_rest_adapter" in module))
        or "status=401" in text
    ):
        logging.getLogger(__name__).warning("Jobs scheduler auth failure: %s", text)
        raise AuthenticationError(message) from None


def _raise_external_service_error(exc: Exception, message: str) -> None:
    module = getattr(exc.__class__, "__module__", "")
    name = exc.__class__.__name__
    if "slurm_adapter" in module or "jobs_scheduler_rest_adapter" in module or name.startswith("Slurm"):
        logging.getLogger(__name__).warning("Jobs scheduler service error: %s", exc)
        raise ExternalServiceError(message) from None


def _extract_input_params(raw: List | None) -> List[Tuple[str, str]]:
    params: List[Tuple[str, str]] = []
    for item in raw or []:
        if isinstance(item, dict):
            name = item.get("name")
            p_type = item.get("type")
        else:
            name = getattr(item, "name", None)
            p_type = getattr(item, "type", None)
        if name and p_type:
            params.append((str(name), _param_type_text(p_type)))
    if not params:
        raise ValidationError("Simulator has no input parameters")
    return params


def _build_simulator_payload(record) -> Dict[str, object]:
    return {
        "model_name": record.model_name,
        "version": record.version,
        "build_spec": record.build_spec,
        "input_params": record.input_params,
        "output_params": record.output_params,
    }


def _param_type_text(value: object) -> str:
    if hasattr(value, "value"):
        try:
            return str(value.value)
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value)


def _serialize_value(param_types: Dict[str, str], name: str, value: str) -> str:
    if name not in param_types:
        raise ValidationError(f"Unknown parameter: {name}")
    p_type = param_types[name].lower()
    if p_type in ("str", "string"):
        text = str(value).strip()
        if not text:
            raise ValidationError(f"Empty value for '{name}'")
        if " " in text:
            raise ValidationError(f"String values cannot contain spaces: {name}")
        return text
    if p_type == "bool":
        text = str(value).strip().lower()
        if text in ("true", "1", "yes"):
            return "true"
        if text in ("false", "0", "no"):
            return "false"
        raise ValidationError(f"Invalid bool for '{name}': {value}")
    if p_type == "int":
        try:
            return str(int(str(value).strip()))
        except ValueError as exc:
            raise ValidationError(f"Invalid int for '{name}': {value}") from exc
    if p_type == "float":
        return _format_decimal(value, name)
    raise ValidationError(f"Unsupported parameter type '{p_type}' for '{name}'")


def _format_decimal(value: str, name: str) -> str:
    text = str(value).strip()
    try:
        dec = Decimal(text)
    except InvalidOperation as exc:
        raise ValidationError(f"Invalid float for '{name}': {value}") from exc
    normalized = format(dec, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _build_matrix_text(reps, rows: Iterable[str]) -> str:
    return f"{reps}\n" + "\n".join(rows) + "\n"


def build_matrix_location(matrix_id: str) -> tuple[str, str, str]:
    bucket = "tmp"
    key = f"matrix/{matrix_id}.txt"
    uri = f"s3://{bucket}/{key}"
    return bucket, key, uri


def _dedupe_rows(rows: List[str]) -> List[str]:
    seen = set()
    unique = []
    for row in rows:
        if row in seen:
            continue
        seen.add(row)
        unique.append(row)
    return unique
