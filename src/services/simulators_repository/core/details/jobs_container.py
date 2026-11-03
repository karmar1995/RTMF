import threading

from services.simulators_repository.core.details.simulator_build_job import SimulatorBuildJob


class JobsContainer:
    """
    Thread-safe container for active and finished build jobs.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_jobs = {}
        self._finished_jobs = {}

    def add_active_job(self, build_id: str, job: SimulatorBuildJob) -> None:
        if not isinstance(build_id, str) or not build_id.strip():
            raise ValueError("build_id must be a non-empty string")
        if job is None:
            raise ValueError("job is required")
        with self._lock:
            self._active_jobs[build_id] = job
            self._finished_jobs.pop(build_id, None)

    def mark_finished(self, build_id: str) -> SimulatorBuildJob | None:
        if not isinstance(build_id, str) or not build_id.strip():
            raise ValueError("build_id must be a non-empty string")
        with self._lock:
            job = self._active_jobs.pop(build_id, None)
            if job is None:
                return None
            job.on_job_finished()
            self._finished_jobs[build_id] = job
            return job

    def get_active_job(self, build_id: str) -> SimulatorBuildJob | None:
        if not isinstance(build_id, str) or not build_id.strip():
            raise ValueError("build_id must be a non-empty string")
        with self._lock:
            return self._active_jobs.get(build_id)

    def get_finished_job(self, build_id: str) -> SimulatorBuildJob | None:
        if not isinstance(build_id, str) or not build_id.strip():
            raise ValueError("build_id must be a non-empty string")
        with self._lock:
            return self._finished_jobs.get(build_id)

    def get_active_job_ids(self) -> list[str]:
        with self._lock:
            return list(self._active_jobs.keys())

    def get_finished_job_ids(self) -> list[str]:
        with self._lock:
            return list(self._finished_jobs.keys())

    def remove_finished_job(self, build_id: str) -> SimulatorBuildJob | None:
        if not isinstance(build_id, str) or not build_id.strip():
            raise ValueError("build_id must be a non-empty string")
        with self._lock:
            return self._finished_jobs.pop(build_id, None)
