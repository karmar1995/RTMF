from __future__ import annotations

import io
import json
import os
import pickle
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

from services.use_case.handlers.sd_simulator_registration import (
    InvalidSystemDiscoverySimulatorArchiveError,
    build_build_spec,
    build_simulator_input_params,
    build_simulator_output_params,
    build_wrapper_archive,
    derive_ic_dimension,
)
from use_case_contracts.dtos import ParamType


def _workspace_archive(initial_conditions=(0, 1, 2)) -> bytes:
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, mode="w") as archive:
            archive.writestr("model.syspy", b"trained-model-bytes")
            archive.writestr(
                "initial_conditions.json",
                json.dumps(list(initial_conditions)).encode(),
            )
        return buffer.getvalue()


def test_build_simulator_input_params_flattens_ic_and_adds_horizon() -> None:
    params = build_simulator_input_params(3, include_horizon=True)

    assert [p.name for p in params] == ["ic_0", "ic_1", "ic_2", "horizon"]
    assert all(p.type == ParamType.FLOAT for p in params if p.name.startswith("ic_"))
    assert params[-1].type == ParamType.INT


def test_build_simulator_input_params_can_omit_horizon() -> None:
    params = build_simulator_input_params(2, include_horizon=False)

    assert [p.name for p in params] == ["ic_0", "ic_1"]


def test_build_simulator_input_params_rejects_no_ic() -> None:
    with pytest.raises(
        InvalidSystemDiscoverySimulatorArchiveError, match="no initial conditions"
    ):
        build_simulator_input_params(0)


def test_build_simulator_output_params_exposes_single_timeseries() -> None:
    params = build_simulator_output_params()

    assert len(params) == 1
    assert params[0].name == "output"
    assert params[0].type == ParamType.FLOAT_TS


def test_build_build_spec_targets_python_3_11_linux_with_sysidentpy() -> None:
    spec = build_build_spec()

    assert spec.spec["platform"]["os"] == "linux"
    assert spec.spec["technology"]["python"]["version"] == "3.11"
    assert spec.spec["technology"]["python"]["packages"] == [
        {"name": "sysidentpy"}
    ]


def test_derive_ic_dimension_from_json_list() -> None:
    assert derive_ic_dimension(_workspace_archive((7, 8, 9))) == 3


def test_derive_ic_dimension_from_space_separated_string() -> None:
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, mode="w") as archive:
            archive.writestr("model.syspy", b"bytes")
            archive.writestr("initial_conditions.json", b"4 5 6 7")
        raw = buffer.getvalue()

    assert derive_ic_dimension(raw) == 4


def test_derive_ic_dimension_rejects_archive_without_model() -> None:
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, mode="w") as archive:
            archive.writestr("initial_conditions.json", b"[1, 2]")
        raw = buffer.getvalue()

    with pytest.raises(
        InvalidSystemDiscoverySimulatorArchiveError, match="no trained model"
    ):
        derive_ic_dimension(raw)


def test_derive_ic_dimension_falls_back_to_fallback_dimension_without_initial_conditions() -> None:
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, mode="w") as archive:
            archive.writestr("model.syspy", b"trained-model-bytes")
        raw = buffer.getvalue()

    assert derive_ic_dimension(raw, fallback_dimension=5) == 5


def test_derive_ic_dimension_prefers_initial_conditions_over_fallback() -> None:
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, mode="w") as archive:
            archive.writestr("model.syspy", b"trained-model-bytes")
            archive.writestr("initial_conditions.json", b"[1, 2, 3]")
        raw = buffer.getvalue()

    assert derive_ic_dimension(raw, fallback_dimension=5) == 3


def test_derive_ic_dimension_rejects_missing_fallback_without_initial_conditions() -> None:
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, mode="w") as archive:
            archive.writestr("model.syspy", b"trained-model-bytes")
        raw = buffer.getvalue()

    with pytest.raises(
        InvalidSystemDiscoverySimulatorArchiveError, match="no initial conditions"
    ):
        derive_ic_dimension(raw)


def test_derive_ic_dimension_rejects_invalid_fallback_dimension() -> None:
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, mode="w") as archive:
            archive.writestr("model.syspy", b"trained-model-bytes")
        raw = buffer.getvalue()

    with pytest.raises(
        InvalidSystemDiscoverySimulatorArchiveError, match="invalid lag window"
    ):
        derive_ic_dimension(raw, fallback_dimension=0)


def test_derive_ic_dimension_rejects_bad_archive() -> None:
    with pytest.raises(InvalidSystemDiscoverySimulatorArchiveError, match="not a valid ZIP"):
        derive_ic_dimension(b"not-a-zip")


def test_build_wrapper_archive_contains_entrypoint_and_model_artifacts() -> None:
    wrapped = build_wrapper_archive(_workspace_archive((1, 2, 3)), ic_dimension=3)

    with zipfile.ZipFile(io.BytesIO(wrapped), mode="r") as archive:
        names = set(archive.namelist())

    assert names == {
        "start_sim.sh",
        "run.py",
        "model.syspy",
        "initial_conditions.json",
    }

    entrypoint = (
        zipfile.ZipFile(io.BytesIO(wrapped))
        .read("run.py")
        .decode()
    )
    assert "IC_DIMENSION = 3" in entrypoint


def test_build_wrapper_archive_includes_start_sim_shim() -> None:
    wrapped = build_wrapper_archive(_workspace_archive((1, 2, 3)), ic_dimension=3)

    with zipfile.ZipFile(io.BytesIO(wrapped)) as archive:
        shim = archive.read("start_sim.sh").decode()
        info = archive.getinfo("start_sim.sh")

    assert shim.startswith("#!/bin/bash")
    assert 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in shim
    assert 'export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"' in shim
    assert 'source "$SCRIPT_DIR/.venv/bin/activate"' in shim
    assert 'python3 "$SCRIPT_DIR/run.py" "$1" "$2"' in shim
    assert info.external_attr >> 16 & 0o777 == 0o777


def test_build_wrapper_archive_nests_artifacts_flat() -> None:
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, mode="w") as archive:
            archive.writestr("work/model.syspy", b"bytes")
            archive.writestr("work/initial_conditions.json", b"[1, 2]")
        raw = buffer.getvalue()

    wrapped = build_wrapper_archive(raw, ic_dimension=2)

    with zipfile.ZipFile(io.BytesIO(wrapped), mode="r") as archive:
        assert set(archive.namelist()) == {
            "start_sim.sh",
            "run.py",
            "model.syspy",
            "initial_conditions.json",
        }


def test_wrapped_simulator_executes_pickled_model_and_writes_results(tmp_path) -> None:
    pytest.importorskip("sysidentpy")
    from sysidentpy.basis_function import Polynomial
    from sysidentpy.model_structure_selection import FROLS
    from sysidentpy.parameter_estimation import LeastSquares

    rng = np.random.default_rng(0)
    n_samples = 60
    x = rng.normal(size=n_samples).reshape(-1, 1)
    y = np.zeros((n_samples, 1))
    for index in range(3, n_samples):
        y[index, 0] = (
            0.5 * y[index - 1, 0] + 0.2 * y[index - 2, 0] + 0.3 * x[index - 1, 0]
        )
    trained = FROLS(
        order_selection=False,
        n_terms=3,
        ylag=2,
        xlag=1,
        estimator=LeastSquares(),
        basis_function=Polynomial(degree=1),
    )
    trained.fit(X=x, y=y)
    max_lag = int(trained.max_lag)

    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, mode="w") as archive:
            archive.writestr("models/model.syspy", pickle.dumps(trained))
        workspace = buffer.getvalue()

    assert derive_ic_dimension(
        workspace, fallback_dimension=max_lag
    ) == max_lag == 2
    wrapped = build_wrapper_archive(workspace, ic_dimension=max_lag)

    sim_dir = tmp_path / "sim"
    sim_dir.mkdir()
    with zipfile.ZipFile(io.BytesIO(wrapped), mode="r") as archive:
        archive.extractall(sim_dir)

    (sim_dir / "matrix.txt").write_text(
        "1\n0.5 0.25 4\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "run.py", "matrix.txt", "0"],
        cwd=sim_dir,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

    timeseries = (sim_dir / "results" / "results_0.csv").read_text().splitlines()
    assert timeseries[0] == "time;output"
    assert len(timeseries) == 5  # header + 4 horizon steps

    summary = (sim_dir / "results" / "results.csv").read_text().splitlines()
    assert summary[0] == "ic_0;ic_1;horizon;repetition;output"
    assert summary[1] == "0.5;0.25;4;0;results_0.csv"
    assert len(summary) == 2
