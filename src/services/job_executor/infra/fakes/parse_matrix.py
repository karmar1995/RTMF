from __future__ import annotations

from dataclasses import dataclass
from typing import List
from typing import Sequence

@dataclass(frozen=True)
class MatrixRow:
    index: int
    params: Sequence[str]

@dataclass(frozen=True)
class MatrixData:
    repetitions: int
    rows: List[MatrixRow]


def _split_line(line: str) -> list[str]:
    parts = line.split()
    return [p for p in (part.strip() for part in parts) if p]


def load_matrix_bytes(content: bytes) -> MatrixData:
    lines = []
    for raw in content.decode("utf-8", errors="strict").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)

    if not lines:
        raise ValueError("matrix content is empty")

    try:
        repetitions = int(lines[0])
    except ValueError as exc:
        raise ValueError("first line of matrix must be an integer repetition count") from exc

    rows: List[MatrixRow] = []
    for idx, line in enumerate(lines[1:]):
        params = _split_line(line)
        rows.append(MatrixRow(index=idx, params=params))

    return MatrixData(repetitions=repetitions, rows=rows)
