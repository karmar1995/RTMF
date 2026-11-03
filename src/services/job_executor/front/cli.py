from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from services.job_executor.core.models import ExecutionRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Job Executor CLI")
    parser.add_argument("--matrix-uri", required=True)
    parser.add_argument("--row-index", type=int, default=None, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--sub-job-id", required=True)
    parser.add_argument("--simulator-path", default=os.getenv("JOB_EXECUTOR_SIMULATOR_PATH"))
    parser.add_argument("--workdir", default='./workspace')
    return parser


def parse_request(argv: Sequence[str] | None = None) -> ExecutionRequest:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.simulator_path:
        raise ValueError("simulator_path is required (set --simulator-path or JOB_EXECUTOR_SIMULATOR_PATH)")

    job_id = args.job_id
    sub_job_id = args.sub_job_id
    return ExecutionRequest(
        job_id=job_id,
        sub_job_id=sub_job_id,
        simulator_path=Path(args.simulator_path),
        matrix_uri=args.matrix_uri,
        row_index=args.row_index,
        workdir=Path(args.workdir),
    )

def render_error(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"
