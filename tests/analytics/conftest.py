from __future__ import annotations

import pytest


class FakeResultsRepository:
    def __init__(self, files: dict[str, str]) -> None:
        self._files = {key: value.encode("utf-8") for key, value in files.items()}
        self.downloads: list[str] = []

    def download(self, url: str) -> bytes:
        self.downloads.append(url)
        if url not in self._files:
            raise FileNotFoundError(url)
        return self._files[url]


@pytest.fixture
def fake_results_repository():
    return FakeResultsRepository
