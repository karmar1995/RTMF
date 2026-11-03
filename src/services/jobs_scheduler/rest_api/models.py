from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SubmitSimulationBatchRequest(BaseModel):
    simulator_uri: str = Field(min_length=1)
    matrix_uri: str = Field(min_length=1)
    combinations: int = Field(gt=0)
    simulator_id: str = Field(min_length=1)


class ScheduledBatchInfoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    sub_job_ids: list[str] | None = None


class JobSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    status: str


class JobInfoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    status: str
    simulator_uri: str | None = None
    matrix_uri: str | None = None


class SubJobInfoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    sub_job_id: str
    status: str


class SubJobStdoutResponse(BaseModel):
    content: str


class SubJobStderrResponse(BaseModel):
    content: str


class HealthResponse(BaseModel):
    status: str = "ok"


class ErrorResponse(BaseModel):
    detail: str
