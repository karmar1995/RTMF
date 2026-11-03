from __future__ import annotations

from typing import Protocol


class ResultsRepositoryPort(Protocol):
    def assemble_job_root_url(self, job_id):
        ...

    def upload_result_zip(self, job_id: str, sub_job_id: str, zip_bytes: bytes) -> str:
        ...

    # deprecated
    def upload_params(self, job_id: str, sub_job_id: str, params: list[str]) -> None:
        ...

    def upload_csv_zip(self, job_id: str, sub_job_id: str, filename: str, data: bytes) -> None:
        ...


class JobsRepositoryPort(Protocol):
    def store_job_root_url(self, job_id: str, url: str):
        ...

    def store_result_url(self, job_id: str, sub_job_id: str, url: str) -> None:
        ...


class SimulatorPort(Protocol):
    def run(self, simulator_path: str, matrix_path: str, row_number: str, workdir: str) -> None:
        ...


class MatrixSourcePort(Protocol):
    def download_matrix(self, uri: str) -> bytes:
        """Download matrix bytes from a URI such as s3://bucket/key."""
        ...
