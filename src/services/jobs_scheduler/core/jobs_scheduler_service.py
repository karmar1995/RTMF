from __future__ import annotations

from typing import Protocol

from services.jobs_scheduler.core.dtos import JobInfo, JobSummary, ScheduledBatchInfo, SubJobInfo
from services.jobs_scheduler.core.errors import NotFoundError, ValidationError
from services.jobs_scheduler.core.ports import JobsSchedulerPort


class JobsSchedulerService(Protocol):
    def submit_simulation_batch(
        self,
        simulator_uri: str,
        matrix_uri: str,
        combinations: int,
        simulator_id: str
    ) -> ScheduledBatchInfo:
        ...

    def get_job(self, job_id: str) -> JobInfo | None:
        ...

    def list_jobs(self) -> list[JobSummary]:
        ...

    def get_job_sub_jobs(self, job_id: str) -> list[SubJobInfo]:
        ...

    def get_sub_job_stderr(self, job_id: str, sub_job_id: str) -> str:
        ...

    def get_sub_job_stdout(self, job_id: str, sub_job_id: str) -> str:
        ...


