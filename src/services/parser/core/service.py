import sys
import uuid
import subprocess
import json
import os
from pathlib import Path
from typing import Tuple, List, Optional, Dict, Any

class ParserService:
    def __init__(self, tasks_dir: str):
        self.tasks_dir = Path(tasks_dir)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        # Assuming the analysis script is now at this specific relative location
        self.base_dir = Path(__file__).resolve().parent.parent.parent.parent.parent # points to src
        self.analysis_script_path = Path(__file__).resolve().parent / "resiliency_recognition" / "src" / "main.py"

    def run_recognition(self, file_path: Path, baseline: Optional[float] = None) -> str:
        recognition_id = str(uuid.uuid4())
        task_dir = self.tasks_dir / recognition_id
        task_dir.mkdir(parents=True, exist_ok=True)
        
        target_path = task_dir / "input.zip"
        file_path.rename(target_path)
        
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.base_dir)
        
        cmd = [sys.executable, str(self.analysis_script_path)]
        if baseline is not None:
            cmd.extend(["--baseline", str(baseline)])

        subprocess.Popen(cmd, cwd=str(task_dir.absolute()), env=env)
        return recognition_id

    def get_status(self, recognition_id: str) -> str:
        task_dir = self.tasks_dir / recognition_id
        status_file = task_dir / "status.txt"
        if not task_dir.exists():
            return "NOT_FOUND"
        if not status_file.exists():
            return "PENDING"
        return status_file.read_text().strip()

    def get_result(self, recognition_id: str) -> Tuple[List, Dict]:
        task_dir = self.tasks_dir / recognition_id
        result_file = task_dir / "result.json"
        if not task_dir.exists():
            raise FileNotFoundError("Task not found")
        if not result_file.exists():
            raise FileNotFoundError("Results not ready")
            
        with open(result_file, 'r') as f:
            data = json.load(f)
            return data.get("phases", []), data.get("metrics", {})
