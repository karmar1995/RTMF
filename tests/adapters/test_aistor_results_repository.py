from __future__ import annotations

import io
import threading
import zipfile

import pytest

from adapters.aistor_results_repository.details.results_repository import (
    AIStorResultsRepository,
)
from use_case_contracts.errors import (
    JobsRepositoryStoreCheckFailedError as ResultsRepositoryStoreCheckFailedError,
    JobsRepositoryStoreMissingError as ResultsRepositoryStoreMissingError,
)


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self) -> bytes:
        return self._content

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        pass


class _FakeMinio:
    def __init__(self, *, bucket_exists: bool = True, check_delay: float = 0.0):
        self._bucket_exists = bucket_exists
        self._check_delay = check_delay
        self.objects: dict[tuple[str, str], bytes] = {}
        self.bucket_checks: list[str] = []
        self.object_gets: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def bucket_exists(self, bucket: str) -> bool:
        if self._check_delay:
            # Widen the window in which a second thread could slip in and
            # duplicate the check, so the test would fail without the lock.
            threading.Event().wait(self._check_delay)
        with self._lock:
            self.bucket_checks.append(bucket)
        return self._bucket_exists

    def get_object(self, bucket: str, key: str) -> _FakeResponse:
        with self._lock:
            self.object_gets.append((bucket, key))
        return _FakeResponse(self.objects[(bucket, key)])


def _repository(
    client: _FakeMinio, bucket: str = "jobs-results"
) -> AIStorResultsRepository:
    return AIStorResultsRepository(
        endpoint="http://127.0.0.1:9000",
        access_key="minio",
        secret_key="password",
        secure=False,
        bucket=bucket,
        client=client,
    )


def _zip_bytes(content: bytes = b"a,b\n1,2\n") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("results.csv", content)
    return buffer.getvalue()


def test_download_checks_the_bucket_only_once_across_many_objects() -> None:
    client = _FakeMinio()
    repository = _repository(client)
    for index in range(25):
        client.objects[("jobs-results", f"jobs/1/results/{index}/results.csv.zip")] = (
            _zip_bytes()
        )

    for index in range(25):
        data = repository.download(
            f"s3://jobs-results/jobs/1/results/{index}/results.csv.zip"
        )

    assert data == b"a,b\n1,2\n"
    assert client.bucket_checks == ["jobs-results"]
    assert len(client.object_gets) == 25


def test_download_checks_the_bucket_once_under_concurrency() -> None:
    client = _FakeMinio(check_delay=0.02)
    repository = _repository(client)
    urls = []
    for index in range(20):
        key = f"jobs/1/results/{index}/results.csv.zip"
        client.objects[("jobs-results", key)] = _zip_bytes()
        urls.append(f"s3://jobs-results/{key}")

    errors: list[Exception] = []

    def worker(url: str) -> None:
        try:
            repository.download(url)
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(url,)) for url in urls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert client.bucket_checks == ["jobs-results"]


def test_missing_bucket_is_reported_on_every_call() -> None:
    client = _FakeMinio(bucket_exists=False)
    repository = _repository(client)

    for _ in range(3):
        with pytest.raises(ResultsRepositoryStoreMissingError):
            repository.download("s3://jobs-results/jobs/1/results/0/results.csv.zip")

    assert client.bucket_checks == ["jobs-results"] * 3


def test_bucket_check_failure_is_reported_on_every_call() -> None:
    class _BrokenMinio(_FakeMinio):
        def bucket_exists(self, bucket: str) -> bool:
            self.bucket_checks.append(bucket)
            raise RuntimeError("connection reset")

    repository = _repository(_BrokenMinio())

    for _ in range(2):
        with pytest.raises(ResultsRepositoryStoreCheckFailedError):
            repository.download("s3://jobs-results/jobs/1/results/0/results.csv.zip")


def test_bucket_becoming_available_is_picked_up_after_a_failed_check() -> None:
    client = _FakeMinio(bucket_exists=False)
    repository = _repository(client)

    with pytest.raises(ResultsRepositoryStoreMissingError):
        repository.download("s3://jobs-results/jobs/1/results/0/results.csv.zip")

    client._bucket_exists = True
    client.objects[("jobs-results", "jobs/1/results/0/results.csv.zip")] = _zip_bytes()

    assert repository.download(
        "s3://jobs-results/jobs/1/results/0/results.csv.zip"
    ) == b"a,b\n1,2\n"
