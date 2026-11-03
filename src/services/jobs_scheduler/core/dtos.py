from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ScheduledBatchInfo:
    job_id: str
    sub_job_ids: list[str] | None = field(default=None)


@dataclass(frozen=True, slots=True)
class JobSummary:
    job_id: str
    status: str


@dataclass(frozen=True, slots=True)
class JobInfo:
    job_id: str
    status: str
    simulator_uri: str | None = None
    matrix_uri: str | None = None


@dataclass(frozen=True, slots=True)
class SubJobInfo:
    job_id: str
    sub_job_id: str
    status: str

