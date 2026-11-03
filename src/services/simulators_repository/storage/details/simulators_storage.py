import json
from types import SimpleNamespace

import psycopg
from psycopg.rows import dict_row
from psycopg.sql import SQL, Identifier
from psycopg.types.json import Json
from datetime import datetime

from services.simulators_repository.core.abstract_simulators_storage import AbstractSimulatorsStorage\
    , SimulatorEntry

from services.simulators_repository.core.abstract_simulators_storage import SimulatorSummary

class SimulatorsStorage(AbstractSimulatorsStorage):
    def __init__(self, config) -> None:
        self._config = SimpleNamespace(**config)
        self._dsn = _config_value(getattr(self._config, "dsn", None))
        self._conn_kwargs = self._build_conn_kwargs()
        self._ensure_schema()

    def get_latest_simulator_by_model_name(self, model_name: str) -> SimulatorEntry | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT simulator_id,
                           model_name,
                           version,
                           image_reference_url,
                           image_digest,
                           image_tags
                    FROM simulators.simulator
                    WHERE model_name = %s
                    ORDER BY simulator_id DESC
                    LIMIT 1
                    """,
                    (model_name,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                simulator_id = row["simulator_id"]

                # Deterministic selection rule: choose latest by simulator_id.
                cur.execute(
                    """
                    SELECT direction, name, ptype
                    FROM simulators.param_def
                    WHERE simulator_id = %s
                    ORDER BY direction, ordinal, name
                    """,
                    (simulator_id,),
                )
                params = cur.fetchall()

        input_params = []
        output_params = []
        for item in params:
            direction = item["direction"]
            pair = (item["name"], item["ptype"])
            if direction == "input":
                input_params.append(pair)
            elif direction == "output":
                output_params.append(pair)

        return SimulatorEntry(
            simulator_id=simulator_id,
            model_name=row["model_name"],
            version=row["version"],
            image_reference_url=row["image_reference_url"],
            image_digest=row["image_digest"],
            image_tags=_string_list(row["image_tags"]),
            input_params=input_params,
            output_params=output_params,
        )


    def get_simulator(self, model_id: str) -> SimulatorEntry | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT simulator_id,
                           model_name,
                           version,
                           image_reference_url,
                           image_digest,
                           image_tags
                    FROM simulators.simulator
                    WHERE simulator_id = %s
                    ORDER BY simulator_id DESC
                    LIMIT 1
                    """,
                    (model_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                simulator_id = row["simulator_id"]

                # Deterministic selection rule: choose latest by simulator_id.
                cur.execute(
                    """
                    SELECT direction, name, ptype
                    FROM simulators.param_def
                    WHERE simulator_id = %s
                    ORDER BY direction, ordinal, name
                    """,
                    (simulator_id,),
                )
                params = cur.fetchall()

        input_params = []
        output_params = []
        for item in params:
            direction = item["direction"]
            pair = (item["name"], item["ptype"])
            if direction == "input":
                input_params.append(pair)
            elif direction == "output":
                output_params.append(pair)

        return SimulatorEntry(
            simulator_id=simulator_id,
            model_name=row["model_name"],
            version=row["version"],
            image_reference_url=row["image_reference_url"],
            image_digest=row["image_digest"],
            image_tags=_string_list(row["image_tags"]),
            input_params=input_params,
            output_params=output_params,
        )

    def insert(self, entry: SimulatorEntry) -> None:
        input_pairs = _pair_list(entry.input_params)
        output_pairs = _pair_list(entry.output_params)
        _validate_param_types("input", input_pairs)
        _validate_param_types("output", output_pairs)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO simulators.simulator (
                        model_name,
                        version,
                        image_reference_url,
                        image_digest,
                        image_tags
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (model_name, version) DO UPDATE SET
                        version = EXCLUDED.version,
                        image_reference_url = EXCLUDED.image_reference_url,
                        image_digest = EXCLUDED.image_digest,
                        image_tags = EXCLUDED.image_tags
                    RETURNING simulator_id
                    """,
                    (
                        entry.model_name,
                        entry.version,
                        entry.image_reference_url,
                        entry.image_digest,
                        Json(_string_list(entry.image_tags)),
                    ),
                )
                simulator_id = cur.fetchone()[0]
                self._upsert_params(cur, simulator_id, "input", input_pairs)
                self._upsert_params(cur, simulator_id, "output", output_pairs)

    def update_simulator(self, model_name: str, key: str, value: object) -> None:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("key must be a non-empty string")
        allowed = {
            "model_name",
            "version",
            "image_reference_url",
            "image_digest",
            "image_tags",
            "input_params",
            "output_params",
        }
        if key not in allowed:
            raise ValueError(f"Unknown simulator field: {key}")

        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT simulator_id
                    FROM simulators.simulator
                    WHERE model_name = %s
                    ORDER BY simulator_id DESC
                    LIMIT 1
                    """,
                    (model_name,),
                )
                row = cur.fetchone()
                if row is None:
                    # No-op when simulator is not found.
                    return
                simulator_id = row["simulator_id"]

                if key in ("input_params", "output_params"):
                    direction = "input" if key == "input_params" else "output"
                    pairs = _pair_list(value)
                    _validate_param_types(direction, pairs)
                    self._upsert_params(cur, simulator_id, direction, pairs)
                    return

                value_payload = value
                if key == "image_tags":
                    value_payload = Json(_string_list(value))

                cur.execute(
                    SQL("UPDATE simulators.simulator SET {} = %s WHERE simulator_id = %s").format(
                        Identifier(key)
                    ),
                    (value_payload, simulator_id),
                )

    def delete_simulator(self, model_name: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM simulators.simulator WHERE model_name = %s",
                    (model_name,),
                )
                return cur.rowcount > 0

    def list_simulator_names(self) -> list[str]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT model_name FROM simulators.simulator ORDER BY model_name"
                )
                return [row[0] for row in cur.fetchall()]

    def list_simulators_ids(self) -> list[str]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT simulator_id FROM simulators.simulator"
                )
                return [row[0] for row in cur.fetchall()]

    def get_simulators_summaries(self) -> list[SimulatorSummary]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT simulator_id, model_name, version
                    FROM simulators.simulator
                    ORDER BY simulator_id ASC
                    """
                )
                return [
                    SimulatorSummary(
                        simulator_id=str(simulator_id),
                        model_name=model_name,
                        version=version,
                        created_at=datetime(2000, 1, 1),
                    )
                    for simulator_id, model_name, version in cur.fetchall()
                ]


    def _build_conn_kwargs(self) -> dict:
        if self._dsn:
            return {}
        host = _config_value(getattr(self._config, "host", None))
        port = _config_value(getattr(self._config, "port", None))
        dbname = _config_value(getattr(self._config, "dbname", None))
        user = _config_value(getattr(self._config, "user", None))
        password = _config_value(getattr(self._config, "password", None))
        kwargs = {}
        if host:
            kwargs["host"] = host
        if port:
            kwargs["port"] = port
        if dbname:
            kwargs["dbname"] = dbname
        if user:
            kwargs["user"] = user
        if password:
            kwargs["password"] = password
        return kwargs

    def _connect(self):
        if self._dsn:
            return psycopg.connect(self._dsn)
        return psycopg.connect(**self._conn_kwargs)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT to_regclass('simulators.simulator') AS simulator,
                           to_regclass('simulators.param_def') AS param_def
                    """
                )
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError(
                        "Required tables are missing: simulators.simulator or simulators.param_def"
                    )
                sim_tbl, param_tbl = row
                if sim_tbl is None or param_tbl is None:
                    raise RuntimeError(
                        "Required tables are missing: simulators.simulator or simulators.param_def"
                    )

    def _upsert_params(
        self, cur, simulator_id: int, direction: str, pairs: list[tuple[str, str]]
    ) -> None:
        names = []
        for idx, (name, ptype) in enumerate(pairs, start=1):
            names.append(name)
            cur.execute(
                """
                INSERT INTO simulators.param_def (
                    simulator_id,
                    direction,
                    name,
                    ptype,
                    required,
                    ordinal
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (simulator_id, direction, name)
                DO UPDATE SET
                    ptype = EXCLUDED.ptype,
                    required = EXCLUDED.required,
                    ordinal = EXCLUDED.ordinal
                """,
                (simulator_id, direction, name, ptype, True, idx),
            )

        if not names:
            cur.execute(
                """
                DELETE FROM simulators.param_def
                WHERE simulator_id = %s AND direction = %s
                """,
                (simulator_id, direction),
            )
            return

        # Use ANY to delete rows not present in the new list.
        cur.execute(
            """
            DELETE FROM simulators.param_def
            WHERE simulator_id = %s AND direction = %s AND NOT (name = ANY(%s))
            """,
            (simulator_id, direction, names),
        )


def _pair_list(value: object) -> list[tuple[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected a list of (name, type) pairs")
    pairs = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("expected a list of (name, type) pairs")
        name, typ = item
        if not isinstance(name, str) or not isinstance(typ, str):
            raise ValueError("parameter name and type must be strings")
        pairs.append((name, typ))
    return pairs


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("expected a JSON array of strings") from exc
    if not isinstance(value, list):
        raise ValueError("expected a list of strings")
    items = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("expected a list of strings")
        items.append(item)
    return items


def _config_value(value):
    return value() if callable(value) else value


def _validate_param_types(direction: str, pairs: list[tuple[str, str]]) -> None:
    if direction not in ("input", "output"):
        raise ValueError("direction must be 'input' or 'output'")
    input_allowed = {"int", "float", "str", "bool"}
    output_allowed = {
        "int",
        "float",
        "str",
        "bool",
        "int_ts",
        "float_ts",
        "str_ts",
        "bool_ts",
    }
    allowed = input_allowed if direction == "input" else output_allowed
    for name, typ in pairs:
        if typ not in allowed:
            raise ValueError(
                f"Invalid param type for {direction} '{name}': {typ}. "
                f"Allowed: {sorted(allowed)}"
            )


def createStorage(config) -> AbstractSimulatorsStorage:
    return SimulatorsStorage(config)
