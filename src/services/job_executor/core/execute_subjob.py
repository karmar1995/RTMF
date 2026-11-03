from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
from typing import List
import os

from services.job_executor.core.models import ExecutionRequest, ExecutionResult
from services.job_executor.core.ports import (
    ResultsRepositoryPort,
    MatrixSourcePort,
    SimulatorPort,
    JobsRepositoryPort
)


class ExecuteSubjob:
    def __init__(self,
                 simulator: SimulatorPort,
                 results_repo: ResultsRepositoryPort,
                 matrix_source: MatrixSourcePort,
                 jobs_repo: JobsRepositoryPort
                 ):
        self.simulator = simulator
        self.results_repo = results_repo
        self.matrix_source = matrix_source
        self.jobs_repo = jobs_repo

    def __call__(self, request: ExecutionRequest) -> ExecutionResult:
        matrix_bytes = self.matrix_source.download_matrix(request.matrix_uri)
        workdir = request.workdir or Path.cwd()
        res_ids: List[str] = []

        res_id = request.sub_job_id
        run_dir = workdir / request.job_id / request.sub_job_id
        run_dir.mkdir(parents=True, exist_ok=True)
        matrix_file = 'matrix.txt'
        with open(os.path.join(run_dir, matrix_file), 'wb') as f:
            f.write(matrix_bytes)

        self.simulator.run(str(request.simulator_path), matrix_file, str(request.row_index), str(run_dir))

        results_dir = run_dir / "results"
        results_csv = results_dir / "results.csv"

        if not results_csv.exists():
            raise FileNotFoundError(f"missing results.csv at {results_csv}")

        url = self.results_repo.upload_result_zip(
            job_id=request.job_id,
            sub_job_id=res_id,
            zip_bytes=_zip_single_file(results_csv, "results.csv"),
        )

        self.jobs_repo.store_job_root_url(
            job_id=request.job_id,
            url=self.results_repo.assemble_job_root_url(request.job_id)
        )

        self.jobs_repo.store_result_url(
            job_id=request.job_id,
            sub_job_id=res_id,
            url=url
        )

        timeseries_csvs = _find_timeseries_csvs(results_dir)
        for timeseries_csv in timeseries_csvs:
            self.results_repo.upload_csv_zip(
                request.job_id,
                res_id,
                timeseries_csv,
                _zip_single_file(results_dir / timeseries_csv, timeseries_csv),
            )
        res_ids.append(res_id)

        return ExecutionResult(job_id=request.job_id, res_ids=res_ids)


def _zip_single_file(path: Path, arcname: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(path, arcname)
    return buffer.getvalue()

def _find_timeseries_csvs(results_dir: Path) -> list[str]:
    matched: list[str] = []

    for path in results_dir.iterdir():
        if not path.is_file():
            continue

        if path.name == "results.csv":
            continue

        if not path.name.endswith(".csv"):
            continue

        matched.append(path.name)


    return matched
