from __future__ import annotations

import csv
import io
import logging
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from use_case_contracts.dtos import (
    MatrixParameterDefinition,
    ParamType,
    SimulatorDetails,
    SimulatorSummary,
)
from use_case_contracts.errors import NotFoundError
from use_case_contracts.ports import (
    AnalyticsPort,
    JobsRepositoryReaderPort,
    JobsSchedulerPort,
    MatrixGenerationPort,
    ParserPort,
    ResultsRepositoryPort,
    SimulatorRepository,
)

from services.evaluator.core.dto import (
    EvaluationProgress,
    EvaluationResultResponse,
    EvaluationSummary,
)
from services.evaluator.core.errors import EvaluationNotFound, EvaluationNotComplete
from services.evaluator.core.ports import EvaluatorPort, EvaluationsStorePort
from services.evaluator.core.ssbo import SSBO

logger = logging.getLogger(__name__)


@dataclass
class _EvaluationState:
    status: str = "queued"
    simulator_id: str = ""
    created_at: float = 0.0
    stage: str | None = None
    iteration: int = 0
    kmax: int = 0
    best_params: dict[str, float | int] | None = None
    best_value: float | None = None
    output_column: str | None = None
    aggregation: str | None = None
    problem: dict | None = None
    important_parameters: list[str] | None = None
    config: dict | None = None
    ssbo_history: list[dict] = field(default_factory=list)
    final_result: EvaluationResultResponse | None = None
    error: str | None = None


_TERMINAL_STATUSES = frozenset({"success", "failed"})


def _best_value_from_history(history: list[dict]) -> float | None:
    """Lowest best_value recorded so far, or None if no iteration has one."""
    values = [
        float(entry["best_value"])
        for entry in history or []
        if isinstance(entry, dict) and entry.get("best_value") is not None
    ]
    return min(values) if values else None


def _result_from_dict(raw: Any) -> EvaluationResultResponse | None:
    if not isinstance(raw, dict):
        return None
    return EvaluationResultResponse(
        evaluation_id=raw.get("evaluation_id", ""),
        status=raw.get("status", ""),
        details=raw.get("details"),
    )


def _serialize_input_value(param: Any, value: object) -> str:
    ptype = getattr(param, "type", None)
    if ptype in {"int", "int_ts"}:
        return str(int(round(float(value))))
    if ptype in {"bool", "bool_ts"}:
        return (
            "true"
            if value in (True, 1, "1", "true", "True", "yes")
            else "false"
        )
    return str(value)


def _aggregate_timeseries_value(
    csv_text: str,
    value_column: str,
    aggregation: str,
) -> float:
    dataframe = pd.read_csv(io.StringIO(csv_text), delimiter=";")
    if value_column not in dataframe.columns:
        raise ValueError(
            f"Timeseries CSV is missing expected column {value_column!r}"
        )
    series = pd.to_numeric(dataframe[value_column], errors="coerce").dropna()
    if series.empty:
        raise ValueError(
            f"No numeric values found in timeseries column {value_column!r}"
        )
    name = aggregation.strip().lower()
    if name == "mean":
        value = series.mean()
    elif name == "min":
        value = series.min()
    elif name == "max":
        value = series.max()
    elif name == "median":
        value = series.median()
    elif name == "p95":
        value = series.quantile(0.95)
    else:
        raise ValueError(f"Unsupported aggregation method: {aggregation!r}")
    return float(value)


class EvaluatorService(EvaluatorPort):
    def __init__(
        self,
        jobs_scheduler: JobsSchedulerPort,
        simulator_repository: SimulatorRepository,
        jobs_repository: JobsRepositoryReaderPort,
        results_repository: ResultsRepositoryPort,
        analytics: AnalyticsPort,
        parser: ParserPort,
        matrix_generator: MatrixGenerationPort,
        state_store: EvaluationsStorePort | None = None,
    ) -> None:
        self.__jobs_scheduler = jobs_scheduler
        self.__simulator_repo = simulator_repository
        self.__jobs_repo = jobs_repository
        self.__results_repo = results_repository
        self.__analytics = analytics
        self.__parser = parser
        self.__matrix_generator = matrix_generator
        self.__lock = threading.Lock()
        self.__state_store = state_store
        # Transient copy of in-flight state only. The store is the source of
        # truth; this dict holds states touched by the running pipeline so
        # concurrent status updates do not each round-trip to the database.
        self.__evaluations: dict[str, _EvaluationState] = {}
        if state_store is not None:
            self._reconcile_interrupted(self._load_states())

    def evaluate(
        self,
        simulator_id: str,
        *,
        kmax: int = 30,
        epsilon: float = 1e-3,
        batch_size: int = 1,
        lhs_candidates: int = 1500,
        random_state: int = 42,
        number_of_repetitions: int = 128,
        problem: dict | None = None,
        aggregation: str | None = None,
    ) -> str:
        evaluation_id = uuid.uuid4().hex[:16]
        now = time.time()
        state = _EvaluationState(
            simulator_id=simulator_id,
            created_at=now,
            kmax=kmax,
            output_column=(problem or {}).get("output"),
            aggregation=aggregation,
            problem=problem,
            config={
                "kmax": kmax,
                "epsilon": epsilon,
                "batch_size": batch_size,
                "lhs_candidates": lhs_candidates,
                "random_state": random_state,
                "number_of_repetitions": number_of_repetitions,
            },
        )
        with self.__lock:
            self.__evaluations[evaluation_id] = state
            # Write the row before starting the thread so an evaluation that
            # dies immediately is still visible in the queue.
            self._persist_state(evaluation_id, state)
        thread = threading.Thread(
            target=self._run_pipeline,
            args=(evaluation_id, simulator_id, number_of_repetitions),
            kwargs=dict(
                kmax=kmax,
                epsilon=epsilon,
                batch_size=batch_size,
                lhs_candidates=lhs_candidates,
                random_state=random_state,
                problem=problem,
                aggregation=aggregation,
            ),
            daemon=True,
        )
        thread.start()
        return evaluation_id

    def get_evaluation_status(self, evaluation_id: str) -> str:
        if self.__state_store is not None:
            raw = self.__state_store.load(evaluation_id)
            if raw is None:
                raise EvaluationNotFound(f"Evaluation '{evaluation_id}' not found")
            return raw.get("status", "queued")
        with self.__lock:
            state = self.__evaluations.get(evaluation_id)
            if state is None:
                raise EvaluationNotFound(f"Evaluation '{evaluation_id}' not found")
            return state.status

    def list_evaluations(self) -> list[EvaluationSummary]:
        if self.__state_store is not None:
            all_raw = self.__state_store.load_all()
            return [
                EvaluationSummary(
                    evaluation_id=evaluation_id,
                    simulator_id=raw.get("simulator_id", ""),
                    status=raw.get("status", "queued"),
                    created_at=datetime.fromtimestamp(raw["created_at"], tz=timezone.utc)
                    if raw.get("created_at")
                    else None,
                )
                for evaluation_id, raw in reversed(tuple(all_raw.items()))
            ]
        with self.__lock:
            return [
                EvaluationSummary(
                    evaluation_id=evaluation_id,
                    simulator_id=state.simulator_id,
                    status=state.status,
                    created_at=datetime.fromtimestamp(state.created_at, tz=timezone.utc)
                    if state.created_at
                    else None,
                )
                for evaluation_id, state in reversed(tuple(self.__evaluations.items()))
            ]

    def get_evaluation_progress(
        self, evaluation_id: str
    ) -> EvaluationProgress:
        """Return live progress for an evaluation.

        Reads through to the store so progress stays correct even when the
        evaluation is owned by another process (e.g. after a restart, or when
        several evaluator replicas share the database).
        """
        raw: dict[str, Any] | None = None
        if self.__state_store is not None:
            raw = self.__state_store.load(evaluation_id)
        else:
            with self.__lock:
                state = self.__evaluations.get(evaluation_id)
                if state is not None:
                    raw = self._state_to_dict(state)
        if raw is None:
            raise EvaluationNotFound(f"Evaluation '{evaluation_id}' not found")

        jobs_by_stage: dict[str, int] = {}
        jobs_submitted = 0
        if self.__state_store is not None:
            try:
                counts = self.__state_store.job_counts(evaluation_id)
            except Exception:
                logger.exception(
                    "Failed to read job counts for evaluation '%s'", evaluation_id
                )
            else:
                jobs_submitted = sum(counts.values())
                jobs_by_stage = counts

        history = raw.get("ssbo_history") or []
        return EvaluationProgress(
            evaluation_id=evaluation_id,
            status=raw.get("status", "queued"),
            stage=raw.get("stage"),
            iteration=int(raw.get("iteration", 0) or 0),
            kmax=int(raw.get("kmax", 0) or 0),
            best_params=raw.get("best_params"),
            best_value=(
                float(raw["best_value"])
                if raw.get("best_value") is not None
                else None
            ),
            important_parameters=raw.get("important_parameters"),
            ssbo_history=history,
            jobs_submitted=jobs_submitted,
            jobs_by_stage=jobs_by_stage,
        )

    def get_evaluation_results(self, evaluation_id: str) -> EvaluationResultResponse:
        if self.__state_store is not None:
            raw = self.__state_store.load(evaluation_id)
            if raw is None:
                raise EvaluationNotFound(f"Evaluation '{evaluation_id}' not found")
            result = _result_from_dict(raw.get("final_result"))
            if result is None:
                raise EvaluationNotComplete(
                    f"Evaluation '{evaluation_id}' not yet complete"
                )
            return result
        with self.__lock:
            state = self.__evaluations.get(evaluation_id)
            if state is None:
                raise EvaluationNotFound(f"Evaluation '{evaluation_id}' not found")
            if state.final_result is None:
                raise EvaluationNotComplete(
                    f"Evaluation '{evaluation_id}' not yet complete"
                )
            return state.final_result

    def _set_status(
        self, evaluation_id: str, status: str, *, stage: str | None = None
    ) -> None:
        with self.__lock:
            state = self.__evaluations.get(evaluation_id)
            if state is None:
                return
            state.status = status
            if stage is not None:
                state.stage = stage
            self._persist_state(evaluation_id, state)

    def _publish_progress(self, evaluation_id: str, history: list[dict]) -> None:
        """Persist one completed SSBO iteration.

        Uses the targeted update rather than a full row rewrite so the hot loop
        does not re-send config/problem/best_params on every iteration. The
        in-memory state is refreshed when we own the evaluation; otherwise the
        persisted row is the source of truth for status and stage.
        """
        if self.__state_store is None:
            return
        with self.__lock:
            state = self.__evaluations.get(evaluation_id)
            if state is not None:
                state.ssbo_history = history
                state.iteration = len(history)
                best_value = _best_value_from_history(history)
                state.best_value = best_value
                status = state.status
                stage = state.stage
                iteration = state.iteration
            else:
                raw = self.__state_store.load(evaluation_id)
                if raw is None:
                    logger.warning(
                        "Ignoring progress for unknown evaluation '%s'",
                        evaluation_id,
                    )
                    return
                status = str(raw.get("status") or "queued")
                stage = raw.get("stage")
                iteration = len(history)
            try:
                self.__state_store.update_progress(
                    evaluation_id,
                    status=status,
                    stage=stage,
                    iteration=iteration,
                    best_value=_best_value_from_history(history),
                    ssbo_history=history,
                )
            except Exception:
                logger.exception(
                    "Failed to persist progress for evaluation '%s'", evaluation_id
                )

    def _load_states(self) -> dict[str, _EvaluationState]:
        assert self.__state_store is not None
        loaded: dict[str, _EvaluationState] = {}
        for evaluation_id, raw in self.__state_store.load_all().items():
            state = self._state_from_dict(raw)
            if state is None:
                continue
            loaded[evaluation_id] = state
        return loaded

    def _reconcile_interrupted(
        self, loaded: dict[str, _EvaluationState]
    ) -> None:
        """Fail any evaluation that was still in flight when we last stopped.

        Progress recorded up to that point is kept, so the detail page can still
        show how far the optimizer got before the interruption.
        """
        for evaluation_id, state in loaded.items():
            if state.status in _TERMINAL_STATUSES:
                continue
            state.status = "failed"
            state.stage = "failed"
            state.error = "Interrupted by restart"
            state.final_result = EvaluationResultResponse(
                evaluation_id=evaluation_id,
                status="failed",
                details={"error": state.error},
            )
            self._persist_state(evaluation_id, state)

    @staticmethod
    def _state_to_dict(state: _EvaluationState) -> dict[str, Any]:
        return asdict(state)

    @staticmethod
    def _state_from_dict(raw: dict[str, Any]) -> _EvaluationState | None:
        try:
            state = _EvaluationState(
                status=raw.get("status", "queued"),
                simulator_id=str(raw.get("simulator_id", "")),
                created_at=float(raw.get("created_at", 0.0)),
                stage=raw.get("stage"),
                iteration=int(raw.get("iteration", 0)),
                kmax=int(raw.get("kmax", 0)),
                best_params=raw.get("best_params"),
                best_value=(
                    float(raw["best_value"])
                    if raw.get("best_value") is not None
                    else None
                ),
                output_column=raw.get("output_column"),
                aggregation=raw.get("aggregation"),
                problem=raw.get("problem"),
                important_parameters=raw.get("important_parameters"),
                config=raw.get("config"),
                ssbo_history=raw.get("ssbo_history", []),
                final_result=_result_from_dict(raw.get("final_result")),
                error=raw.get("error"),
            )
            return state
        except (TypeError, ValueError):
            logger.exception("Failed to parse persisted evaluation state")
            return None

    def _persist_state(
        self, evaluation_id: str, state: _EvaluationState
    ) -> None:
        if self.__state_store is None:
            return
        self.__state_store.save(evaluation_id, self._state_to_dict(state))

    def _record_job(
        self,
        evaluation_id: str,
        job_id: str,
        *,
        stage: str,
        iteration: int = 0,
    ) -> None:
        """Link a submitted job to the evaluation. Never fails the pipeline."""
        if self.__state_store is None:
            return
        try:
            self.__state_store.record_job(
                evaluation_id, job_id, stage=stage, iteration=iteration
            )
        except Exception:
            logger.exception(
                "Failed to link job '%s' to evaluation '%s'", job_id, evaluation_id
            )

    def _run_pipeline(
        self,
        evaluation_id: str,
        simulator_id: str,
        number_of_repetitions: int,
        *,
        kmax: int,
        epsilon: float,
        batch_size: int,
        lhs_candidates: int,
        random_state: int,
        problem: dict | None = None,
        aggregation: str | None = None,
    ) -> None:
        try:
            simulator = self.__simulator_repo.get(simulator_id)
            if simulator is None:
                raise NotFoundError(f"Simulator '{simulator_id}' not found")
            if not simulator.input_params:
                raise NotFoundError(f"Simulator '{simulator_id}' has no input params")

            self._set_status(evaluation_id, "running", stage="running")

            if problem is not None:
                sweep_param_names = problem["names"]
                sweep_bounds = problem["bounds"]
                sweep_params = {
                    name: [str(bound[0]), str(bound[1])]
                    for name, bound in zip(sweep_param_names, sweep_bounds)
                }
            else:
                sweep_params = {
                    p.name: ["-2.12", "2.12"] for p in simulator.input_params
                }
            generated_matrix = (
                self.__matrix_generator.generate_satelli_matrix_combinations(
                    matrix_id=uuid.uuid4().hex[:8],
                    repetitions=number_of_repetitions,
                    parameter_definitions=[
                        MatrixParameterDefinition(name=p.name, type=p.type)
                        for p in simulator.input_params
                    ],
                    fixed_params={},
                    sweep_params=sweep_params,
                )
            )

            self._set_status(evaluation_id, "simulating", stage="simulating")
            matrix_rows = number_of_repetitions * (len(simulator.input_params) + 2)

            batch = self.__jobs_scheduler.submit_simulation_batch(
                simulator_uri=f"docker://{simulator.bin_url}",
                matrix_uri=generated_matrix.matrix_url,
                combinations=matrix_rows,
                simulator_id=simulator_id,
            )
            self._record_job(evaluation_id, batch.job_id, stage="sensitivity")
            self._await_job(evaluation_id, batch.job_id, stage="sensitivity")

            result_refs = self.__jobs_repo.list_results(batch.job_id)

            self._set_status(
                evaluation_id, "sensitivity_analysis", stage="sensitivity_analysis"
            )
            if problem is not None:
                sa_problem = problem
            else:
                sa_sweep_param_names = list(sweep_params.keys())
                sa_problem = {
                    "names": sa_sweep_param_names,
                    "bounds": [[-2.12, 2.12]] * len(sa_sweep_param_names),
                }

            output_column = (
                problem["output"]
                if problem is not None and problem.get("output")
                else simulator.output_params[0].name
            )
            sa_result = self.__analytics.analyze_sensitivity(
                results_urls=[ref.url for ref in result_refs],
                problem=sa_problem,
                n_real=number_of_repetitions,
                output_names=[output_column],
                aggregation=aggregation,
            )

            important_parameters = sa_result.important_parameters

            point_columns = important_parameters.get(output_column, [])

            if not point_columns:
                raise ValueError(f"No important parameters for '{output_column}'.")

            with self.__lock:
                state = self.__evaluations.get(evaluation_id)
                if state is not None:
                    state.important_parameters = list(point_columns)
                    self._persist_state(evaluation_id, state)

            mean_data_path = (
                Path(tempfile.mkdtemp()) / "stochastic_input_for_optimization.csv"
            )
            mean_data_path.write_text(sa_result.mean_data_csv, encoding="utf-8")

            optimizer_input_file = self._preprocess_optimization_data(
                input_filename=mean_data_path,
                point_columns=point_columns,
                value_column=output_column,
            )

            self._set_status(evaluation_id, "optimizing", stage="optimizing")
            X_init, y_init = self._read_initial_samples(optimizer_input_file)

            bounds = self._extract_bounds(point_columns, problem)

            best_fixed_values = self._best_fixed_param_values(
                mean_data_path=mean_data_path,
                input_param_names=[p.name for p in simulator.input_params],
                point_columns=point_columns,
                value_column=output_column,
            )

            def evaluation_callback(
                x: np.ndarray,
            ) -> tuple[float, np.ndarray]:
                # Read the optimizer's live iteration: it is advanced before each
                # batch is evaluated, so submitted jobs carry the iteration they
                # actually belong to (0..kmax) instead of a stale sentinel.
                return self._evaluate_single_point(
                    x=x,
                    simulator=simulator,
                    simulator_id=simulator_id,
                    point_columns=point_columns,
                    fixed_param_values=best_fixed_values,
                    number_of_repetitions=number_of_repetitions,
                    output_column=output_column,
                    aggregation=aggregation,
                    evaluation_id=evaluation_id,
                    iteration=ssbo.current_iteration,
                )

            def progress_callback(
                iteration: int, history: list[dict]
            ) -> None:
                self._publish_progress(evaluation_id, history)

            ssbo = SSBO(
                evaluation_callback=evaluation_callback,
                bounds=bounds,
                kmax=kmax,
                epsilon=epsilon,
                batch_size=batch_size,
                lhs_candidates=lhs_candidates,
                random_state=random_state,
                progress_callback=progress_callback,
            )
            ssbo.set_initial_samples(X_init, y_init)

            best_x, best_y, history = ssbo.optimize()
            self._publish_progress(evaluation_id, history)

            with self.__lock:
                state = self.__evaluations[evaluation_id]
                state.status = "success"
                state.stage = "finished"
                state.ssbo_history = history
                state.best_params = self._full_best_params(
                    input_param_names=[p.name for p in simulator.input_params],
                    point_columns=point_columns,
                    best_x=best_x,
                    fixed_param_values=best_fixed_values,
                )
                state.best_value = float(best_y)
                state.final_result = EvaluationResultResponse(
                    evaluation_id=evaluation_id,
                    status="success",
                    details={
                        "best_params": state.best_params,
                        "best_value": float(best_y),
                        "important_parameters": point_columns,
                        "iterations": kmax,
                        "history": [
                            {
                                "iteration": h["iteration"],
                                "best_value": h["best_value"],
                                "skipped": h.get("skipped", False),
                            }
                            for h in history
                        ],
                    },
                )
                self._persist_state(evaluation_id, state)

        except Exception as e:
            logger.exception("Evaluation '%s' failed", evaluation_id)
            with self.__lock:
                state = self.__evaluations.get(evaluation_id)
                if state is None:
                    return
                state.status = "failed"
                state.stage = "failed"
                state.error = str(e)
                state.final_result = EvaluationResultResponse(
                    evaluation_id=evaluation_id,
                    status="failed",
                    details={"error": str(e)},
                )
                self._persist_state(evaluation_id, state)

    @staticmethod
    def _preprocess_optimization_data(
        input_filename: str | Path,
        point_columns: list[str],
        value_column: str,
        output_filename: str = "optimizer_input.csv",
    ) -> Path:
        input_path = Path(input_filename)
        output_path = input_path.parent / output_filename

        with input_path.open("r", newline="", encoding="utf-8") as fin:
            reader = csv.DictReader(fin, delimiter=";")
            point_values: dict[str, list[float]] = {}
            point_order: list[str] = []

            for row in reader:
                point_string = ",".join(str(row[col]) for col in point_columns)
                value = float(row[value_column])
                if point_string not in point_values:
                    point_values[point_string] = []
                    point_order.append(point_string)
                point_values[point_string].append(value)

        rows_out = []
        for sample_id, point in enumerate(point_order):
            values = point_values[point]
            rows_out.append([sample_id, point, sum(values) / len(values)])

        with output_path.open("w", newline="", encoding="utf-8") as fout:
            writer = csv.writer(fout, delimiter=";")
            writer.writerow(["sample_id", "point", "value"])
            writer.writerows(rows_out)

        return output_path

    def _read_initial_samples(
        self, filepath: str | Path
    ) -> tuple[np.ndarray, np.ndarray]:
        X: list[np.ndarray] = []
        y: list[float] = []

        with open(filepath, "r") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                point = np.array([float(v) for v in row["point"].split(",")])
                value = float(row["value"])
                X.append(point)
                y.append(value)

        return np.array(X), np.array(y)

    def _extract_bounds(
        self, point_columns: list[str], problem: dict | None = None
    ) -> list[tuple[float, float]]:
        if problem is not None and "names" in problem and "bounds" in problem:
            names = problem["names"]
            bounds_map = {name: tuple(b) for name, b in zip(names, problem["bounds"])}
            return [bounds_map[col] for col in point_columns]
        return [(-2.12, 2.12) for _ in point_columns]

    @staticmethod
    def _full_best_params(
        input_param_names: list[str],
        point_columns: list[str],
        best_x: np.ndarray,
        fixed_param_values: dict[str, float],
    ) -> dict[str, float]:
        full: dict[str, float] = {}
        for name in input_param_names:
            if name in point_columns:
                full[name] = float(best_x[point_columns.index(name)])
            else:
                full[name] = fixed_param_values[name]
        return full

    @staticmethod
    def _best_fixed_param_values(
        mean_data_path: str | Path,
        input_param_names: list[str],
        point_columns: list[str],
        value_column: str,
    ) -> dict[str, float]:
        fixed_param_names = [
            name for name in input_param_names if name not in point_columns
        ]
        if not fixed_param_names:
            return {}

        best_row: dict[str, str] | None = None
        with open(mean_data_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            best_value: float | None = None
            for row in reader:
                value = float(row[value_column])
                if best_row is None or value < best_value:
                    best_row = row
                    best_value = value

        if best_row is None:
            raise ValueError(
                f"No mean-data rows found to resolve fixed values for {fixed_param_names}."
            )
        return {name: float(best_row[name]) for name in fixed_param_names}

    def _await_job(
        self,
        evaluation_id: str | None,
        job_id: str,
        *,
        stage: str | None = None,
        poll_interval: float = 0.5,
    ):
        """Poll a job until it reaches a terminal state.

        Returns the last observed job info. A transient scheduler failure is
        logged and retried rather than failing the whole evaluation, so a
        short scheduler hiccup does not lose hours of optimization work.
        """
        while True:
            try:
                job_info = self.__jobs_scheduler.get_job(job_id)
            except Exception:
                logger.exception(
                    "Failed to get status of job '%s' (stage=%s, evaluation=%s)",
                    job_id,
                    stage,
                    evaluation_id,
                )
            else:
                if job_info.status in ("successful", "failed", "success"):
                    return job_info
            time.sleep(poll_interval)

    def _evaluate_single_point(
        self,
        x: np.ndarray,
        simulator: SimulatorDetails | None = None,
        simulator_id: str | None = None,
        point_columns: list[str] | None = None,
        fixed_param_values: dict[str, float] | None = None,
        number_of_repetitions: int | None = None,
        output_column: str | None = None,
        aggregation: str | None = None,
        evaluation_id: str | None = None,
        iteration: int = 0,
    ) -> tuple[float, np.ndarray]:
        point_columns = point_columns or []
        fixed_param_values = fixed_param_values or {}

        full_values: list[str] = []
        for param in simulator.input_params:
            if param.name in point_columns:
                raw_value = x[point_columns.index(param.name)]
            else:
                raw_value = fixed_param_values[param.name]
            full_values.append(_serialize_input_value(param, raw_value))

        matrix_text = f"1\n{' '.join(full_values)}\n"
        matrix = self.__matrix_generator.upload_matrix(
            matrix_id=uuid.uuid4().hex[:8],
            matrix_text=matrix_text,
        )
        batch = self.__jobs_scheduler.submit_simulation_batch(
            simulator_uri=f"docker://{simulator.bin_url}",
            matrix_uri=matrix.matrix_url,
            combinations=1,
            simulator_id=simulator_id,
        )
        if evaluation_id is not None:
            self._record_job(
                evaluation_id, batch.job_id, stage="ssbo", iteration=iteration
            )
        job_info = self._await_job(evaluation_id, batch.job_id, stage="ssbo")
        if job_info.status == "failed":
            raise RuntimeError(f"SSBO evaluation job {batch.job_id} failed")
        refs = self.__jobs_repo.list_results(batch.job_id)
        csv_text = self.__results_repo.download(refs[0].url).decode()
        reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
        row = next(reader)
        return self._extract_output_value(
            row=row,
            result_url=refs[0].url,
            output_column=output_column,
            aggregation=aggregation,
        ), np.array([])

    def _extract_output_value(
        self,
        *,
        row: dict[str, str],
        result_url: str,
        output_column: str,
        aggregation: str | None,
    ) -> float:
        cell = (row.get(output_column) or "").strip()
        if not cell.lower().endswith(".csv"):
            return float(cell)
        aggregation_name = (aggregation or "mean").strip().lower()
        base_url = result_url.rsplit("/", 1)[0]
        timeseries_url = f"{base_url}/{cell}.zip"
        content = self.__results_repo.download(timeseries_url).decode("utf-8")
        return _aggregate_timeseries_value(
            csv_text=content,
            value_column=output_column,
            aggregation=aggregation_name,
        )
