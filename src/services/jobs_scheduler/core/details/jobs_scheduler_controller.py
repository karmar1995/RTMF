from __future__ import annotations


from services.jobs_scheduler.core.jobs_scheduler_service import JobsSchedulerService
from services.jobs_scheduler.core.dtos import JobInfo, JobSummary, ScheduledBatchInfo, SubJobInfo
from services.jobs_scheduler.core.errors import NotFoundError, ValidationError
from services.jobs_scheduler.core.ports import JobsSchedulerPort
from services.jobs_scheduler.core.details.jobs_status_monitor import start_refresh_loop
from use_case_contracts.ports import JobsRepositoryWriterPort


class JobsSchedulerController(JobsSchedulerService):
    def __init__(
        self,
        jobs_scheduler: JobsSchedulerPort,
        jobs_repository: JobsRepositoryWriterPort,
    ) -> None:
        self._jobs_scheduler = jobs_scheduler
        self._jobs_repository = jobs_repository
        self._refresh_thread = None
        self._refresh_stop_event = None

    def start_monitoring(self) -> None:
        if self._refresh_thread is not None and self._refresh_thread.is_alive():
            return

        self._refresh_thread, self._refresh_stop_event = start_refresh_loop(
            jobs_scheduler=self._jobs_scheduler,
            jobs_repo=self._jobs_repository,
        )

    def stop_monitoring(self) -> None:
        if self._refresh_stop_event is not None:
            self._refresh_stop_event.set()

    def submit_simulation_batch(
        self,
        simulator_uri: str,
        matrix_uri: str,
        combinations: int,
        simulator_id: str
    ) -> ScheduledBatchInfo:
        self._require_non_blank("simulator_uri", simulator_uri)
        self._require_non_blank("matrix_uri", matrix_uri)
        if combinations <= 0:
            raise ValidationError("combinations must be greater than zero.")

        if self._refresh_thread is None:
            self.start_monitoring()

        batch = self._jobs_scheduler.submit_simulation_batch(
            simulator_uri=simulator_uri,
            matrix_uri=matrix_uri,
            combinations=combinations,
        )
        self._jobs_repository.store_job(
            job_id=batch.job_id,
            simulator_id=simulator_id,
            status='started'
        )

        return batch

    def get_job(self, job_id: str) -> JobInfo | None:
        self._require_non_blank("job_id", job_id)
        return self._jobs_scheduler.get_job(job_id)

    def list_jobs(self) -> list[JobSummary]:
        return self._jobs_scheduler.list_jobs()

    def get_job_sub_jobs(self, job_id: str) -> list[SubJobInfo]:
        self._require_non_blank("job_id", job_id)
        job = self._jobs_scheduler.get_job(job_id)
        if job is None:
            raise NotFoundError(f"Job '{job_id}' was not found.")
        return self._jobs_scheduler.get_job_sub_jobs(job_id)

    def get_sub_job_stderr(self, job_id: str, sub_job_id: str) -> str:
        self._require_non_blank("job_id", job_id)
        self._require_non_blank("sub_job_id", sub_job_id)
        return self._jobs_scheduler.get_sub_job_stderr(job_id, sub_job_id)

    def get_sub_job_stdout(self, job_id: str, sub_job_id: str) -> str:
        self._require_non_blank("job_id", job_id)
        self._require_non_blank("sub_job_id", sub_job_id)
        return self._jobs_scheduler.get_sub_job_stdout(job_id, sub_job_id)

    @staticmethod
    def _require_non_blank(name: str, value: str) -> None:
        if not value.strip():
            raise ValidationError(f"{name} must not be blank.")
