from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from use_case_contracts.dtos import ResultRef


INSERT_EVALUATION_SQL = """
    INSERT INTO evaluations.evaluation (
        evaluation_id, simulator_id, created_at, updated_at, finished_at,
        status, stage, iteration, kmax, best_value, best_params,
        important_parameters, output_column, aggregation, problem, config,
        ssbo_history, final_result, error
    )
    VALUES (
        %s, %s, now(), now(), CASE WHEN %s THEN now() ELSE NULL END,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON CONFLICT (evaluation_id) DO UPDATE SET
        updated_at = now(),
        finished_at = CASE WHEN %s THEN now() ELSE NULL END,
        status = EXCLUDED.status,
        stage = EXCLUDED.stage,
        iteration = EXCLUDED.iteration,
        best_value = EXCLUDED.best_value,
        best_params = EXCLUDED.best_params,
        important_parameters = EXCLUDED.important_parameters,
        output_column = EXCLUDED.output_column,
        aggregation = EXCLUDED.aggregation,
        problem = EXCLUDED.problem,
        config = EXCLUDED.config,
        ssbo_history = EXCLUDED.ssbo_history,
        final_result = EXCLUDED.final_result,
        error = EXCLUDED.error
"""

UPDATE_PROGRESS_SQL = """
    UPDATE evaluations.evaluation
    SET updated_at = now(),
        status = %s,
        stage = %s,
        iteration = %s,
        best_value = %s,
        ssbo_history = %s
    WHERE evaluation_id = %s
"""

SELECT_ONE_COLUMNS = """
    status, stage, iteration, kmax, best_value, best_params,
    important_parameters, output_column, aggregation, problem, config,
    ssbo_history, final_result, error
"""

LOAD_EVALUATION_SQL = f"""
    SELECT simulator_id, created_at, {SELECT_ONE_COLUMNS}
    FROM evaluations.evaluation
    WHERE evaluation_id = %s
"""

LIST_EVALUATION_IDS_SQL = """
    SELECT evaluation_id
    FROM evaluations.evaluation
    ORDER BY created_at DESC
"""

INSERT_EVALUATION_JOB_SQL = """
    INSERT INTO evaluations.evaluation_job (
        evaluation_id, job_id, stage, iteration
    )
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (evaluation_id, job_id) DO NOTHING
"""

COUNT_JOBS_BY_STAGE_SQL = """
    SELECT stage, count(*)
    FROM evaluations.evaluation_job
    WHERE evaluation_id = %s
    GROUP BY stage
    ORDER BY stage
"""

# Lets the monitor hide the individual SSBO submissions behind their
# evaluation, so an evaluation shows up as a single parent entry. The
# evaluation id is kept too, so the monitor can decide whether a finished
# evaluation is still backed by a live Slurm job.
LIST_EVALUATION_JOB_LINKS_SQL = """
    SELECT evaluation_id, job_id
    FROM evaluations.evaluation_job
    ORDER BY evaluation_id, job_id
"""

# Every result artifact produced by an evaluation's jobs, as one flat list.
# The analytics service merges a flat list of result URLs into a single
# dataset, which is what lets an evaluation be visualized as one big job.
# Sensitivity and SSBO results are intentionally mixed.
LIST_RESULTS_FOR_EVALUATION_SQL = """
    SELECT r.res_id, r.url
    FROM evaluations.evaluation_job AS ej
    JOIN results.result AS r ON r.job_id = ej.job_id
    WHERE ej.evaluation_id = %s
    ORDER BY ej.stage, ej.iteration, ej.job_id, r.res_id
"""

# Monitor card projection: metadata only, no large JSONB payloads.
LIST_SUMMARIES_SQL = """
    SELECT e.evaluation_id,
           e.simulator_id,
           s.model_name,
           e.created_at,
           e.status,
           e.stage,
           e.iteration,
           e.kmax,
           e.best_value
    FROM evaluations.evaluation AS e
    JOIN simulators.simulator AS s ON s.simulator_id = e.simulator_id
    ORDER BY e.created_at DESC
"""

# Mirrors _EvaluationState in services/evaluator/core/evaluator_service.py.
_STATE_DEFAULTS: dict[str, Any] = {
    "status": "queued",
    "simulator_id": "",
    "created_at": 0.0,
    "stage": None,
    "iteration": 0,
    "kmax": 0,
    "best_params": None,
    "best_value": None,
    "output_column": None,
    "aggregation": None,
    "problem": None,
    "important_parameters": None,
    "config": {},
    "ssbo_history": [],
    "final_result": None,
    "error": None,
}

# Statuses that mean "this evaluation will not progress any further on its own".
TERMINAL_STATUSES = frozenset({"success", "failed"})

_STAGE_COLUMNS = ("status", "stage", "iteration", "kmax")


class PostgresEvaluationsStore:
    """Postgres-backed implementation of EvaluationsStorePort.

    Exposes the port's dict-shaped load/save contract plus two hot-path methods
    (update_progress, record_job) so the SSBO loop can persist each iteration
    without rewriting the whole row through the generic save().
    """

    def __init__(self, dsn: str) -> None:
        normalized_dsn = dsn.strip()
        if not normalized_dsn:
            raise RuntimeError("Missing PostgreSQL DSN for evaluations store")
        self._dsn = normalized_dsn

    # --- EvaluationsStorePort contract ---

    def load(self, evaluation_id: str) -> dict[str, Any] | None:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(LOAD_EVALUATION_SQL, (evaluation_id,))
                    row = cursor.fetchone()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to load evaluation '{evaluation_id}' from PostgreSQL: {exc}"
            ) from exc
        if row is None:
            return None
        return _row_to_state(evaluation_id, row)

    def load_all(self) -> dict[str, dict[str, Any]]:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(LIST_EVALUATION_IDS_SQL)
                    ids = [str(row[0]) for row in cursor.fetchall()]
                    states: dict[str, dict[str, Any]] = {}
                    for evaluation_id in ids:
                        cursor.execute(LOAD_EVALUATION_SQL, (evaluation_id,))
                        row = cursor.fetchone()
                        if row is not None:
                            states[evaluation_id] = _row_to_state(evaluation_id, row)
        except psycopg.Error as exc:
            raise RuntimeError(f"Failed to list evaluations from PostgreSQL: {exc}") from exc
        return states

    def save(self, evaluation_id: str, data: dict[str, Any]) -> None:
        state = _merge_defaults(data)
        status = str(state.get("status") or "queued")
        is_terminal = status in TERMINAL_STATUSES
        best_value = state.get("best_value")
        params = (
            evaluation_id,
            _parse_bigint(state.get("simulator_id"), field_name="simulator_id"),
            is_terminal,
            status,
            state.get("stage"),
            int(state.get("iteration") or 0),
            int(state.get("kmax") or 0),
            _as_float(best_value),
            _as_jsonb(state.get("best_params")),
            _as_jsonb(state.get("important_parameters")),
            state.get("output_column"),
            state.get("aggregation"),
            _as_jsonb(state.get("problem")),
            _as_jsonb(state.get("config")) or Jsonb({}),
            _as_jsonb(state.get("ssbo_history")) or Jsonb([]),
            _as_jsonb(state.get("final_result")),
            state.get("error"),
            is_terminal,
        )
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(INSERT_EVALUATION_SQL, params)
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to save evaluation '{evaluation_id}' in PostgreSQL: {exc}"
            ) from exc

    # --- hot-path methods ---

    def update_progress(
        self,
        evaluation_id: str,
        *,
        status: str,
        stage: str | None,
        iteration: int,
        best_value: float | None,
        ssbo_history: list[dict],
    ) -> None:
        """Persist one SSBO iteration without rewriting the rest of the row."""

        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        UPDATE_PROGRESS_SQL,
                        (
                            status,
                            stage,
                            iteration,
                            _as_float(best_value),
                            _as_jsonb(ssbo_history) or Jsonb([]),
                            evaluation_id,
                        ),
                    )
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to update progress for evaluation '{evaluation_id}' in PostgreSQL: {exc}"
            ) from exc

    def record_job(
        self,
        evaluation_id: str,
        job_id: str,
        *,
        stage: str,
        iteration: int = 0,
    ) -> None:
        """Link a submitted Slurm job back to the evaluation that created it."""

        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        INSERT_EVALUATION_JOB_SQL,
                        (
                            evaluation_id,
                            _parse_bigint(job_id, field_name="job_id"),
                            stage,
                            iteration,
                        ),
                    )
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to record job '{job_id}' for evaluation "
                f"'{evaluation_id}' in PostgreSQL: {exc}"
            ) from exc

    def job_counts(self, evaluation_id: str) -> dict[str, int]:
        """Submitted job counts per stage, for the evaluation detail page.

        Counts rows in the link table, so this reflects jobs handed to the
        scheduler rather than jobs that finished successfully.
        """

        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(COUNT_JOBS_BY_STAGE_SQL, (evaluation_id,))
                    rows = cursor.fetchall()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to count jobs for evaluation '{evaluation_id}': {exc}"
            ) from exc
        return {str(stage): int(count) for stage, count in rows}

    def list_evaluation_job_links(self) -> dict[str, set[str]]:
        """Map each evaluation to the Slurm job ids it submitted.

        The monitor lists live scheduler jobs, so it needs both the flat set
        (to hide the individual SSBO submissions behind their evaluation) and
        the per-evaluation grouping (to keep a finished evaluation visible only
        while one of its jobs is still tracked by Slurm). Ids are returned as
        strings because ``job_id`` is BIGINT in SQL while the scheduler reports
        it as a string.
        """

        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(LIST_EVALUATION_JOB_LINKS_SQL)
                    rows = cursor.fetchall()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to list jobs owned by evaluations: {exc}"
            ) from exc

        links: dict[str, set[str]] = {}
        for evaluation_id, job_id in rows:
            links.setdefault(str(evaluation_id), set()).add(str(job_id))
        return links

    def list_summaries(self) -> list[dict[str, Any]]:
        """Lightweight per-evaluation summary for the monitor list.

        Selects only what a monitor card needs. The large JSONB columns
        (``ssbo_history``, ``config``, ``problem``, ``final_result``) are
        deliberately excluded because the monitor refreshes on a timer.
        """

        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(LIST_SUMMARIES_SQL)
                    rows = cursor.fetchall()
        except psycopg.Error as exc:
            raise RuntimeError(f"Failed to list evaluation summaries: {exc}") from exc

        summaries: list[dict[str, Any]] = []
        for row in rows:
            (
                evaluation_id,
                simulator_id,
                model_name,
                created_at,
                status,
                stage,
                iteration,
                kmax,
                best_value,
            ) = row
            summaries.append(
                {
                    "evaluation_id": str(evaluation_id),
                    "simulator_id": str(simulator_id),
                    "model_name": model_name,
                    "created_at": created_at,
                    "status": str(status),
                    "stage": stage,
                    "iteration": int(iteration or 0),
                    "kmax": int(kmax or 0),
                    "best_value": _as_float(best_value),
                }
            )
        return summaries

    def list_results_for_evaluation(self, evaluation_id: str) -> list[ResultRef]:
        """Result artifacts of every job this evaluation submitted.

        Returned as a flat list because the analytics service merges a list of
        result URLs into a single dataset. Sensitivity and SSBO results are
        mixed deliberately, so the evaluation plots as one big job.
        """

        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(LIST_RESULTS_FOR_EVALUATION_SQL, (evaluation_id,))
                    rows = cursor.fetchall()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to list results for evaluation '{evaluation_id}': {exc}"
            ) from exc
        return [ResultRef(sub_job_id=str(sub_job_id), url=url) for sub_job_id, url in rows]


    def evaluation_status(self, evaluation_id: str) -> str | None:
        """Current status, or None when the evaluation does not exist.

        The jobs repository uses this to keep a partly finished evaluation out
        of the visualization list and off its direct URL.
        """

        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT status FROM evaluations.evaluation "
                        "WHERE evaluation_id = %s",
                        (evaluation_id,),
                    )
                    row = cursor.fetchone()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to read status for evaluation '{evaluation_id}': {exc}"
            ) from exc
        return None if row is None else str(row[0])

    def simulator_id_for_evaluation(self, evaluation_id: str) -> str:
        """Simulator the evaluation ran.

        Looked up per evaluation rather than by scanning every summary, since
        the jobs repository needs it on the visualization hot path.
        """

        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT simulator_id FROM evaluations.evaluation "
                        "WHERE evaluation_id = %s",
                        (evaluation_id,),
                    )
                    row = cursor.fetchone()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to read simulator for evaluation '{evaluation_id}': {exc}"
            ) from exc
        if row is None:
            raise RuntimeError(f"Evaluation '{evaluation_id}' was not found.")
        return str(row[0])


def _row_to_state(evaluation_id: str, row: tuple[Any, ...]) -> dict[str, Any]:
    (
        simulator_id,
        created_at,
        status,
        stage,
        iteration,
        kmax,
        best_value,
        best_params,
        important_parameters,
        output_column,
        aggregation,
        problem,
        config,
        ssbo_history,
        final_result,
        error,
    ) = row

    state = dict(_STATE_DEFAULTS)
    state["evaluation_id"] = evaluation_id
    state["simulator_id"] = str(simulator_id)
    state["created_at"] = created_at.timestamp() if created_at is not None else 0.0
    state["stage"] = stage
    state["iteration"] = int(iteration or 0)
    state["kmax"] = int(kmax or 0)
    state["best_value"] = _as_float(best_value)
    state["best_params"] = best_params
    state["important_parameters"] = important_parameters
    state["output_column"] = output_column
    state["aggregation"] = aggregation
    state["problem"] = problem
    state["config"] = config
    state["ssbo_history"] = ssbo_history or []
    state["final_result"] = final_result
    state["error"] = error
    state["status"] = status

    error = state.get("error")
    if status == "failed" and error and not state.get("final_result"):
        state["final_result"] = {
            "evaluation_id": evaluation_id,
            "status": "failed",
            "details": {"error": error},
        }
    return state


def _merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    state = dict(_STATE_DEFAULTS)
    state.update(data or {})
    return state


def _as_jsonb(value: Any) -> Jsonb | None:
    """Wrap a value for a JSONB column, tolerating numpy scalars/arrays.

    The SSBO history contains numpy arrays, so plain ``Jsonb(value)`` would
    raise on every iteration write.
    """
    if value is None:
        return None
    if isinstance(value, Jsonb):
        return value
    return Jsonb(json.loads(json.dumps(value, default=_json_default)))


def _json_default(value: Any) -> Any:
    import numpy as np

    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_bigint(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or value is None:
        raise RuntimeError(f"Invalid {field_name} value: {value!r}")
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid {field_name} value: {value!r}") from exc