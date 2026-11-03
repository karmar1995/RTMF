from __future__ import annotations

import io
import json
import stat
import zipfile

from use_case_contracts.dtos import (
    BuildSpec,
    ParamType,
    ParameterSpec,
)

_INITIAL_CONDITIONS_FILE = "initial_conditions.json"
_WRAPPER_ENTRYPOINT = "run.py"
_START_SIM_SHIM = "start_sim.sh"
_START_SIM_CONTENT = (
    "#!/bin/bash\n"
    "set -e\n\n"
    'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
    'export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"\n\n'
    'source "$SCRIPT_DIR/.venv/bin/activate"\n'
    'python3 "$SCRIPT_DIR/run.py" "$1" "$2"\n'
)


class InvalidSystemDiscoverySimulatorArchiveError(ValueError):
    """Raised when a saved System Discovery model workspace cannot be turned
    into a registered simulator artifact."""


def build_simulator_input_params(
    ic_dimension: int,
    *,
    include_horizon: bool = True,
) -> list[ParameterSpec]:
    """Flatten the initial-conditions vector into per-element scalar inputs.

    The standard simulator run pipeline exposes each input parameter as a
    scalar matrix parameter. A System Discovery model's initial conditions are
    a vector, so we expand them into ``ic_0`` .. ``ic_{N-1}`` scalar float
    inputs (optionally plus a ``horizon`` input) so they can be fixed and swept
    individually.
    """
    if ic_dimension < 1:
        raise InvalidSystemDiscoverySimulatorArchiveError(
            "System Discovery model has no initial conditions; cannot register simulator."
        )
    params = [
        ParameterSpec(name=f"ic_{index}", type=ParamType.FLOAT)
        for index in range(ic_dimension)
    ]
    if include_horizon:
        params.append(ParameterSpec(name="horizon", type=ParamType.INT))
    return params


def build_simulator_output_params() -> list[ParameterSpec]:
    """Outputs of a registered System Discovery simulator.

    Only the simulated output (the per-repetition time series) is exposed.
    """
    return [ParameterSpec(name="output", type=ParamType.FLOAT_TS)]


def build_build_spec() -> BuildSpec:
    """Build the Dockerfile configuration the Simulators Repository expects.

    ``DockerfileDirector`` only supports the ``python`` technology on
    linux/amd64 with a ``major.minor`` Python version, and unpacks the model
    zip into ``/opt/simulator``. A System Discovery ``.syspy`` artifact is a
    pickled ``sysidentpy`` model, so the container runtime needs ``sysidentpy``
    installed to unpickle and simulate it.
    """
    return BuildSpec(
        spec={
            "platform": {"os": "linux", "arch": "amd64"},
            "technology": {
                "type": "python",
                "python": {
                    "version": "3.11",
                    "packages": [{"name": "sysidentpy"}],
                },
            },
        }
    )


def build_wrapper_archive(
    workspace_archive: bytes,
    ic_dimension: int,
) -> bytes:
    """Turn a saved System Discovery model's workspace archive into a
    self-contained, runnable simulator zip.

    The returned zip contains:
      * ``start_sim.sh`` -- the shell entrypoint expected by the Slurm subjob
        runtime at ``/opt/simulator/start_sim.sh``. It activates the venv and
        delegates to ``run.py`` with the same args.
      * ``run.py`` -- the Python entrypoint conforming to the subjob contract
        ``run.py <matrix_path> <row_number>``.
      * the trained model artifacts (``*.syspy``) and ``initial_conditions.json``
        extracted from the workspace archive, so the model can be executed
        locally.
    """
    model_members = _extract_model_artifacts(workspace_archive)
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as target:
            shim_info = zipfile.ZipInfo(_START_SIM_SHIM)
            shim_info.external_attr = (stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO) << 16
            target.writestr(shim_info, _START_SIM_CONTENT)
            target.writestr(_WRAPPER_ENTRYPOINT, _render_entrypoint(ic_dimension))
            for name, content in model_members.items():
                target.writestr(name, content)
        return buffer.getvalue()


def _extract_model_artifacts(workspace_archive: bytes) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(workspace_archive), mode="r") as source:
            for info in source.infolist():
                if info.is_dir():
                    continue
                basename = info.filename.rsplit("/", 1)[-1]
                if not basename.endswith(".syspy") and basename != _INITIAL_CONDITIONS_FILE:
                    continue
                members[basename] = source.read(info.filename)
    except zipfile.BadZipFile as exc:
        raise InvalidSystemDiscoverySimulatorArchiveError(
            "Saved System Discovery model workspace is not a valid ZIP archive."
        ) from exc

    if not any(name.endswith(".syspy") for name in members):
        raise InvalidSystemDiscoverySimulatorArchiveError(
            "Saved System Discovery model workspace has no trained model artifact."
        )
    return members


def derive_ic_dimension(
    workspace_archive: bytes,
    *,
    fallback_dimension: int | None = None,
) -> int:
    """Return the number of scalar initial-condition inputs the registered
    simulator should expose.

    Prefer the ``initial_conditions.json`` embedded in the saved model
    workspace; when the archive does not carry one, use ``fallback_dimension``.
    The fallback is the persisted ``nlags_y`` of the trained model (the size of
    the output lag window that seeds the free-run simulation); the actual
    initial-condition *values* are supplied per-run at simulation time.
    """
    members = _extract_model_artifacts(workspace_archive)
    if _INITIAL_CONDITIONS_FILE in members:
        try:
            labels = _parse_initial_conditions(members[_INITIAL_CONDITIONS_FILE])
        except (ValueError, TypeError) as exc:
            raise InvalidSystemDiscoverySimulatorArchiveError(
                "Saved System Discovery model initial conditions are ill-formed."
            ) from exc
        if not labels:
            raise InvalidSystemDiscoverySimulatorArchiveError(
                "System Discovery model has empty initial conditions."
            )
        return len(labels)
    if fallback_dimension is not None:
        if fallback_dimension < 1:
            raise InvalidSystemDiscoverySimulatorArchiveError(
                "Saved System Discovery model reports an invalid lag window."
            )
        return fallback_dimension
    raise InvalidSystemDiscoverySimulatorArchiveError(
        "Saved System Discovery model workspace has no initial conditions "
        "and no fallback dimension was supplied."
    )


def _parse_initial_conditions(raw: bytes) -> list[int]:
    text = raw.decode("utf-8", errors="ignore")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # The storage normalizes initial conditions to a space separated string;
        # accept either a JSON list or the raw numeric sequence.
        return [int(part) for part in text.split()]
    if isinstance(payload, (list, tuple)):
        return [int(part) for part in payload]
    if isinstance(payload, str):
        return [int(part) for part in payload.split()]
    raise ValueError("initial conditions payload must be a list or numeric string")


def _render_entrypoint(ic_dimension: int) -> str:
    """Render the ``run.py`` that the registered simulator container executes.

    Contract (see SubprocessSimulator): invoked as ``run.py <matrix> <row>``.
    It reads the requested matrix row, reassembles the flattened ``ic_*`` /
    ``horizon`` inputs into initial conditions for the bundled ``.syspy``
    model, runs a free-run simulation with ``sysidentpy`` and writes the
    simulated output as ``results/results.csv`` plus one timeseries CSV per
    repetition.
    """
    return f'''#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import sysidentpy  # noqa: F401  (keeps the pickled model importable)

IC_DIMENSION = {ic_dimension}


class SimulatorError(RuntimeError):
    pass


def _load_matrix(content: bytes):
    lines = []
    for raw in content.decode("utf-8", errors="strict").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    repetitions = int(lines[0])
    rows = [line.split() for line in lines[1:]]
    return repetitions, rows


def _parse_initial_conditions(text: str):
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = text
    if isinstance(payload, str):
        values = payload.split()
    elif isinstance(payload, (list, tuple)):
        values = payload
    else:
        values = text.split()
    return [float(value) for value in values]


def _load_model(artifacts_dir: Path):
    candidates = [name for name in os.listdir(artifacts_dir) if name.endswith(".syspy")]
    if not candidates:
        raise SimulatorError("no .syspy model artifact found in simulator")
    with (artifacts_dir / candidates[0]).open("rb") as handle:
        return pickle.load(handle)


def _build_seed_conditions(ic_values, default_ic, max_lag):
    sequence = [float(value) for value in ic_values]
    if len(sequence) < max_lag and default_ic:
        sequence = list(default_ic) + sequence
    if len(sequence) < max_lag:
        if not sequence:
            raise SimulatorError(
                "not enough initial conditions to start the model simulation"
            )
        sequence = [sequence[-1]] * (max_lag - len(sequence)) + sequence
    return sequence[-max_lag:]


def _run_model(*, artifacts_dir, model_artifacts, initial_conditions, default_ic, horizon, timeseries_path):
    model = _load_model(artifacts_dir)
    model_type = str(getattr(model, "model_type", "NAR") or "NAR")
    max_lag = int(getattr(model, "max_lag", 1) or 1)
    if max_lag < 1:
        raise SimulatorError("model reports an invalid lag window")

    seed = np.asarray(
        _build_seed_conditions(initial_conditions, default_ic, max_lag),
        dtype=float,
    ).reshape(-1, 1)

    if model_type == "NAR":
        model_input = None
    else:
        n_inputs = int(getattr(model, "n_inputs", None) or 1)
        model_input = np.zeros((max_lag + horizon, n_inputs), dtype=float)

    predicted = np.asarray(
        model.predict(X=model_input, y=seed, forecast_horizon=horizon),
        dtype=float,
    )
    output_values = predicted[-horizon:].ravel()

    with timeseries_path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["time", "output"])
        for index, value in enumerate(output_values):
            writer.writerow([index, float(value)])


def _main(argv):
    if len(argv) < 2:
        print("usage: run.py <matrix_file> <row_number>", file=sys.stderr)
        return 2
    matrix_file = argv[1]
    row_index = int(argv[2])

    with open(matrix_file, "rb") as handle:
        content = handle.read()
    repetitions, rows = _load_matrix(content)
    if row_index < 0 or row_index >= len(rows):
        raise SimulatorError(f"matrix row {{row_index}} is out of range")
    params = rows[row_index]

    ic_values = tuple(float(part) for part in params[:IC_DIMENSION])
    if len(params) <= IC_DIMENSION:
        raise SimulatorError("matrix row is missing the horizon input")
    horizon = int(params[IC_DIMENSION])
    if horizon < 1:
        raise SimulatorError("horizon must be a positive integer")

    workdir = Path.cwd()
    sim_dir = Path(__file__).parent
    initial_conditions_file = sim_dir / "initial_conditions.json"
    default_ic = None
    if initial_conditions_file.exists():
        default_ic = _parse_initial_conditions(initial_conditions_file.read_text())

    results_dir = workdir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    input_names = [f"ic_{{index}}" for index in range(IC_DIMENSION)] + ["horizon"]
    input_values = [str(value) for value in ic_values] + [str(horizon)]

    summary = []
    for repetition in range(repetitions):
        timeseries_path = results_dir / f"results_{{repetition}}.csv"
        _run_model(
            artifacts_dir=sim_dir,
            model_artifacts=[name for name in os.listdir(sim_dir) if name.endswith(".syspy")],
            initial_conditions=ic_values,
            default_ic=default_ic,
            horizon=horizon,
            timeseries_path=timeseries_path,
        )
        summary.append(input_values + [str(repetition), timeseries_path.name])

    with (results_dir / "results.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(input_names + ["repetition", "output"])
        for row in summary:
            writer.writerow(row)

    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
'''
