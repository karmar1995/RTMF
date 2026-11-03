from __future__ import annotations

import io
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from adapters.system_discovery_aistor_adapter.config import SystemDiscoveryAIStorConfig
from adapters.system_discovery_aistor_adapter.errors import (
    SystemDiscoveryAIStorBucketUnavailableError,
    SystemDiscoveryAIStorConfigurationError,
    SystemDiscoveryAIStorObjectNotFoundError,
    SystemDiscoveryAIStorTransferError,
)


class SystemDiscoveryAIStorClient:
    def __init__(
        self,
        config: SystemDiscoveryAIStorConfig,
        client: Minio | None = None,
    ) -> None:
        self._config = _validate_config(config)
        self._client = client or Minio(
            endpoint=_endpoint_host(self._config.endpoint),
            access_key=self._config.access_key,
            secret_key=self._config.secret_key,
            secure=self._config.secure,
        )

    def upload_bytes(self, *, key: str, content: bytes, content_type: str) -> None:
        self._ensure_bucket_exists()
        try:
            self._client.put_object(
                self._config.system_discovery_results_bucket,
                key,
                io.BytesIO(content),
                length=len(content),
                content_type=content_type,
            )
        except Exception as exc:
            raise SystemDiscoveryAIStorTransferError(
                "Failed to upload System Discovery storage object"
            ) from exc

    def download_bytes(self, *, key: str) -> bytes:
        self._ensure_bucket_exists()
        try:
            response = self._client.get_object(
                self._config.system_discovery_results_bucket,
                key,
            )
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                raise SystemDiscoveryAIStorObjectNotFoundError(
                    "System Discovery storage object was not found"
                ) from exc
            raise SystemDiscoveryAIStorTransferError(
                "Failed to download System Discovery storage object"
            ) from exc
        except Exception as exc:
            if exc.__class__.__name__ == "FakeNoSuchKeyError":
                raise SystemDiscoveryAIStorObjectNotFoundError(
                    "System Discovery storage object was not found"
                ) from exc
            raise SystemDiscoveryAIStorTransferError(
                "Failed to download System Discovery storage object"
            ) from exc

    def object_exists(self, *, key: str) -> bool:
        self._ensure_bucket_exists()
        try:
            self._client.stat_object(
                self._config.system_discovery_results_bucket,
                key,
            )
            return True
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return False
            raise SystemDiscoveryAIStorTransferError(
                "Failed to check System Discovery storage object"
            ) from exc
        except Exception as exc:
            if exc.__class__.__name__ == "FakeNoSuchKeyError":
                return False
            raise SystemDiscoveryAIStorTransferError(
                "Failed to check System Discovery storage object"
            ) from exc

    def remove_object(self, *, key: str) -> None:
        self._ensure_bucket_exists()
        try:
            self._client.remove_object(
                self._config.system_discovery_results_bucket,
                key,
            )
        except Exception as exc:
            raise SystemDiscoveryAIStorTransferError(
                "Failed to remove System Discovery storage object"
            ) from exc

    def _ensure_bucket_exists(self) -> None:
        try:
            exists = self._client.bucket_exists(
                self._config.system_discovery_results_bucket
            )
        except Exception as exc:
            raise SystemDiscoveryAIStorBucketUnavailableError(
                "Failed to check System Discovery results bucket"
            ) from exc
        if not exists:
            raise SystemDiscoveryAIStorBucketUnavailableError(
                "System Discovery results bucket is unavailable"
            )


def _validate_config(
    config: SystemDiscoveryAIStorConfig,
) -> SystemDiscoveryAIStorConfig:
    if not config.endpoint.strip():
        raise SystemDiscoveryAIStorConfigurationError(
            "Missing System Discovery AIStor endpoint"
        )
    if not config.access_key.strip():
        raise SystemDiscoveryAIStorConfigurationError(
            "Missing System Discovery AIStor access key"
        )
    if not config.secret_key.strip():
        raise SystemDiscoveryAIStorConfigurationError(
            "Missing System Discovery AIStor secret key"
        )
    if not (config.system_discovery_results_bucket or "").strip():
        raise SystemDiscoveryAIStorConfigurationError(
            "Missing System Discovery results bucket"
        )
    return config


def _endpoint_host(endpoint: str | bytes) -> str:
    if isinstance(endpoint, bytes):
        endpoint = endpoint.decode("utf-8")
    parsed = urlparse(endpoint)
    if parsed.scheme:
        return parsed.netloc
    return endpoint