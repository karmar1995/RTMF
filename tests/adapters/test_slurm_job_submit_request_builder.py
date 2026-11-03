import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from adapters.slurm_adapter.slurm_job_submit_request_builder import (
    SlurmJobSubmitDefaults,
    SlurmJobSubmitRequestBuilder,
)


@pytest.mark.parametrize(
    "field", ["simulator_uri", "matrix_uri", "simulator_path", "base_workdir"]
)
def test_job_script_passes_shell_metacharacters_as_literal_arguments(tmp_path, field):
    marker = tmp_path / "unexpected-command-execution"
    captured = tmp_path / "arguments.json"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    apptainer = bin_dir / "apptainer"
    apptainer.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['CAPTURED_ARGUMENTS']).write_text(json.dumps({"
        "'args': sys.argv[1:], 'repetition': os.environ['RTMF_REPETITION']}))\n",
        encoding="utf-8",
    )
    apptainer.chmod(0o755)
    payload = "spaces ' \" ; $(touch \"$AUDIT_MARKER\") `touch \"$AUDIT_MARKER\"`\nnext"
    values = {
        "simulator_uri": "docker://registry.example/simulator:local",
        "matrix_uri": "s3://tmp/matrix.txt",
        "simulator_path": "/opt/simulator/start_sim.sh",
        "base_workdir": str(tmp_path / "work"),
    }
    values[field] += payload
    builder = SlurmJobSubmitRequestBuilder(None, defaults=SlurmJobSubmitDefaults())
    script = tmp_path / "job.sh"
    script.write_text(
        builder.build_array_script(**values, combinations=3, repetitions=2),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "CAPTURED_ARGUMENTS": str(captured),
            "AUDIT_MARKER": str(marker),
            "SLURM_ARRAY_JOB_ID": "12",
            "SLURM_ARRAY_TASK_ID": "5",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    invocation = json.loads(captured.read_text(encoding="utf-8"))
    args = invocation["args"]
    assert args[args.index("--") + 1] == values["simulator_uri"]
    for option, value in {
        "--matrix-uri": values["matrix_uri"],
        "--simulator-path": values["simulator_path"],
        "--row-index": "2",
        "--job-id": "12",
        "--sub-job-id": "5",
        "--workdir": str(Path(values["base_workdir"]) / "12" / "5"),
    }.items():
        assert args[args.index(option) + 1] == value
    assert Path(args[args.index("--workdir") + 1]).is_dir()
    assert invocation["repetition"] == "2"
