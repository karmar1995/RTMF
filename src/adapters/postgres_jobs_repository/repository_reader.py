from __future__ import annotations

from typing import Any

import psycopg

from use_case_contracts.errors import NotFoundError
from use_case_contracts.ports import (
    EvaluationResultsStorePort,
    JobsRepositoryReaderPort,
)
from use_case_contracts.dtos import (
    Job4Visualization,
    JobResultRef,
    JobVisualizationPage,
    ResultRef,
    VisualizationTarget,
)

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

# An evaluation counts as finished only once its pipeline completed. Filter on
# status rather than stage: rows written before stage was given terminal values
# still carry the phase they ran in, so a stage filter would hide evaluations
# that already finished. Shared with resolve_visualization_target so the list and
# the resolver cannot drift apart.
FINISHED_EVALUATION_STATUS = "success"

# Shared body of the visualization list: successful simulation jobs, minus
# any job an evaluator submitted, unioned with the finished evaluations that
# produced at least one result. An evaluation is therefore listed once, as one
# big job. Partly finished evaluations stay visible on the evaluation queue and
# the monitor, but are not visualizable yet.
# Ordered by creation time so jobs and evaluations interleave sensibly.
_VISUALIZATION_LIST_BODY = """
    SELECT j.job_id::text AS target_id,
           s.model_name,
           j.created_at,
           'job' AS kind
    FROM jobs.job AS j
    JOIN simulators.simulator AS s ON j.simulator_id = s.simulator_id
    WHERE j.status = %(status)s
      AND NOT EXISTS (
          SELECT 1 FROM evaluations.evaluation_job AS ej WHERE ej.job_id = j.job_id
      )
    UNION ALL
    SELECT e.evaluation_id AS target_id,
           s.model_name,
           e.created_at,
           'evaluation' AS kind
    FROM evaluations.evaluation AS e
    JOIN simulators.simulator AS s ON e.simulator_id = s.simulator_id
    WHERE e.status = %(evaluation_status)s
      AND EXISTS (
          SELECT 1
          FROM evaluations.evaluation_job AS ej
          JOIN results.result AS r ON r.job_id = ej.job_id
          WHERE ej.evaluation_id = e.evaluation_id
      )
"""

VISUALIZATION_LIST_COUNT_SQL = (
    f"SELECT count(*) FROM ({_VISUALIZATION_LIST_BODY}) AS targets"
)

VISUALIZATION_LIST_PAGE_SQL = f"""
    SELECT target_id, model_name, created_at, kind
    FROM ({_VISUALIZATION_LIST_BODY}) AS targets
    ORDER BY created_at DESC, target_id
    LIMIT %(per_page)s OFFSET %(offset)s
"""


class PostgresJobsRepositoryReader(JobsRepositoryReaderPort):
    def __init__(
        self,
        dsn: str,
        evaluations_store: EvaluationResultsStorePort | None = None,
    ) -> None:
        normalized_dsn = dsn.strip()
        if not normalized_dsn:
            raise RuntimeError("Missing PostgreSQL DSN for jobs repository")
        self._dsn = normalized_dsn
        # Optional: when present, an evaluation id can be visualized as one
        # aggregated job. Absent, behaviour is unchanged and job-only.
        self._evaluations_store = evaluations_store

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

    def update_job_status(self, job_id, status):
        parsed_job_id = _parse_bigint(job_id, field_name="job_id")
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(UPDATE_JOB_STATUS_SQL, (status, parsed_job_id))
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to update status for job '{parsed_job_id}' in PostgreSQL: {exc}"
            ) from exc

    def list_jobs(self) -> list[str]:
        query = """
            SELECT job_id
            FROM jobs.job
            ORDER BY job_id ASC
        """
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(query)
                    return [str(job_id) for (job_id,) in cursor.fetchall()]
        except psycopg.Error as exc:
            raise RuntimeError(f"Failed to list jobs from PostgreSQL: {exc}") from exc

    def list_jobs_for_visualization(
        self, page: int = 1, per_page: int = 20
    ) -> JobVisualizationPage:
        """Successful simulation jobs plus finished evaluations with results.

        Jobs submitted by an evaluator are hidden here and represented once by
        their evaluation, so an evaluation with many SSBO jobs appears as a
        single row that visualizes as one big job.

        Evaluations are listed only once their pipeline has finished: an
        evaluation still running has partial results, and building a dataset
        from those would freeze an incomplete view.
        """

        offset = max(0, (page - 1) * per_page)
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        VISUALIZATION_LIST_COUNT_SQL,
                        {
                            "status": "successful",
                            "evaluation_status": FINISHED_EVALUATION_STATUS,
                        },
                    )
                    total = int(cursor.fetchone()[0])
                    cursor.execute(
                        VISUALIZATION_LIST_PAGE_SQL,
                        {
                            "status": "successful",
                            "evaluation_status": FINISHED_EVALUATION_STATUS,
                            "per_page": per_page,
                            "offset": offset,
                        },
                    )
                    rows = cursor.fetchall()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to list visualization targets from PostgreSQL: {exc}"
            ) from exc
        return JobVisualizationPage(
            jobs=[
                Job4Visualization(
                    job_id=str(target_id),
                    model_name=str(model_name),
                    created_at=created_at.isoformat() if created_at is not None else "",
                    kind=kind,
                )
                for target_id, model_name, created_at, kind in rows
            ],
            page=page,
            per_page=per_page,
            total=total,
        )

    def job_details(self, job_id) -> JobResultRef:
        parsed_job_id = _parse_bigint(job_id, field_name="job_id")
        job_query = """
            SELECT job_id, simulator_id, created_at, results_root_url
            FROM jobs.job
            WHERE job_id = %s
        """
        results_query = """
            SELECT res_id, url
            FROM results.result
            WHERE job_id = %s
            ORDER BY res_id ASC
        """
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(job_query, (parsed_job_id,))
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeError(f"Job '{parsed_job_id}' not found in PostgreSQL")
                    cursor.execute(results_query, (parsed_job_id,))
                    cursor.fetchall()
        except RuntimeError:
            raise
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to read job '{parsed_job_id}' from PostgreSQL: {exc}"
            ) from exc
        return _job_result_ref_from_row(row)

    def list_results(self, job_id: str) -> list[ResultRef]:
        parsed_job_id = _parse_bigint(job_id, field_name="job_id")
        query = """
            SELECT res_id, url
            FROM results.result
            WHERE job_id = %s
            ORDER BY res_id ASC
        """
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(query, (parsed_job_id,))
                    return [_result_ref_from_row(row) for row in cursor.fetchall()]
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to list results for job '{parsed_job_id}' from PostgreSQL: {exc}"
            ) from exc

    def resolve_visualization_target(self, target_id: str) -> VisualizationTarget:
        """Resolve a job id or an evaluation id into a single plot source.

        A job id is tried first, keeping today's behaviour. An evaluation is
        then presented as one big job: its results are the union of every
        artifact its jobs produced, which the analytics service merges into a
        single dataset.

        An evaluation is only visualizable once it has finished. The list hides
        unfinished evaluations, and this refuses them too, so a bookmarked URL
        cannot open one: the merged dataset would be partial, and analytics
        caches the first result set it is handed for the job key without
        refreshing, so the incomplete view would stick.
        """

        job = self._try_resolve_job(target_id)
        if job is not None:
            return job

        if self._evaluations_store is None:
            raise NotFoundError(
                f"Job '{target_id}' was not found and no evaluations store is configured."
            )

        # Cheapest possible probe first: a primary-key lookup, before the
        # join that collects result artifacts.
        status = self._evaluations_store.evaluation_status(target_id)
        if status != FINISHED_EVALUATION_STATUS:
            detail = "not found" if status is None else f"status '{status}'"
            raise NotFoundError(
                f"Evaluation '{target_id}' is not finished ({detail}); "
                f"it becomes visualizable once it completes."
            )

        result_urls = self._evaluations_store.list_results_for_evaluation(target_id)
        if not result_urls:
            raise NotFoundError(
                f"Neither a job nor an evaluation with results was found for '{target_id}'."
            )
        return VisualizationTarget(
            id=target_id,
            simulator_id=self._evaluation_simulator_id(target_id),
            # Never fetched from; analytics only carries it as metadata.
            job_root_url="",
            result_urls=result_urls,
            is_evaluation=True,
        )

    def _try_resolve_job(self, target_id: str) -> VisualizationTarget | None:
        try:
            parsed_job_id = _parse_bigint(target_id, field_name="job_id")
        except RuntimeError:
            # Not numeric, so it cannot be a job id. Treat as an evaluation.
            return None

        query = """
            SELECT job_id, simulator_id, results_root_url
            FROM jobs.job
            WHERE job_id = %s
        """
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(query, (parsed_job_id,))
                    row = cursor.fetchone()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to read job '{parsed_job_id}' from PostgreSQL: {exc}"
            ) from exc
        if row is None:
            return None
        return VisualizationTarget(
            id=str(row[0]),
            simulator_id=str(row[1]),
            job_root_url=row[2] or "",
            result_urls=self.list_results(str(row[0])),
            is_evaluation=False,
        )

    def _evaluation_simulator_id(self, evaluation_id: str) -> str:
        try:
            return self._evaluations_store.simulator_id_for_evaluation(evaluation_id)
        except RuntimeError as exc:
            raise NotFoundError(f"Evaluation '{evaluation_id}' was not found.") from exc


def _parse_bigint(value: Any, *, field_name: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid {field_name} value: {value!r}") from exc


def _job_result_ref_from_row(row: tuple[Any, Any, Any, Any]) -> JobResultRef:
    job_id, simulator_id, created_at, results_root_url = row
    return JobResultRef(
        job_id=str(job_id),
        simulator_id=str(simulator_id),
        created_at=created_at.isoformat(),
        job_root_url=str(results_root_url),
    )


def _result_ref_from_row(row: tuple[Any, Any]) -> ResultRef:
    res_id, url = row
    return ResultRef(
        sub_job_id=str(res_id),
        url=str(url),
    )
