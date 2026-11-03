from __future__ import annotations

import json
from typing import Final
from urllib.parse import urlparse
from io import BytesIO
from urllib.parse import quote

from minio import Minio

from services.job_executor.core.ports import ResultsRepositoryPort


_ZIP_CONTENT_TYPE: Final = "application/octet-stream"
_JSON_CONTENT_TYPE: Final = "application/json"


def _assemble_url(endpoint: str, bucket: str, path: str,  secure: bool):
    endpoint = 's3:/'
    object_name = path.lstrip("/")

    # keep path separators, but encode special characters in each segment
    encoded_object_name = "/".join(
        quote(part, safe="") for part in object_name.split("/")
    )

    return f"{endpoint}/{quote(bucket, safe='')}/{encoded_object_name}"


class AIStorResultsRepository(ResultsRepositoryPort):
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
        bucket: str,
    ) -> None:
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.secure = secure
        self.bucket = bucket
        self._client = Minio(
            _endpoint_host(endpoint),
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
    def assemble_job_root_url(self, job_id):
        return _assemble_url(self.endpoint, self.bucket, f"jobs/{job_id}", self.secure)

    def upload_result_zip(self, job_id: str, sub_job_id: str, zip_bytes: bytes) -> str:
        result_key = f"jobs/{job_id}/results/{sub_job_id}/results.csv.zip"
        self._ensure_bucket_exists()
        return self._put_bytes(result_key, zip_bytes, _ZIP_CONTENT_TYPE)

    def upload_params(self, job_id: str, sub_job_id: str, params: list[str]) -> None:
        params_key = f"jobs/{job_id}/results/{sub_job_id}/params.json"
        self._ensure_bucket_exists()
        payload = json.dumps(list(params)).encode("utf-8")
        self._put_bytes(params_key, payload, _JSON_CONTENT_TYPE)

    def upload_csv_zip(self, job_id: str, sub_job_id: str, filename: str, data: bytes) -> None:
        key = f"jobs/{job_id}/results/{sub_job_id}/{filename}.zip"
        self._ensure_bucket_exists()
        self._put_bytes(key, data, _ZIP_CONTENT_TYPE)

    def _ensure_bucket_exists(self) -> None:
        try:
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Failed to ensure bucket exists endpoint={self.endpoint} bucket={self.bucket}"
            ) from exc

    def _put_bytes(self, key: str, content: bytes, content_type: str) -> str:
        try:
            data = BytesIO(content)
            result = self._client.put_object(
                self.bucket,
                key,
                data,
                length=len(content),
                content_type=content_type,
            )

            return _assemble_url(self.endpoint, self.bucket, result.object_name, self.secure)

        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Failed to upload endpoint={self.endpoint} bucket={self.bucket} key={key}"
            ) from exc

def _endpoint_host(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    host = parsed.netloc if parsed.scheme else parsed.path
    if not host:
        raise ValueError(f"Invalid endpoint: {endpoint}")
    return host
