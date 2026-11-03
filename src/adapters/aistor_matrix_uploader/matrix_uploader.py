from __future__ import annotations

import io
from urllib.parse import urlparse

from minio import Minio

from services.matrix_generation.core.dto import UploadResult
from services.matrix_generation.core.ports import MatrixUploader

def _endpoint_host(endpoint: str | bytes) -> str:
    if isinstance(endpoint, bytes):
        endpoint = endpoint.decode("utf-8")
    parsed = urlparse(endpoint)
    if parsed.scheme:
        return parsed.netloc
    return endpoint


class AIStorMatrixUploader(MatrixUploader):
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
        client: Minio | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._secure = secure
        if client is not None:
            self._client = client
        else:
            self._client = Minio(
                _endpoint_host(self._endpoint),
                access_key=self._access_key,
                secret_key=self._secret_key,
                secure=self._secure,
            )

    def upload_text(
            self,
            *,
            bucket: str,
            key: str,
            content: str,
            content_type: str = "text/plain",
    ) -> UploadResult:
        data = content.encode("utf-8")
        try:
            result = self._client.put_object(
                bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
        except Exception as exc:
            raise RuntimeError(
                f"AIStor upload failed (endpoint={self._endpoint}, bucket={bucket}, key={key}): {exc}"
            ) from exc

        return UploadResult(
            url=_object_s3_uri(bucket, key),
            etag=getattr(result, "etag", None),
            version_id=getattr(result, "version_id", None),
        )

def _object_s3_uri(bucket: str, key: str) -> str:
    normalized_key = key.lstrip("/")
    return f"s3://{bucket}/{normalized_key}"
