from __future__ import annotations

from dataclasses import dataclass

from services.job_executor.core.ports import MatrixSourcePort


@dataclass
class FakeMatrixSource(MatrixSourcePort):
    mapping: dict[str, bytes]

    def download_matrix(self, uri: str) -> bytes:
        if uri not in self.mapping:
            raise KeyError(uri)
        return self.mapping[uri]
