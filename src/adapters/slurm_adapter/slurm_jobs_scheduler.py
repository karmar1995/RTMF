from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.jobs_scheduler.core.dtos import JobInfo, JobSummary, ScheduledBatchInfo, SubJobInfo
from services.jobs_scheduler.core.errors import (
    ExternalServiceError,
    SlurmAuthenticationError,
    SlurmProtocolError,
    SlurmUnavailableError,
)
from adapters.slurm_adapter.slurm_job_submit_request_builder import SlurmJobSubmitRequestBuilder
from adapters.slurm_adapter.slurm_request_info import SlurmRequestInfo
from adapters.slurm_adapter.slurm_rest_client import (
    SlurmRestClient,
    SlurmRestConnectionError,
    SlurmRestError,
    SlurmRestProtocolError,
)
from services.jobs_scheduler.core.ports import JobsSchedulerPort


# Response shapes handled:
# {"jobs": [{...}]}, {"job": {...}}, {"job": [{...}]}, {"data": [{...}]}, [{...}]
def _extract_first_job(response: Any) -> dict | None:
    if response is None:
        return None
    if isinstance(response, list):
        for item in response:
            if isinstance(item, dict):
                return item
        return None
    if isinstance(response, dict):
        jobs = response.get("jobs")
        if isinstance(jobs, list) and jobs:
            return jobs[0] if isinstance(jobs[0], dict) else None
        job = response.get("job")
        if isinstance(job, dict):
            return job
        if isinstance(job, list) and job:
            return job[0] if isinstance(job[0], dict) else None
        data = response.get("data")
        if isinstance(data, list) and data:
            return data[0] if isinstance(data[0], dict) else None
    return None


def _extract_jobs(response: object) -> list[dict]:
    if response is None:
        return []
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]
    if isinstance(response, dict):
        jobs = response.get("jobs")
        if isinstance(jobs, list):
            return [item for item in jobs if isinstance(item, dict)]
        job = response.get("job")
        if isinstance(job, list):
            return [item for item in job if isinstance(item, dict)]
        if isinstance(job, dict):
            return [job]
        data = response.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def _has_jobs_collection(response: object) -> bool:
    if isinstance(response, list):
        return True
    if isinstance(response, dict):
        return any(key in response for key in ("jobs", "job", "data"))
    return False


# Example: array_job_id=465, array_task_id=28, job_id=494 -> root id "465".
def _slurm_number(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
        return None
    if isinstance(value, dict):
        if value.get("set") is False:
            return None
        number = value.get("number")
        if isinstance(number, (int, float)):
            return int(number)
        if isinstance(number, str) and number.strip().isdigit():
            return int(number.strip())
    return None


def _extract_root_job_id(job: dict) -> str | None:
    array_job_id = _slurm_number(job.get("array_job_id"))
    if array_job_id:
        return str(array_job_id)

    for key in ("job_id", "jobid", "id"):
        value = job.get(key)
        number = _slurm_number(value)
        if number:
            return str(number)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = job.get("job")
    if isinstance(nested, dict):
        for key in ("job_id", "jobid", "id"):
            value = nested.get(key)
            number = _slurm_number(value)
            if number:
                return str(number)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _map_slurm_state_to_status(state: object | None) -> str:
    if isinstance(state, (list, tuple)):
        state = state[0] if state else None
    text = str(state or "").strip().upper()
    if "+" in text:
        text = text.split("+", 1)[0]
    failed_states = {
        "FAILED",
        "CANCELLED",
        "TIMEOUT",
        "NODE_FAIL",
        "PREEMPTED",
        "OUT_OF_MEMORY",
        "OOM",
        "BOOT_FAIL",
    }
    waiting_states = {
        "PENDING",
        "CONFIGURING",
        "REQUEUED",
        "SPECIAL_EXIT",
    }
    running_states = {
        "RUNNING",
        "COMPLETING",
        "SUSPENDED",
        "STOPPED",
    }
    if text == "COMPLETED":
        return "successful"
    if text in failed_states:
        return "failed"
    if text in waiting_states:
        return "waiting"
    if text in running_states:
        return "running"
    return "waiting"


def _format_slurm_time(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("number") or value.get("value")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    if isinstance(value, str):
        return value
    return None


def _rest_context(exc: object) -> dict[str, object]:
    context: dict[str, object] = {
        "adapter": "SlurmJobsScheduler",
    }
    for name in ("operation", "base_url", "timeout_seconds", "status_code", "body_snippet"):
        value = getattr(exc, name, None)
        if value is not None:
            context[name] = value
    return context


def _map_rest_error(
    exc: SlurmRestError | SlurmRestConnectionError | SlurmRestProtocolError,
) -> Exception:
    context = _rest_context(exc)
    if isinstance(exc, SlurmRestProtocolError):
        return SlurmProtocolError(
            "Slurm scheduler returned malformed data.",
            diagnostic_context=context,
        )
    if isinstance(exc, SlurmRestConnectionError):
        return SlurmUnavailableError(
            "Slurm scheduler is temporarily unavailable.",
            diagnostic_context=context,
        )
    if exc.status_code in {401, 403}:
        return SlurmAuthenticationError(
            "Slurm scheduler authentication failed.",
            diagnostic_context=context,
        )
    if exc.status_code >= 500:
        return SlurmUnavailableError(
            "Slurm scheduler is temporarily unavailable.",
            diagnostic_context=context,
        )
    return ExternalServiceError(str(exc))


class SlurmJobsScheduler(JobsSchedulerPort):
    def __init__(
        self,
        request_info: SlurmRequestInfo,
        builder: SlurmJobSubmitRequestBuilder,
        rest_client: SlurmRestClient,
        *,
        working_directory: str = "/tmp/workspace",
        job_name_prefix: str = "simu",
        partition: str | None = None,
        standard_output: str | None = None,
        standard_error: str | None = None,
    ) -> None:
        self._common_request_info = request_info
        self._builder = builder
        self._rest_client = rest_client
        self.__workdir = working_directory
        self.__job_name_prefix = job_name_prefix
        self.__partition = partition
        self.__standard_output = standard_output
        self.__standard_error = standard_error
        self.__simulator_path = "/opt/simulator/start_sim.sh"

    def submit_simulation_batch(
        self,
        simulator_uri: str,
        matrix_uri: str,
        combinations: int,
    ) -> ScheduledBatchInfo:
        combinations = max(combinations, 1)
        repetitions = 1
        subjobs = combinations * repetitions
        environment = self._common_request_info.to_env_list()
        script = self._builder.build_array_script(
            simulator_uri=simulator_uri,
            matrix_uri=matrix_uri,
            combinations=combinations,
            repetitions=repetitions,
            base_workdir=self.__workdir,
            simulator_path=self.__simulator_path,
        )
        extra_job_fields: dict[str, str] = {}
        if subjobs > 1:
            extra_job_fields["array"] = f"0-{subjobs - 1}"
        payload = self._builder.build_payload(
            name=f"{self.__job_name_prefix}-array",
            tasks=1,
            script=script,
            environment=environment,
            partition=self.__partition,
            standard_output=self.__standard_output,
            standard_error=self.__standard_error,
            current_working_directory=self.__workdir,
            extra_job_fields=extra_job_fields or None,
        )
        try:
            response = self._builder.submit(payload=payload)
            job_id = self._builder.extract_job_id(response)
        except (SlurmRestError, SlurmRestConnectionError, SlurmRestProtocolError) as exc:
            raise _map_rest_error(exc) from exc
        except RuntimeError as exc:
            raise ExternalServiceError(str(exc)) from exc
        return ScheduledBatchInfo(
            job_id=job_id,
            sub_job_ids=[str(i) for i in range(subjobs)],
        )

    def get_job(self, job_id: str) -> JobInfo | None:
        try:
            response = self._rest_client.get_slurm_job(job_id)
            job = _extract_first_job(response)
            if job is not None:
                # job_state may be a list in Slurm REST responses; unknown states default to waiting.
                state = job.get("job_state", job.get("state"))
                return JobInfo(
                    job_id=str(job_id),
                    status=_map_slurm_state_to_status(state),
                )
        except SlurmRestError as exc:
            if exc.status_code == 404:
                return None
            raise _map_rest_error(exc) from exc
        except SlurmRestConnectionError as exc:
            raise _map_rest_error(exc) from exc
        except SlurmRestProtocolError as exc:
            raise _map_rest_error(exc) from exc
        return None

    def list_jobs(self) -> list[JobSummary]:
        ids: set[str] = set()
        summaries: list[JobSummary] = []

        try:
            response = self._rest_client.list_slurm_jobs()
            if not _has_jobs_collection(response):
                raise SlurmProtocolError(
                    "Slurm scheduler returned an invalid jobs list payload.",
                    diagnostic_context={
                        "operation": "list_jobs",
                        "adapter": "SlurmJobsScheduler",
                    },
                )
            for job in _extract_jobs(response):
                job_id = _extract_root_job_id(job)
                if job_id and job_id not in ids:
                    ids.add(job_id)
                    summaries.append(
                        JobSummary(
                            job_id=job_id,
                            status=_map_slurm_state_to_status(
                                job.get("job_state", job.get("state"))
                            ),
                        )
                    )
        except SlurmRestError as exc:
            if exc.status_code != 404:
                raise _map_rest_error(exc) from exc
        except SlurmRestConnectionError as exc:
            raise _map_rest_error(exc) from exc
        except SlurmRestProtocolError as exc:
            raise _map_rest_error(exc) from exc

        def _sort_key(item: JobSummary) -> tuple[int, str]:
            try:
                return (0, f"{int(item.job_id):020d}")
            except (TypeError, ValueError):
                return (1, item.job_id)

        return sorted(summaries, key=_sort_key)

    def get_job_sub_jobs(self, job_id: str) -> list[SubJobInfo]:
        try:
            response = self._rest_client.get_slurm_job(job_id)
        except SlurmRestError as exc:
            if exc.status_code == 404:
                return []
            raise _map_rest_error(exc) from exc
        except SlurmRestConnectionError as exc:
            raise _map_rest_error(exc) from exc
        except SlurmRestProtocolError as exc:
            raise _map_rest_error(exc) from exc

        master_id = str(job_id)
        jobs = [job for job in _extract_jobs(response) if _extract_root_job_id(job) == master_id]
        if not jobs:
            return []

        by_task: dict[str, SubJobInfo] = {}
        for job in jobs:
            task_id = _slurm_number(job.get("array_task_id"))
            if task_id is None:
                continue
            state = job.get("job_state", job.get("state"))
            status = _map_slurm_state_to_status(state)
            sub_job_id = str(task_id)
            by_task[sub_job_id] = SubJobInfo(
                sub_job_id=sub_job_id,
                job_id=master_id,
                status=status,
            )

        def _sort_key(item: SubJobInfo) -> tuple[int, str]:
            try:
                return (0, f"{int(item.sub_job_id):020d}")
            except (TypeError, ValueError):
                return (1, item.sub_job_id)

        return sorted(by_task.values(), key=_sort_key)

    def get_sub_job_stderr(self, job_id: str, sub_job_id: str) -> str:
        path = self._resolve_stdio_path(
            self.__standard_error or self.__standard_output,
            job_id,
            sub_job_id,
            default_filename="simulation.err",
        )
        return self._read_text_file(path)

    def get_sub_job_stdout(self, job_id: str, sub_job_id: str) -> str:
        path = self._resolve_stdio_path(
            self.__standard_output,
            job_id,
            sub_job_id,
            default_filename="simulation.out",
        )
        return self._read_text_file(path)

    def _resolve_stdio_path(
            self,
            template: str | None,
            job_id: str,
            sub_job_id: str,
            *,
            default_filename: str,
    ) -> str:
        if template is None or not template.strip():
            template = f"{self.__workdir}/{job_id}/{sub_job_id}/{default_filename}"

        return (
            template
            .replace("%A", str(job_id))
            .replace("%a", str(sub_job_id))
            .replace("%j", str(job_id))
        )

    def _read_text_file(self, path: str) -> str:
        normalized_path = path.strip()
        if not normalized_path:
            raise RuntimeError("File path is empty")

        try:
            with open(normalized_path, "r", encoding="utf-8", errors="replace") as file:
                return file.read()
        except FileNotFoundError as exc:
            return f"File not found: {normalized_path}"
        except OSError as exc:
            return f"Failed to read file '{normalized_path}': {exc}"
