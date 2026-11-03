import threading
import time
from functools import partial

from services.jobs_scheduler.core.ports import JobsSchedulerPort
from use_case_contracts.ports import JobsRepositoryWriterPort


def refresh_loop(
    refresher,
    stop_event: threading.Event,
    interval_seconds: float = 2.0,
) -> None:
    while not stop_event.is_set():
        try:
            refresher()
        except Exception:
            pass

        stop_event.wait(interval_seconds)


def start_refresh_loop(
    jobs_scheduler: JobsSchedulerPort,
    jobs_repo: JobsRepositoryWriterPort,
    interval_seconds: float = 2.0,
) -> tuple[threading.Thread, threading.Event]:
    refresher = partial(
        refresh_job_status,
        jobs_scheduler=jobs_scheduler,
        jobs_repo=jobs_repo,
    )

    stop_event = threading.Event()
    thread = threading.Thread(
        target=refresh_loop,
        kwargs={
            "refresher": refresher,
            "stop_event": stop_event,
            "interval_seconds": interval_seconds,
        },
        daemon=True,
        name="job-status-refresh-loop",
    )
    thread.start()
    return thread, stop_event


def refresh_job_status(
    jobs_scheduler: JobsSchedulerPort,
    jobs_repo: JobsRepositoryWriterPort,
) -> None:
    ids_to_statuses: dict[str, str] = {}

    started_jobs = jobs_repo.get_started_jobs()
    for started_job_id in started_jobs:
        try:
            job = jobs_scheduler.get_job(started_job_id)
            if job is None:
                continue

            status = job.status
            if status in {"successful", "failed"}:
                ids_to_statuses[started_job_id] = status
        except Exception as e:
            pass

    jobs_repo.update_jobs_statuses(ids_to_statuses)
