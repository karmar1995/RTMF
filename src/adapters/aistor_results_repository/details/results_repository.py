from __future__ import annotations

import io
import threading
import zipfile
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from use_case_contracts.dtos import UploadResult
from use_case_contracts.errors import (
    JobsRepositoryError as ResultsRepositoryError,
    JobsRepositoryInvalidStoreError as ResultsRepositoryInvalidStoreError,
    JobsRepositoryInvalidUrlError as ResultsRepositoryInvalidUrlError,
    JobsRepositoryInvalidZipError as ResultsRepositoryInvalidZipError,
    JobsRepositoryMalformedUrlError as ResultsRepositoryMalformedUrlError,
    JobsRepositoryObjectDownloadFailedError as ResultsRepositoryObjectDownloadFailedError,
    JobsRepositoryObjectNotFoundError as ResultsRepositoryObjectNotFoundError,
    JobsRepositoryResponseCleanupFailedError as ResultsRepositoryResponseCleanupFailedError,
    JobsRepositoryResponseReadFailedError as ResultsRepositoryResponseReadFailedError,
    JobsRepositoryStoreCheckFailedError as ResultsRepositoryStoreCheckFailedError,
    JobsRepositoryStoreMissingError as ResultsRepositoryStoreMissingError,
    JobsRepositoryZipHasMultipleFilesError as ResultsRepositoryZipHasMultipleFilesError,
    JobsRepositoryZipHasNoFilesError as ResultsRepositoryZipHasNoFilesError,
)
from use_case_contracts.ports import ResultsRepositoryPort


class AIStorResultsRepository(ResultsRepositoryPort):
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
        bucket: str,
        client: Minio | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._secure = secure
        self._bucket = bucket
        self._bucket_lock = threading.Lock()
        self._bucket_verified = False
        if client is not None:
            self._client = client
        else:
            self._client = Minio(
                _endpoint_host(self._endpoint),
                access_key=self._access_key,
                secret_key=self._secret_key,
                secure=self._secure,
            )

    def download(self, url: str) -> bytes:
        bucket, key = _parse_s3_url(url)
        if bucket != self._bucket:
            raise ResultsRepositoryInvalidStoreError(
                expected_store=self._bucket,
                actual_store=bucket,
                url=url,
            )
        self._ensure_bucket_exists()
        try:
            response = self._client.get_object(bucket, key)
            read_exc: Exception | None = None
            data: bytes | None = None
            try:
                try:
                    data = response.read()
                except Exception as exc:
                    read_exc = exc
            finally:
                try:
                    response.close()
                except Exception as exc:
                    raise ResultsRepositoryResponseCleanupFailedError(
                        self._endpoint, self._bucket, key, str(exc)
                    ) from exc
                try:
                    response.release_conn()
                except Exception as exc:
                    raise ResultsRepositoryResponseCleanupFailedError(
                        self._endpoint, self._bucket, key, str(exc)
                    ) from exc
            if read_exc is not None:
                raise ResultsRepositoryResponseReadFailedError(
                    self._endpoint, self._bucket, key, str(read_exc)
                ) from read_exc
            if key.endswith(".zip"):
                try:
                    return _unzip_single_file(data, key)
                except zipfile.BadZipFile as exc:
                    raise ResultsRepositoryInvalidZipError(self._endpoint, self._bucket, key) from exc
                except RuntimeError as exc:
                    if str(exc) == "zip has no files":
                        raise ResultsRepositoryZipHasNoFilesError(self._endpoint, self._bucket, key) from exc
                    if str(exc) == "zip has multiple files":
                        raise ResultsRepositoryZipHasMultipleFilesError(self._endpoint, self._bucket, key) from exc
                    raise
            return data
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                raise ResultsRepositoryObjectNotFoundError(self._endpoint, self._bucket, key) from exc
            raise ResultsRepositoryObjectDownloadFailedError(
                self._endpoint,
                self._bucket,
                key,
                str(exc),
            ) from exc
        except ResultsRepositoryError:
            raise
        except Exception as exc:
            if exc.__class__.__name__ == "FakeNoSuchKeyError":
                raise ResultsRepositoryObjectNotFoundError(self._endpoint, self._bucket, key) from exc
            raise ResultsRepositoryObjectDownloadFailedError(
                self._endpoint,
                self._bucket,
                key,
                str(exc),
            ) from exc

    def upload(
        self,
        *,
        bucket: str,
        key: str,
        content: str,
        content_type: str = "text/plain",
    ) -> UploadResult:
        raise NotImplementedError("Work in progress!")

    def _ensure_bucket_exists(self) -> None:
        if self._bucket_verified:
            return
        with self._bucket_lock:
            if self._bucket_verified:
                return
            try:
                exists = self._client.bucket_exists(self._bucket)
            except Exception as exc:
                raise ResultsRepositoryStoreCheckFailedError(
                    self._endpoint,
                    self._bucket,
                    str(exc),
                ) from exc
            if not exists:
                raise ResultsRepositoryStoreMissingError(
                    self._endpoint, self._bucket
                )
            self._bucket_verified = True

def _endpoint_host(endpoint: str | bytes) -> str:
    if isinstance(endpoint, bytes):
        endpoint = endpoint.decode("utf-8")
    parsed = urlparse(endpoint)
    if parsed.scheme:
        return parsed.netloc
    return endpoint


def _parse_s3_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme != "s3":
        raise ResultsRepositoryInvalidUrlError(url)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket:
        raise ResultsRepositoryMalformedUrlError(url, reason="missing store")
    if not key:
        raise ResultsRepositoryMalformedUrlError(url, reason="missing key")
    return bucket, key

def _unzip_single_file(data: bytes, key: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        names = [name for name in zf.namelist() if not name.endswith("/")]
        if not names:
            raise RuntimeError("zip has no files")
        if len(names) > 1:
            raise RuntimeError("zip has multiple files")
        return zf.read(names[0])
