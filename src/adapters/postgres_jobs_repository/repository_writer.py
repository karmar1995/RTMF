from __future__ import annotations

from typing import Any

import psycopg

from use_case_contracts.ports import JobsRepositoryWriterPort

INSERT_JOB_SQL = """
    INSERT INTO jobs.job (job_id, simulator_id, created_at, status, results_root_url)
    VALUES (%s, %s, now(), %s, %s)
"""
UPDATE_JOB_STATUS_SQL = """
    UPDATE jobs.job
    SET status = %s
    WHERE job_id = %s
"""
UPDATE_JOBS_STATUSES_SQL_TEMPLATE = """
    UPDATE jobs.job AS j
    SET status = v.status
    FROM (VALUES {values_placeholders}) AS v(job_id, status)
    WHERE j.job_id = v.job_id
"""

GET_STARTED_JOBS_SQL = """
    SELECT job_id
    FROM jobs.job
    WHERE status = %s
"""


class PostgresJobsRepository(JobsRepositoryWriterPort):
    def __init__(self, dsn: str) -> None:
        normalized_dsn = dsn.strip()
        if not normalized_dsn:
            raise RuntimeError("Missing PostgreSQL DSN for jobs repository")
        self._dsn = normalized_dsn

    def store_job(self, job_id, simulator_id, status):
        parsed_job_id = _parse_bigint(job_id, field_name="job_id")
        parsed_simulator_id = _parse_bigint(simulator_id, field_name="simulator_id")
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        INSERT_JOB_SQL,
                        (parsed_job_id, parsed_simulator_id, status, ""),
                    )
        except psycopg.IntegrityError as exc:
            raise RuntimeError(
                f"Failed to store job '{parsed_job_id}' in PostgreSQL: duplicate or invalid reference"
            ) from exc
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to store job '{parsed_job_id}' in PostgreSQL: {exc}"
            ) from exc

    def update_jobs_statuses(self, job_ids_to_statuses):
        if not job_ids_to_statuses:
            return

        parsed_items = [
            (_parse_bigint(job_id, field_name="job_id"), status)
            for job_id, status in job_ids_to_statuses.items()
        ]
        values_placeholders = ", ".join(["(%s, %s)"] * len(parsed_items))
        query = UPDATE_JOBS_STATUSES_SQL_TEMPLATE.format(
            values_placeholders=values_placeholders,
        )
        params = [value for item in parsed_items for value in item]

        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(query, params)
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to update job statuses in PostgreSQL: {exc}"
            ) from exc

    def get_started_jobs(self) -> list[str]:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(GET_STARTED_JOBS_SQL, ("started",))
                    rows = cursor.fetchall()
            return [str(row[0]) for row in rows]
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to fetch started jobs from PostgreSQL: {exc}"
            ) from exc

def _parse_bigint(value: Any, *, field_name: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid {field_name} value: {value!r}") from exc
