import io
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from use_case_contracts.ports import ResultsRepositoryPort


class FakeResultsRepository(ResultsRepositoryPort):
    def __init__(self, store: dict[str, bytes] | None = None) -> None:
        self._store: dict[str, bytes] = store or {}

    def download(self, url: str) -> bytes:
        raw: bytes | None = None
        parsed = urlparse(url)

        if parsed.scheme == "memory":
            raw = self._store.get(url)
        elif parsed.scheme == "file":
            raw = Path(parsed.path).read_bytes()
        elif parsed.scheme in ("", "s3"):
            raw = self._store.get(url)
        else:
            raise ValueError(f"Unsupported scheme in {url}")

        if raw is None:
            raise KeyError(f"Fake result not found: {url}")

        if url.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                if not names:
                    raise RuntimeError("zip has no files")
                if len(names) > 1:
                    raise RuntimeError("zip has multiple files")
                return zf.read(names[0])

        return raw

    def store(self, url: str, data: bytes) -> None:
        self._store[url] = data
