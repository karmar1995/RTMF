from __future__ import annotations

import csv
import io
import zipfile
from pathlib import PurePosixPath

from use_case_contracts.dtos import (
    SystemDiscoverySimulationResultsArchive,
    SystemDiscoverySimulationResultsArchivePostprocessingResult,
)
from use_case_contracts.ports import (
    SystemDiscoverySimulationResultsArchivePostprocessorPort,
)

_RESULTS_CSV = "results.csv"
_TIME_COLUMN = "time"
_CANONICAL_DELIMITER = ";"
_LEGACY_COMMA_DELIMITER = ","


class SystemDiscoverySimulationResultsArchivePostprocessor(
    SystemDiscoverySimulationResultsArchivePostprocessorPort
):
    def postprocess(
        self,
        archive: SystemDiscoverySimulationResultsArchive,
    ) -> SystemDiscoverySimulationResultsArchivePostprocessingResult:
        try:
            with zipfile.ZipFile(io.BytesIO(archive.content), mode="r") as source:
                bad_member = source.testzip()
                if bad_member is not None:
                    raise ValueError(f"Corrupted ZIP member: {bad_member}")
                infos = source.infolist()
                results_info = _locate_results_csv(infos)
                processed_csv = _canonical_results_csv(
                    source.read(results_info.filename)
                )
                original_csv = source.read(results_info.filename)
                return SystemDiscoverySimulationResultsArchivePostprocessingResult(
                    archive=SystemDiscoverySimulationResultsArchive(
                        content=_replace_member(
                            source=source,
                            infos=infos,
                            selected=results_info,
                            content=processed_csv,
                        )
                    ),
                    was_modified=processed_csv != original_csv,
                )
        except zipfile.BadZipFile as exc:
            raise ValueError(
                "System Discovery simulation results archive must be a valid ZIP file"
            ) from exc


def _locate_results_csv(infos: list[zipfile.ZipInfo]) -> zipfile.ZipInfo:
    seen_paths: set[str] = set()
    matches: list[zipfile.ZipInfo] = []
    for info in infos:
        _validate_member_path(info.filename)
        if info.is_dir():
            continue
        if info.filename in seen_paths:
            raise ValueError(f"Duplicate ZIP member path: {info.filename}")
        seen_paths.add(info.filename)
        if PurePosixPath(info.filename).name == _RESULTS_CSV:
            matches.append(info)
    if not matches:
        raise ValueError(
            "System Discovery simulation results archive is missing results.csv"
        )
    if len(matches) > 1:
        raise ValueError(
            "System Discovery simulation results archive contains multiple results.csv files"
        )
    return matches[0]


def _validate_member_path(name: str) -> None:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or path.as_posix().startswith("/")
        or ".." in path.parts
    ):
        raise ValueError(f"Unsafe ZIP member path: {name}")


def _canonical_results_csv(content: bytes) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("results.csv must be UTF-8 encoded") from exc

    rows = _read_results_rows(text)

    if not rows:
        raise ValueError("results.csv is empty")
    header = rows[0]
    if not header:
        raise ValueError("results.csv header is empty")
    expected_width = len(header)
    for index, row in enumerate(rows[1:], start=2):
        if len(row) != expected_width:
            raise ValueError(
                f"results.csv row {index} has {len(row)} columns; expected {expected_width}"
            )

    time_columns = [
        index for index, column in enumerate(header) if column == _TIME_COLUMN
    ]
    if len(time_columns) > 1:
        raise ValueError("results.csv contains multiple time columns")

    if time_columns:
        time_index = time_columns[0]
        non_time_indexes = [
            index for index in range(len(header)) if index != time_index
        ]
        processed_header = [
            _TIME_COLUMN,
            *(header[index] for index in non_time_indexes),
        ]
        processed_rows = [
            [str(row_index), *(row[index] for index in non_time_indexes)]
            for row_index, row in enumerate(rows[1:])
        ]
    else:
        processed_header = [_TIME_COLUMN, *header]
        processed_rows = [
            [str(row_index), *row] for row_index, row in enumerate(rows[1:])
        ]

    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=_CANONICAL_DELIMITER, lineterminator="\n")
    writer.writerow(processed_header)
    writer.writerows(processed_rows)
    return output.getvalue().encode("utf-8")


def _read_results_rows(text: str) -> list[list[str]]:
    rows = _read_csv_rows(text, delimiter=_CANONICAL_DELIMITER)
    if rows and len(rows[0]) == 1 and _LEGACY_COMMA_DELIMITER in rows[0][0]:
        return _read_csv_rows(text, delimiter=_LEGACY_COMMA_DELIMITER)
    return rows


def _read_csv_rows(text: str, *, delimiter: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        return list(reader)
    except csv.Error as exc:
        raise ValueError("results.csv is malformed") from exc


def _replace_member(
    *,
    source: zipfile.ZipFile,
    infos: list[zipfile.ZipInfo],
    selected: zipfile.ZipInfo,
    content: bytes,
) -> bytes:
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(
            buffer,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as target:
            for info in infos:
                if info.is_dir():
                    target.writestr(info, b"")
                elif info.filename == selected.filename:
                    target.writestr(info, content)
                else:
                    target.writestr(info, source.read(info.filename))
        return buffer.getvalue()
