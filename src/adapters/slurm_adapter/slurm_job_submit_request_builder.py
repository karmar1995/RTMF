from __future__ import annotations

from dataclasses import dataclass
from shlex import quote
from typing import Any

from adapters.slurm_adapter.slurm_rest_client import SlurmRestClient


@dataclass(frozen=True)
class SlurmJobSubmitDefaults:
    working_directory: str = "/tmp/workspace"
    partition: str | None = None
    standard_output: str | None = None
    standard_error: str | None = None


class SlurmJobSubmitRequestBuilder:
    def __init__(self, rest_client: SlurmRestClient, *, defaults: SlurmJobSubmitDefaults) -> None:
        self._rest_client = rest_client
        self._defaults = defaults

    def build_array_script(
        self,
        *,
        simulator_uri: str,
        matrix_uri: str,
        combinations: int,
        repetitions: int,
        base_workdir: str,
        simulator_path: str,
    ) -> str:
        return (
            "#!/bin/bash\n"
            'JOB_ID="${SLURM_ARRAY_JOB_ID:-${SLURM_JOB_ID:-0}}"\n'
            'TASK_ID="${SLURM_ARRAY_TASK_ID:-0}"\n'
            'SUB_JOB_ID="$TASK_ID"\n'
            f"COMBINATIONS={combinations}\n"
            f"REPETITIONS={repetitions}\n"
            "\n"
            "ROW_INDEX=$(( TASK_ID % COMBINATIONS ))\n"
            "REPETITION=$(( TASK_ID / COMBINATIONS + 1 ))\n"
            'export RTMF_REPETITION="$REPETITION"\n'
            "\n"
            f'WORKDIR={quote(base_workdir)}/"$JOB_ID"/"$SUB_JOB_ID"\n'
            'mkdir -p -- "$WORKDIR"\n'
            "\n"
            "apptainer run --no-home --no-https -- "
            f"{quote(simulator_uri)} "
            f"--matrix-uri {quote(matrix_uri)} "
            "--row-index \"$ROW_INDEX\" "
            "--job-id \"$JOB_ID\" "
            "--sub-job-id \"$SUB_JOB_ID\" "
            f"--simulator-path {quote(simulator_path)} "
            "--workdir \"$WORKDIR\"\n"
        )

    def build_payload(
        self,
        *,
        name: str,
        tasks: int,
        script: str,
        environment: list[str],
        partition: str | None = None,
        standard_output: str | None = None,
        standard_error: str | None = None,
        current_working_directory: str | None = None,
        extra_job_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_payload: dict[str, Any] = {
            "name": name,
            "partition": partition if partition is not None else self._defaults.partition,
            "tasks": tasks,
            "current_working_directory": (
                current_working_directory
                if current_working_directory is not None
                else self._defaults.working_directory
            ),
            "environment": environment,
            "script": script,
            "standard_output": (
                standard_output if standard_output is not None else self._defaults.standard_output
            ),
            "standard_error": (
                standard_error if standard_error is not None else self._defaults.standard_error
            ),
        }
        if extra_job_fields:
            job_payload.update(extra_job_fields)
        job_payload = {k: v for k, v in job_payload.items() if v is not None}
        return {"job": job_payload}

    def submit(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        return self._rest_client.submit_job(payload)

    def extract_job_id(self, response: dict[str, Any]) -> str:
        candidates = [
            response.get("job_id"),
            response.get("jobid"),
            response.get("job", {}).get("job_id") if isinstance(response.get("job"), dict) else None,
            response.get("job", {}).get("jobid") if isinstance(response.get("job"), dict) else None,
            response.get("submission", {}).get("job_id")
            if isinstance(response.get("submission"), dict)
            else None,
        ]
        for candidate in candidates:
            if candidate is not None:
                return str(candidate)
        raise RuntimeError(f"Slurm submit response missing job id: {response!r}")
