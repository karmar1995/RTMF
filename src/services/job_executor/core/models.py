from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class ExecutionRequest:
    job_id: str
    sub_job_id: str
    simulator_path: Path
    matrix_uri: str
    row_index: int | None = None
    workdir: Path | None = None


@dataclass(frozen=True)
class ExecutionResult:
    job_id: str
    res_ids: Sequence[str]
