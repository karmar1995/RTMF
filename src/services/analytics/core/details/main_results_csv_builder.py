from __future__ import annotations

import csv
import io
from typing import Iterable, TextIO


class MainResultsCsvBuilder:
    """Stateless builder that concatenates multiple CSV fragments into one CSV text."""

    def build(self, sources: Iterable[str | TextIO]) -> str:
        """Concatenate CSV fragments row-wise, preserving one shared header row."""

        return self.build_with_offsets(sources)[0]

    def build_with_offsets(
        self, sources: Iterable[str | TextIO]
    ) -> tuple[str, list[int]]:
        """Concatenate CSV fragments and report where each fragment's rows start.

        The returned offsets always have one more element than there were sources,
        so ``offsets[i]`` is the first merged-table row produced by ``sources[i]``
        and ``offsets[-1]`` is the total row count. Fragments contributing no rows
        repeat the current offset, which lets a caller recover the owning source of
        any merged row with a binary search even after the fragments are merged.
        """

        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        expected_header: list[str] | None = None
        has_rows = False
        offsets: list[int] = []
        row_count = 0

        for source in sources:
            offsets.append(row_count)
            rows = self._read_rows(source)
            if not rows:
                continue

            header = rows[0]
            if expected_header is None:
                expected_header = header
                writer.writerow(header)
                has_rows = True
            elif header != expected_header:
                raise ValueError(
                    f"CSV header mismatch: expected {expected_header!r}, got {header!r}"
                )

            for row in rows[1:]:
                writer.writerow(row)
                has_rows = True
                row_count += 1

        offsets.append(row_count)

        if not has_rows:
            return "", offsets
        return output.getvalue(), offsets

    def _read_rows(self, source: str | TextIO) -> list[list[str]]:
        reader = csv.reader(self._to_stream(source))
        return [row for row in reader if any(cell.strip() for cell in row)]

    def _to_stream(self, source: str | TextIO) -> TextIO:
        if hasattr(source, "read"):
            return source
        return io.StringIO(source)
