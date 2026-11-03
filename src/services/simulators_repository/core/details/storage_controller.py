import threading
import time

from services.simulators_repository.core.abstract_simulators_storage import AbstractSimulatorsStorage, SimulatorEntry
from services.simulators_repository.core.details.jobs_container import JobsContainer


class StorageController:
    """
    Persists finished build jobs into simulator storage.
    """

    def __init__(
        self,
        jobs_container: JobsContainer,
        simulators_storage: AbstractSimulatorsStorage,
        poll_interval_s: float = 0.5,
    ) -> None:
        if jobs_container is None:
            raise ValueError("jobs_container is required")
        if simulators_storage is None:
            raise ValueError("simulators_storage is required")
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")

        self._jobs_container = jobs_container
        self._simulators_storage = simulators_storage
        self._poll_interval_s = poll_interval_s

        self._stored_ids = set()
        self._stop_event = threading.Event()
        self._thread = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="storage-controller", daemon=True
        )
        self._thread.start()

    def stop(self, wait: bool = False) -> None:
        self._stop_event.set()
        if wait and self._thread is not None:
            self._thread.join()

    def is_stored(self, build_id: str) -> bool:
        return build_id in self._stored_ids

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._store_finished_jobs()
            time.sleep(self._poll_interval_s)

    def _store_finished_jobs(self) -> None:
        for build_id in self._jobs_container.get_finished_job_ids():
            if build_id in self._stored_ids:
                continue
            job = self._jobs_container.get_finished_job(build_id)
            if not self._valid_job_for_storage(job):
                continue
            entry = SimulatorEntry(
                simulator_id='unused',
                model_name=job.model_name,
                version=job.version,
                image_reference_url=job.image_reference_url,
                image_digest=job.image_digest,
                image_tags=job.image_tags,
                input_params=job.input_params(),
                output_params=job.output_params(),
            )
            self._simulators_storage.insert(entry)
            self._stored_ids.add(build_id)

    def _valid_job_for_storage(self, job):
        if job is None:
            return False
        if not job.image_reference_url:
            # TODO: Log error
            return False
        if not job.image_digest:
            # TODO: Log error
            return False
        if not job.image_tags:
            # TODO: Log error
            return False
        return True
