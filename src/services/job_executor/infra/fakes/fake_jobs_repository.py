from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict

from services.job_executor.core.ports import ResultsRepositoryPort


@dataclass
class FakeResultsRepository(ResultsRepositoryPort):
    objects: Dict[str, bytes] = field(default_factory=dict)

    def upload_result_zip(self, job_id: str, sub_job_id: str, zip_bytes: bytes) -> str:
        result_key = f"jobs/{job_id}/results/{sub_job_id}/results.csv.zip"
        legacy_key = f"jobs/{job_id}/results/{sub_job_id}/result.csv"
        self.objects[result_key] = zip_bytes
        self.objects[legacy_key] = zip_bytes
        return result_key

    def upload_params(self, job_id: str, sub_job_id: str, params: list[str]) -> None:
        key = f"jobs/{job_id}/results/{sub_job_id}/params.json"
        self.objects[key] = json.dumps(list(params)).encode("utf-8")

    def upload_csv_zip(self, job_id: str, sub_job_id: str, filename: str, data: bytes) -> None:
        key = f"jobs/{job_id}/results/{sub_job_id}/{filename}"
        self.objects[key] = data

    def list_keys(self) -> list[str]:
        return sorted(self.objects.keys())

    def get(self, key: str) -> bytes:
        return self.objects[key]
