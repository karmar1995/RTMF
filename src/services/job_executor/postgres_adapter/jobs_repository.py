from __future__ import annotations

from typing import Final

import psycopg

from services.job_executor.core.ports import JobsRepositoryPort


_UPDATE_JOB_ROOT_URL_SQL: Final = """
    UPDATE jobs.job
    SET results_root_url = %s
    WHERE job_id = %s
"""

_JOB_EXISTS_SQL: Final = """
    SELECT 1
    FROM jobs.job
    WHERE job_id = %s
"""

_UPSERT_RESULT_SQL: Final = """
    INSERT INTO results.result (job_id, res_id, url)
    VALUES (%s, %s, %s)
    ON CONFLICT (job_id, res_id) DO UPDATE
    SET
        url = EXCLUDED.url
"""


class PostgresJobsRepository(JobsRepositoryPort):
    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError("PostgreSQL DSN is required")
        self.dsn = dsn

    def store_job_root_url(self, job_id: str, url: str):
        db_job_id = _parse_bigint(job_id, field_name="job_id")

        try:
            with psycopg.connect(self.dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(_UPDATE_JOB_ROOT_URL_SQL, (url, db_job_id))

                    if cursor.rowcount == 1:
                        return

                    if cursor.rowcount == 0:
                        cursor.execute(_JOB_EXISTS_SQL, (db_job_id,))
                        row = cursor.fetchone()
                        if row is None:
                            raise RuntimeError(
                                f"Failed to store job root URL: job_id={db_job_id} was not found in jobs.job"
                            )

                        raise RuntimeError(
                            "Failed to store job root URL: "
                            f"job_id={db_job_id} already has a non-empty results_root_url"
                        )

                    raise RuntimeError(
                        "Failed to store job root URL: "
                        f"expected to update exactly one row for job_id={db_job_id}, updated {cursor.rowcount}"
                    )
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to store job root URL for job_id={db_job_id}"
            ) from exc

    def store_result_url(self, job_id: str, sub_job_id: str, url: str) -> None:
        db_job_id = _parse_bigint(job_id, field_name="job_id")
        db_sub_job_id = _parse_bigint(sub_job_id, field_name="sub_job_id")

        try:
            with psycopg.connect(self.dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        _UPSERT_RESULT_SQL,
                        (db_job_id, db_sub_job_id, url),
                    )
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to store result URL for job_id={db_job_id} sub_job_id={db_sub_job_id}"
            ) from exc


def _parse_bigint(value: str, field_name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid BIGINT-compatible integer: {value!r}") from exc
