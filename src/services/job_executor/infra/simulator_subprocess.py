from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List

from services.job_executor.core.ports import SimulatorPort


class SubprocessSimulator(SimulatorPort):
    def __init__(self, executor_user: str | None = None, executor_group: str | None = None) -> None:
        self.executor_user = executor_user
        self.executor_group = executor_group

    def run(self, simulator_path: str, matrix_path: str, row_number: str, workdir: str) -> None:
        simulator_file = Path(simulator_path).expanduser()
        if not simulator_file.is_absolute():
            simulator_file = (Path.cwd() / simulator_file).resolve()
        else:
            simulator_file = simulator_file.resolve()
        cmd = [str(simulator_file), matrix_path, row_number]
        env = os.environ.copy()
        if self.executor_user is not None:
            env["JOB_EXECUTOR_USER"] = self.executor_user
        if self.executor_group is not None:
            env["JOB_EXECUTOR_GROUP"] = self.executor_group
        subprocess.run(cmd, cwd=workdir, check=True, env=env)
