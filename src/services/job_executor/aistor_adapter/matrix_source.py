from __future__ import annotations

from typing import Final
from urllib.parse import urlparse

from minio import Minio

from services.job_executor.core.ports import MatrixSourcePort


class AIStorMatrixSource(MatrixSourcePort):
    def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool) -> None:
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.secure = secure
        self._client = Minio(
            _endpoint_host(endpoint),
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def download_matrix(self, uri: str) -> bytes:
        bucket, key = _parse_s3_url(uri)
        try:
            response = self._client.get_object(bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Failed to download matrix endpoint={self.endpoint} bucket={bucket} key={key}"
            ) from exc


def _endpoint_host(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    host = parsed.netloc if parsed.scheme else parsed.path
    if not host:
        raise ValueError(f"Invalid endpoint: {endpoint}")
    return host


def _parse_s3_url(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise ValueError(f"Invalid matrix URI (expected s3://): {uri}")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        raise ValueError(f"Invalid matrix URI (missing bucket or key): {uri}")
    return bucket, key
