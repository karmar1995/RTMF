from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg

from use_case_contracts.dtos import (
    SystemDiscoverySavedModelRecord,
    SystemDiscoverySimulationRecord,
    SystemDiscoverySimulationState,
    SystemDiscoveryTrainingRecord,
    SystemDiscoveryTrainingState,
)
from use_case_contracts.ports import (
    SystemDiscoverySavedModelRegistryPort,
    SystemDiscoverySimulationRegistryPort,
    SystemDiscoveryTrainingRegistryPort,
)


INSERT_TRAINING_SQL = """
    INSERT INTO system_discovery.training (
        training_id,
        created_at,
        updated_at,
        state,
        raw_status,
        training_status,
        evaluation_status,
        error,
        basis,
        degree,
        model,
        nlags_x,
        nlags_y,
        results_archive_path,
        results_cached_at,
        results_cache_error,
        finished_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
"""

SELECT_TRAINING_SQL = """
    SELECT
        training_id,
        created_at,
        updated_at,
        state,
        raw_status,
        training_status,
        evaluation_status,
        error,
        basis,
        degree,
        model,
        nlags_x,
        nlags_y,
        results_archive_path,
        results_cached_at,
        results_cache_error,
        finished_at
    FROM system_discovery.training
    WHERE training_id = %s AND archived_at IS NULL
"""

LIST_TRAININGS_SQL = """
    SELECT
        training_id,
        created_at,
        updated_at,
        state,
        raw_status,
        training_status,
        evaluation_status,
        error,
        basis,
        degree,
        model,
        nlags_x,
        nlags_y,
        results_archive_path,
        results_cached_at,
        results_cache_error,
        finished_at
    FROM system_discovery.training
    WHERE archived_at IS NULL
    ORDER BY created_at DESC, training_id DESC
"""

UPDATE_TRAINING_SQL = """
    UPDATE system_discovery.training
    SET
        state = %s,
        raw_status = %s,
        training_status = %s,
        evaluation_status = %s,
        error = %s,
        updated_at = %s,
        finished_at = CASE
            WHEN %s THEN COALESCE(finished_at, %s)
            ELSE finished_at
        END
    WHERE training_id = %s
    RETURNING
        training_id,
        created_at,
        updated_at,
        state,
        raw_status,
        training_status,
        evaluation_status,
        error,
        basis,
        degree,
        model,
        nlags_x,
        nlags_y,
        results_archive_path,
        results_cached_at,
        results_cache_error,
        finished_at
"""

ARCHIVE_TRAINING_SQL = """
    UPDATE system_discovery.training
    SET archived_at = %s
    WHERE training_id = %s
"""

INSERT_SAVED_MODEL_SQL = """
    INSERT INTO system_discovery.saved_model (
        model_id,
        source_training_id,
        model_name,
        saved_at,
        nlags_x,
        nlags_y,
        basis,
        degree
    )
    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
    ON CONFLICT (model_id) DO NOTHING
"""

SELECT_SAVED_MODEL_COLUMNS = """
    model_id,
    source_training_id,
    model_name,
    saved_at,
    nlags_x,
    nlags_y,
    basis,
    degree
"""

SELECT_SAVED_MODEL_SQL = f"""
    SELECT {SELECT_SAVED_MODEL_COLUMNS}
    FROM system_discovery.saved_model
    WHERE model_id = %s
"""

SELECT_SAVED_MODEL_BY_TRAINING_SQL = f"""
    SELECT {SELECT_SAVED_MODEL_COLUMNS}
    FROM system_discovery.saved_model
    WHERE source_training_id = %s
"""

LIST_SAVED_MODELS_SQL = f"""
    SELECT {SELECT_SAVED_MODEL_COLUMNS}
    FROM system_discovery.saved_model
    ORDER BY saved_at DESC, model_id DESC
"""

REMOVE_SAVED_MODEL_SQL = """
    DELETE FROM system_discovery.saved_model
    WHERE model_id = %s
"""

UPDATE_TRAINING_RESULTS_CACHE_SQL = """
    UPDATE system_discovery.training
    SET
        results_archive_path = %s,
        results_cached_at = %s,
        results_cache_error = %s
    WHERE training_id = %s
    RETURNING
        training_id,
        created_at,
        updated_at,
        state,
        raw_status,
        training_status,
        evaluation_status,
        error,
        basis,
        degree,
        model,
        nlags_x,
        nlags_y,
        results_archive_path,
        results_cached_at,
        results_cache_error,
        finished_at
"""

INSERT_SIMULATION_SQL = """
    INSERT INTO system_discovery.simulation (
        simulation_id,
        source_model_id,
        source_model_name,
        created_at,
        updated_at,
        state,
        raw_status,
        error,
        horizon,
        initial_conditions,
        uses_external_control_signals,
        aistor_object_key,
        aistor_uploaded_at,
        aistor_upload_error,
        visualization_plot_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
"""

SELECT_SIMULATION_COLUMNS = """
    simulation_id,
    source_model_id,
    source_model_name,
    created_at,
    updated_at,
    state,
    raw_status,
    error,
    horizon,
    initial_conditions,
    uses_external_control_signals,
    aistor_object_key,
    aistor_uploaded_at,
    aistor_upload_error,
    visualization_plot_id
"""

SELECT_SIMULATION_SQL = f"""
    SELECT {SELECT_SIMULATION_COLUMNS}
    FROM system_discovery.simulation
    WHERE simulation_id = %s
"""

LIST_SIMULATIONS_SQL = f"""
    SELECT {SELECT_SIMULATION_COLUMNS}
    FROM system_discovery.simulation
    ORDER BY created_at DESC, simulation_id DESC
"""

UPDATE_SIMULATION_STATUS_SQL = f"""
    UPDATE system_discovery.simulation
    SET state = %s, raw_status = %s, error = %s, updated_at = %s
    WHERE simulation_id = %s
    RETURNING {SELECT_SIMULATION_COLUMNS}
"""

UPDATE_SIMULATION_AISTOR_SQL = f"""
    UPDATE system_discovery.simulation
    SET aistor_object_key = %s, aistor_uploaded_at = %s, aistor_upload_error = %s
    WHERE simulation_id = %s
    RETURNING {SELECT_SIMULATION_COLUMNS}
"""

UPDATE_SIMULATION_VISUALIZATION_SQL = f"""
    UPDATE system_discovery.simulation
    SET visualization_plot_id = %s
    WHERE simulation_id = %s
    RETURNING {SELECT_SIMULATION_COLUMNS}
"""


class PostgresSystemDiscoveryTrainingRegistry(SystemDiscoveryTrainingRegistryPort):
    def __init__(self, dsn: str) -> None:
        normalized_dsn = dsn.strip()
        if not normalized_dsn:
            raise RuntimeError("Missing PostgreSQL DSN for System Discovery training registry")
        self._dsn = normalized_dsn

    def register_training(self, record: SystemDiscoveryTrainingRecord) -> None:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        INSERT_TRAINING_SQL,
                        (
                            record.training_id,
                            record.created_at,
                            record.updated_at,
                            record.state.value,
                            record.raw_status,
                            record.training_status,
                            record.evaluation_status,
                            record.error,
                            record.basis,
                            record.degree,
                            record.model,
                            _json_nlags_x(record.nlags_x),
                            record.nlags_y,
                            record.results_archive_path,
                            record.results_cached_at,
                            record.results_cache_error,
                            record.finished_at,
                        ),
                    )
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to register System Discovery training '{record.training_id}' in PostgreSQL: {exc}"
            ) from exc

    def get_training(self, training_id: str) -> SystemDiscoveryTrainingRecord | None:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(SELECT_TRAINING_SQL, (training_id,))
                    row = cursor.fetchone()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to read System Discovery training '{training_id}' from PostgreSQL: {exc}"
            ) from exc
        if row is None:
            return None
        return _record_from_row(row)

    def list_trainings(self) -> list[SystemDiscoveryTrainingRecord]:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(LIST_TRAININGS_SQL)
                    rows = cursor.fetchall()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to list System Discovery trainings from PostgreSQL: {exc}"
            ) from exc
        return [_record_from_row(row) for row in rows]

    def update_training_status(
        self,
        training_id: str,
        *,
        state: SystemDiscoveryTrainingState,
        raw_status: str,
        training_status: str | None,
        evaluation_status: str | None,
        error: str | None,
        updated_at: datetime,
    ) -> SystemDiscoveryTrainingRecord:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        UPDATE_TRAINING_SQL,
                        (
                            state.value,
                            raw_status,
                            training_status,
                            evaluation_status,
                            error,
                            updated_at,
                            state
                            in {
                                SystemDiscoveryTrainingState.COMPLETED,
                                SystemDiscoveryTrainingState.FAILED,
                            },
                            updated_at,
                            training_id,
                        ),
                    )
                    row = cursor.fetchone()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to update System Discovery training '{training_id}' in PostgreSQL: {exc}"
            ) from exc
        if row is None:
            raise RuntimeError(
                f"System Discovery training '{training_id}' was not found in PostgreSQL"
            )
        return _record_from_row(row)

    def update_training_results_cache(
        self,
        training_id: str,
        *,
        results_archive_path: str | None,
        results_cached_at: datetime | None,
        results_cache_error: str | None,
    ) -> SystemDiscoveryTrainingRecord:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        UPDATE_TRAINING_RESULTS_CACHE_SQL,
                        (
                            results_archive_path,
                            results_cached_at,
                            results_cache_error,
                            training_id,
                        ),
                    )
                    row = cursor.fetchone()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to update System Discovery training '{training_id}' results cache in PostgreSQL: {exc}"
            ) from exc
        if row is None:
            raise RuntimeError(
                f"System Discovery training '{training_id}' was not found in PostgreSQL"
            )
        return _record_from_row(row)

    def archive_training(self, training_id: str, *, archived_at: datetime) -> None:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(ARCHIVE_TRAINING_SQL, (archived_at, training_id))
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to archive System Discovery training '{training_id}' in PostgreSQL: {exc}"
            ) from exc


class PostgresSystemDiscoverySavedModelRegistry(
    SystemDiscoverySavedModelRegistryPort
):
    def __init__(self, dsn: str) -> None:
        normalized_dsn = dsn.strip()
        if not normalized_dsn:
            raise RuntimeError("Missing PostgreSQL DSN for System Discovery saved model registry")
        self._dsn = normalized_dsn

    def save_model(self, record: SystemDiscoverySavedModelRecord) -> None:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        INSERT_SAVED_MODEL_SQL,
                        (
                            record.model_id,
                            record.source_training_id,
                            record.model_name,
                            record.saved_at,
                            _json_nlags_x(record.nlags_x),
                            record.nlags_y,
                            record.basis,
                            record.degree,
                        ),
                    )
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to save System Discovery model '{record.model_id}' in PostgreSQL: {exc}"
            ) from exc

    def get_model(self, model_id: str) -> SystemDiscoverySavedModelRecord | None:
        return self._fetch_one(SELECT_SAVED_MODEL_SQL, model_id)

    def get_model_by_source_training_id(
        self,
        training_id: str,
    ) -> SystemDiscoverySavedModelRecord | None:
        return self._fetch_one(SELECT_SAVED_MODEL_BY_TRAINING_SQL, training_id)

    def list_models(self) -> list[SystemDiscoverySavedModelRecord]:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(LIST_SAVED_MODELS_SQL)
                    rows = cursor.fetchall()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to list System Discovery saved models from PostgreSQL: {exc}"
            ) from exc
        return [_saved_model_from_row(row) for row in rows]

    def remove_model(self, model_id: str) -> None:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(REMOVE_SAVED_MODEL_SQL, (model_id,))
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to remove System Discovery saved model '{model_id}' from PostgreSQL: {exc}"
            ) from exc

    def _fetch_one(
        self,
        query: str,
        value: str,
    ) -> SystemDiscoverySavedModelRecord | None:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(query, (value,))
                    row = cursor.fetchone()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to read System Discovery saved model from PostgreSQL: {exc}"
            ) from exc
        if row is None:
            return None
        return _saved_model_from_row(row)


class PostgresSystemDiscoverySimulationRegistry(SystemDiscoverySimulationRegistryPort):
    def __init__(self, dsn: str) -> None:
        normalized_dsn = dsn.strip()
        if not normalized_dsn:
            raise RuntimeError("Missing PostgreSQL DSN for System Discovery simulation registry")
        self._dsn = normalized_dsn

    def register_simulation(self, record: SystemDiscoverySimulationRecord) -> None:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        INSERT_SIMULATION_SQL,
                        (
                            record.simulation_id,
                            record.source_model_id,
                            record.source_model_name,
                            record.created_at,
                            record.updated_at,
                            record.state.value,
                            record.raw_status,
                            record.error,
                            record.horizon,
                            _json_initial_conditions(record.initial_conditions),
                            record.uses_external_control_signals,
                            record.aistor_object_key,
                            record.aistor_uploaded_at,
                            record.aistor_upload_error,
                            record.visualization_plot_id,
                        ),
                    )
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to register System Discovery simulation '{record.simulation_id}' in PostgreSQL: {exc}"
            ) from exc

    def get_simulation(self, simulation_id: str) -> SystemDiscoverySimulationRecord | None:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(SELECT_SIMULATION_SQL, (simulation_id,))
                    row = cursor.fetchone()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to read System Discovery simulation '{simulation_id}' from PostgreSQL: {exc}"
            ) from exc
        return None if row is None else _simulation_from_row(row)

    def list_simulations(self) -> list[SystemDiscoverySimulationRecord]:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(LIST_SIMULATIONS_SQL)
                    rows = cursor.fetchall()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to list System Discovery simulations from PostgreSQL: {exc}"
            ) from exc
        return [_simulation_from_row(row) for row in rows]

    def update_simulation_status(
        self,
        simulation_id: str,
        *,
        state: SystemDiscoverySimulationState,
        raw_status: str,
        error: str | None,
        updated_at: datetime,
    ) -> SystemDiscoverySimulationRecord:
        return self._update_one(
            UPDATE_SIMULATION_STATUS_SQL,
            (state.value, raw_status, error, updated_at, simulation_id),
            simulation_id,
        )

    def update_simulation_aistor_result(
        self,
        simulation_id: str,
        *,
        aistor_object_key: str | None,
        aistor_uploaded_at: datetime | None,
        aistor_upload_error: str | None,
    ) -> SystemDiscoverySimulationRecord:
        return self._update_one(
            UPDATE_SIMULATION_AISTOR_SQL,
            (
                aistor_object_key,
                aistor_uploaded_at,
                aistor_upload_error,
                simulation_id,
            ),
            simulation_id,
        )

    def update_simulation_visualization(
        self,
        simulation_id: str,
        *,
        visualization_plot_id: str | None,
    ) -> SystemDiscoverySimulationRecord:
        return self._update_one(
            UPDATE_SIMULATION_VISUALIZATION_SQL,
            (visualization_plot_id, simulation_id),
            simulation_id,
        )

    def _update_one(
        self,
        query: str,
        params: tuple[Any, ...],
        simulation_id: str,
    ) -> SystemDiscoverySimulationRecord:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(query, params)
                    row = cursor.fetchone()
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Failed to update System Discovery simulation '{simulation_id}' in PostgreSQL: {exc}"
            ) from exc
        if row is None:
            raise RuntimeError(
                f"System Discovery simulation '{simulation_id}' was not found in PostgreSQL"
            )
        return _simulation_from_row(row)


def _record_from_row(row: tuple[Any, ...]) -> SystemDiscoveryTrainingRecord:
    if len(row) == 16:
        row = (*row, None)
    (
        training_id,
        created_at,
        updated_at,
        state,
        raw_status,
        training_status,
        evaluation_status,
        error,
        basis,
        degree,
        model,
        nlags_x,
        nlags_y,
        results_archive_path,
        results_cached_at,
        results_cache_error,
        finished_at,
    ) = row
    parsed_nlags_x = nlags_x
    if isinstance(parsed_nlags_x, str):
        parsed_nlags_x = json.loads(parsed_nlags_x)
    return SystemDiscoveryTrainingRecord(
        training_id=str(training_id),
        created_at=created_at,
        updated_at=updated_at,
        state=SystemDiscoveryTrainingState(str(state)),
        raw_status=str(raw_status),
        training_status=None if training_status is None else str(training_status),
        evaluation_status=None if evaluation_status is None else str(evaluation_status),
        error=None if error is None else str(error),
        basis=str(basis),
        degree=int(degree),
        model=str(model),
        nlags_x=_parse_nlags_x(parsed_nlags_x),
        nlags_y=int(nlags_y),
        results_archive_path=(
            None if results_archive_path is None else str(results_archive_path)
        ),
        results_cached_at=results_cached_at,
        results_cache_error=(
            None if results_cache_error is None else str(results_cache_error)
        ),
        finished_at=finished_at,
    )


def _saved_model_from_row(row: tuple[Any, ...]) -> SystemDiscoverySavedModelRecord:
    (
        model_id,
        source_training_id,
        model_name,
        saved_at,
        nlags_x,
        nlags_y,
        basis,
        degree,
    ) = row
    parsed_nlags_x = nlags_x
    if isinstance(parsed_nlags_x, str):
        parsed_nlags_x = json.loads(parsed_nlags_x)
    return SystemDiscoverySavedModelRecord(
        model_id=str(model_id),
        source_training_id=str(source_training_id),
        model_name=str(model_name),
        saved_at=saved_at,
        nlags_x=_parse_nlags_x(parsed_nlags_x),
        nlags_y=int(nlags_y),
        basis=str(basis),
        degree=int(degree),
    )


def _simulation_from_row(row: tuple[Any, ...]) -> SystemDiscoverySimulationRecord:
    (
        simulation_id,
        source_model_id,
        source_model_name,
        created_at,
        updated_at,
        state,
        raw_status,
        error,
        horizon,
        initial_conditions,
        uses_external_control_signals,
        aistor_object_key,
        aistor_uploaded_at,
        aistor_upload_error,
        visualization_plot_id,
    ) = row
    parsed_initial_conditions = initial_conditions
    if isinstance(parsed_initial_conditions, str):
        parsed_initial_conditions = json.loads(parsed_initial_conditions)
    return SystemDiscoverySimulationRecord(
        simulation_id=str(simulation_id),
        source_model_id=str(source_model_id),
        source_model_name=str(source_model_name),
        created_at=created_at,
        updated_at=updated_at,
        state=SystemDiscoverySimulationState(str(state)),
        raw_status=str(raw_status),
        error=None if error is None else str(error),
        horizon=None if horizon is None else int(horizon),
        initial_conditions=(
            None
            if parsed_initial_conditions is None
            else tuple(float(value) for value in parsed_initial_conditions)
        ),
        uses_external_control_signals=bool(uses_external_control_signals),
        aistor_object_key=None if aistor_object_key is None else str(aistor_object_key),
        aistor_uploaded_at=aistor_uploaded_at,
        aistor_upload_error=(
            None if aistor_upload_error is None else str(aistor_upload_error)
        ),
        visualization_plot_id=(
            None if visualization_plot_id is None else str(visualization_plot_id)
        ),
    )


def _json_initial_conditions(values: tuple[float, ...] | None) -> str | None:
    if values is None:
        return None
    return json.dumps(list(values))


def _json_nlags_x(values: tuple[tuple[int, ...], ...] | None) -> str:
    if values is None:
        return "null"
    return json.dumps([list(row) for row in values])


def _parse_nlags_x(value: Any) -> tuple[tuple[int, ...], ...] | None:
    if value is None:
        return None
    return tuple(tuple(int(item) for item in row) for row in value)
