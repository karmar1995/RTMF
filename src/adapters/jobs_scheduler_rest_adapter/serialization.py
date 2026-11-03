from __future__ import annotations

from typing import Any

from use_case_contracts.dtos import JobInfo, JobSummary, ScheduledBatchInfo, SubJobInfo
from use_case_contracts.errors import ExternalServiceError


def parse_scheduled_batch_info(payload: Any) -> ScheduledBatchInfo:
    data = _ensure_dict(payload, "Jobs scheduler service returned invalid batch payload")
    job_id = _require_text(data, "job_id", "Jobs scheduler service batch payload missing job_id")
    sub_job_ids_raw = data.get("sub_job_ids")
    sub_job_ids = [str(item) for item in sub_job_ids_raw] if isinstance(sub_job_ids_raw, list) else []
    return ScheduledBatchInfo(
        job_id=job_id,
        sub_job_ids=sub_job_ids,
        repetitions=1,
        matrix_rows=len(sub_job_ids),
    )


def parse_job_info(payload: Any) -> JobInfo:
    data = _ensure_dict(payload, "Jobs scheduler service returned invalid job payload")
    return JobInfo(
        job_id=_require_text(data, "job_id", "Jobs scheduler service job payload missing job_id"),
        status=_require_text(data, "status", "Jobs scheduler service job payload missing status"),
        created_at=_optional_text(data.get("created_at")),
    )


def parse_job_summary_list(payload: Any) -> list[JobSummary]:
    if not isinstance(payload, list):
        raise ExternalServiceError("Jobs scheduler service returned invalid jobs list payload")
    summaries: list[JobSummary] = []
    for item in payload:
        data = _ensure_dict(item, "Jobs scheduler service returned invalid job summary item")
        summaries.append(
            JobSummary(
                job_id=_require_text(data, "job_id", "Jobs scheduler service job summary missing job_id")
            )
        )
    return summaries


def parse_sub_job_info_list(payload: Any) -> list[SubJobInfo]:
    if not isinstance(payload, list):
        raise ExternalServiceError("Jobs scheduler service returned invalid sub-jobs list payload")
    items: list[SubJobInfo] = []
    for item in payload:
        data = _ensure_dict(item, "Jobs scheduler service returned invalid sub-job item")
        items.append(
            SubJobInfo(
                sub_job_id=_require_text(
                    data,
                    "sub_job_id",
                    "Jobs scheduler service sub-job payload missing sub_job_id",
                ),
                job_id=_require_text(data, "job_id", "Jobs scheduler service sub-job payload missing job_id"),
                status=_require_text(data, "status", "Jobs scheduler service sub-job payload missing status"),
                params=[],
                repetition=1,
            )
        )
    return items


def parse_text_response_payload(payload: Any, *, field_name: str = "content") -> str:
    if isinstance(payload, str):
        return payload
    data = _ensure_dict(payload, "Jobs scheduler service returned invalid text payload")
    value = data.get(field_name)
    if value is None:
        raise ExternalServiceError(
            f"Jobs scheduler service text payload missing {field_name}"
        )
    return str(value)


def _ensure_dict(payload: Any, error_message: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExternalServiceError(error_message)
    return payload


def _require_text(payload: dict[str, Any], key: str, error_message: str) -> str:
    value = payload.get(key)
    if value is None:
        raise ExternalServiceError(error_message)
    return str(value)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
