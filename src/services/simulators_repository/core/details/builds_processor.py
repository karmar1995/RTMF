import threading
import time
from typing import Callable

from services.simulators_repository.core.abstract_image_build_worker import AbstractImageBuildWorker
from services.simulators_repository.core.details.build_requests_queue import BuildRequestsQueue
from services.simulators_repository.core.details.jobs_container import JobsContainer
from services.simulators_repository.core.details.simulator_build_job import SimulatorBuildJob


class BuildsProcessor:
    """
    Background processor that assigns queued requests to build workers.
    """

    def __init__(
        self,
        build_worker_factory: Callable[[], AbstractImageBuildWorker],
        requests_queue: BuildRequestsQueue,
        jobs_container: JobsContainer,
        active_workers: int = 1,
        poll_interval_s: float = 0.5,
    ) -> None:
        if build_worker_factory is None:
            raise ValueError("build_worker_factory is required")
        if requests_queue is None:
            raise ValueError("requests_queue is required")
        if jobs_container is None:
            raise ValueError("jobs_container is required")
        if not isinstance(active_workers, int) or active_workers <= 0:
            raise ValueError("active_workers must be a positive integer")
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")

        self._build_worker_factory = build_worker_factory
        self._requests_queue = requests_queue
        self._jobs_container = jobs_container
        self._poll_interval_s = poll_interval_s
        self._lock = threading.Lock()

        self._idle_workers = [self._build_worker_factory() for _ in range(active_workers)]
        self._build_id_to_worker = {}

        self._stop_event = threading.Event()
        self._thread = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop, name="builds-processor", daemon=True
            )
            self._thread.start()

    def stop(self, wait: bool = False) -> None:
        self._stop_event.set()
        if wait and self._thread is not None:
            self._thread.join()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._assign_jobs()
            self._poll_active_jobs()
            time.sleep(self._poll_interval_s)

    def _assign_jobs(self) -> None:
        while True:
            with self._lock:
                if not self._idle_workers:
                    return
                worker = self._idle_workers.pop(0)
            queued_item = self._requests_queue.dequeue()
            if queued_item is None:
                with self._lock:
                    self._idle_workers.insert(0, worker)
                return
            build_id, request = queued_item
            job = SimulatorBuildJob(
                build_worker=worker,
                request=request,
                build_id=build_id,
            )
            job.submit()
            with self._lock:
                self._build_id_to_worker[build_id] = worker
            self._jobs_container.add_active_job(build_id, job)

    def _poll_active_jobs(self) -> None:
        active_ids = self._jobs_container.get_active_job_ids()

        for build_id in active_ids:
            job = self._jobs_container.get_active_job(build_id)
            with self._lock:
                worker = self._build_id_to_worker.get(build_id)
            if job is None or worker is None:
                continue
            status = job.update_build_status()
            if status.status != "running":
                self._jobs_container.mark_finished(build_id)
                with self._lock:
                    self._build_id_to_worker.pop(build_id, None)
                    self._idle_workers.append(worker)
