from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatrixGeneratorAdapterConfig:
    base_url: str
    timeout_seconds: int | None = 10
