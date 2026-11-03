import csv
import hashlib
import io
import os
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from minio import Minio

from use_case_contracts.ports import JobsSchedulerPort
from use_case_contracts.dtos import *

from adapters.fake_adapters.fake_results_repository import FakeResultsRepository
from adapters.fake_adapters.fake_jobs_repository import FakeJobsRepository


def _rosenbrock(x: np.ndarray) -> float:
    x = np.asarray(x)
    if len(x) < 2:
        return float(x[0] ** 2)
    return float(np.sum(100.0 * (x[1:] - x[:-1] ** 2) ** 2 + (1 - x[:-1]) ** 2))


class FakeJobsScheduler(JobsSchedulerPort):
    def __init__(
        self,
        results_repository: FakeResultsRepository,
        jobs_repository: FakeJobsRepository,
        minio_endpoint: str | None = None,
        minio_access_key: str | None = None,
        minio_secret_key: str | None = None,
        minio_secure: bool = False,
    ) -> None:
        self._results_repo = results_repository
        self._jobs_repo = jobs_repository
        self._minio: Minio | None = None
        endpoint = minio_endpoint or os.environ.get("RTMF_AISTOR_ENDPOINT")
        access_key = minio_access_key or os.environ.get("RTMF_AISTOR_ACCESS_KEY")
        secret_key = minio_secret_key or os.environ.get("RTMF_AISTOR_SECRET_KEY")
        if endpoint and access_key and secret_key:
            parsed = urlparse(endpoint)
            host = parsed.netloc if parsed.scheme else parsed.path
            if host:
                self._minio = Minio(host, access_key=access_key, secret_key=secret_key, secure=minio_secure)

    def _read_matrix(self, matrix_uri: str) -> tuple[int, list[list[float]]]:
        if matrix_uri.startswith("s3://"):
            parsed = urlparse(matrix_uri)
            bucket = parsed.netloc
            key = parsed.path.lstrip("/")
            if self._minio is None:
                raise RuntimeError(
                    "MinIO client not configured — cannot read s3:// matrix URIs. "
                    "Set RTMF_AISTOR_ENDPOINT, RTMF_AISTOR_ACCESS_KEY, "
                    "and RTMF_AISTOR_SECRET_KEY or pass minio_* params."
                )
            response = self._minio.get_object(bucket, key)
            try:
                content = response.read().decode("utf-8")
            finally:
                response.close()
                response.release_conn()
            lines = content.splitlines()
            repetitions = int(lines[0].strip())
            rows = []
            for line in lines[1:]:
                stripped = line.strip()
                if stripped:
                    rows.append([float(v) for v in stripped.split()])
            return repetitions, rows

        matrix_path = Path(matrix_uri)
        with matrix_path.open("r", encoding="utf-8") as f:
            repetitions = int(f.readline().strip())
            rows = []
            for line in f:
                stripped = line.strip()
                if stripped:
                    rows.append([float(v) for v in stripped.split()])
        return repetitions, rows

    def submit_simulation_batch(
        self, simulator_uri: str, matrix_uri: str, combinations: int, simulator_id: str
    ) -> ScheduledBatchInfo:
        output_name = "result_x"

        repetitions, rows = self._read_matrix(matrix_uri)

        n_params = len(rows[0]) if rows else 1
        param_names = [f"param_{chr(ord('a') + i)}" for i in range(n_params)]

        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["seed", "realization_id"] + param_names + [output_name])

        for seed, values in enumerate(rows):
            result = _rosenbrock(np.array(values))
            for realization_id in range(repetitions):
                writer.writerow([seed, realization_id] + values + [result])

        csv_data = output.getvalue().encode()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("results.csv", csv_data)

        job_id = hashlib.md5(f"{simulator_id}{time.time()}".encode()).hexdigest()[:8]

        url = f"memory://{job_id}/results/0/results.csv.zip"
        self._results_repo.store(url, buf.getvalue())
        self._jobs_repo.store_result(job_id, ResultRef(sub_job_id="0", url=url))

        return ScheduledBatchInfo(
            job_id=job_id,
            sub_job_ids=["0"],
            repetitions=1,
            matrix_rows=combinations,
        )

    def get_job(self, job_id: str) -> JobInfo | None:
        return JobInfo(
            job_id=job_id,
            status="success",
            created_at="2026-05-28T11:30:00",
        )

    def list_jobs(self) -> list[JobSummary]:
        raise NotImplementedError("Implement me!")

    def get_job_sub_jobs(self, job_id: str) -> list[SubJobInfo]:
        raise NotImplementedError("Implement me!")

    def get_sub_job_stderr(self, job_id: str, sub_job_id: str) -> str:
        raise NotImplementedError("Implement me!")

    def get_sub_job_stdout(self, job_id: str, sub_job_id: str) -> str:
        raise NotImplementedError("Implement me!")
