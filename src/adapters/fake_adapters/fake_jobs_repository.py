from use_case_contracts.ports import JobsRepositoryReaderPort
from use_case_contracts.dtos import *


class FakeJobsRepository(JobsRepositoryReaderPort):
    def __init__(self) -> None:
        self._store: dict[str, list[ResultRef]] = {}

    def list_jobs(self) -> list[str]:
        raise NotImplementedError("Implement me!")

    def job_details(self, job_id) -> JobResultRef:
        raise NotImplementedError("Implement me!")

    def list_results(self, job_id: str) -> list[ResultRef]:
        stored = self._store.get(job_id)
        if stored is not None:
            return stored
        return [
            ResultRef(
                sub_job_id="sub-0",
                url=f"/results/{job_id}/sub-0.zip",
            ),
        ]

    def store_result(self, job_id: str, ref: ResultRef) -> None:
        if job_id not in self._store:
            self._store[job_id] = []
        self._store[job_id].append(ref)
