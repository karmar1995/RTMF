from __future__ import annotations

import csv
import io
import tempfile
import zipfile

import pytest

from adapters.system_discovery_simulation_results_postprocessor import (
    SystemDiscoverySimulationResultsArchivePostprocessor,
)
from use_case_contracts.dtos import SystemDiscoverySimulationResultsArchive


def test_zip_with_one_results_csv_is_processed_and_other_members_are_preserved() -> None:
    archive = _zip(
        {
            "results.csv": b"x;y\n1.0;2.0\n3.0;4.0\n",
            "notes/readme.txt": b"unchanged",
        }
    )

    result = _postprocess(archive)

    assert result.was_modified is True
    members = _members(result.archive.content)
    assert members["notes/readme.txt"] == b"unchanged"
    assert members["results.csv"].decode("utf-8").splitlines()[0] == "time;x;y"
    assert _rows(members["results.csv"], delimiter=";") == [
        ["time", "x", "y"],
        ["0", "1.0", "2.0"],
        ["1", "3.0", "4.0"],
    ]


def test_nested_results_csv_keeps_existing_archive_path() -> None:
    archive = _zip({"nested/results.csv": b"a,b\nc,d\n"})

    result = _postprocess(archive)

    members = _members(result.archive.content)
    assert set(members) == {"nested/results.csv"}
    assert _rows(members["nested/results.csv"], delimiter=";") == [
        ["time", "a", "b"],
        ["0", "c", "d"],
    ]


def test_missing_results_csv_is_rejected() -> None:
    with pytest.raises(ValueError, match="missing results.csv"):
        _postprocess(_zip({"other.csv": b"a,b\n"}))


def test_duplicate_results_csv_members_are_rejected() -> None:
    archive = _zip(
        {
            "results.csv": b"a,b\n",
            "nested/results.csv": b"c,d\n",
        }
    )

    with pytest.raises(ValueError, match="multiple results.csv"):
        _postprocess(archive)


def test_duplicate_time_columns_are_rejected() -> None:
    with pytest.raises(ValueError, match="multiple time"):
        _postprocess(_zip({"results.csv": b"time;time;y\n1;2;3\n"}))


def test_postprocessing_is_idempotent_and_does_not_duplicate_time() -> None:
    first = _postprocess(
        _zip({"results.csv": b"x;time;y\n1.0;10;2.0\n3.0;11;4.0\n"})
    )
    second = _postprocess(first.archive.content)

    assert first.was_modified is True
    assert second.was_modified is False
    assert _rows(_members(second.archive.content)["results.csv"], delimiter=";") == [
        ["time", "x", "y"],
        ["0", "1.0", "2.0"],
        ["1", "3.0", "4.0"],
    ]


def test_already_canonical_semicolon_csv_is_not_marked_modified() -> None:
    result = _postprocess(
        _zip({"results.csv": b"time;x;y\n0;1.0;2.0\n1;3.0;4.0\n"})
    )

    assert result.was_modified is False
    assert _members(result.archive.content)["results.csv"] == (
        b"time;x;y\n0;1.0;2.0\n1;3.0;4.0\n"
    )


def test_comma_delimited_legacy_csv_is_repaired_to_semicolon() -> None:
    result = _postprocess(
        _zip({"results.csv": b"time,prediction,reference\n7,0.12,0.15\n8,0.18,0.17\n"})
    )

    assert result.was_modified is True
    content = _members(result.archive.content)["results.csv"]
    assert content.decode("utf-8").splitlines() == [
        "time;prediction;reference",
        "0;0.12;0.15",
        "1;0.18;0.17",
    ]


def test_quoted_values_containing_commas_or_semicolons_remain_valid() -> None:
    result = _postprocess(
        _zip(
            {
                "results.csv": (
                    b'label;prediction;reference\n'
                    b'"a,b";"1;2";3\n'
                    b'"c;d";"4,5";6\n'
                )
            }
        )
    )

    content = _members(result.archive.content)["results.csv"]
    assert _rows(content, delimiter=";") == [
        ["time", "label", "prediction", "reference"],
        ["0", "a,b", "1;2", "3"],
        ["1", "c;d", "4,5", "6"],
    ]


def test_malformed_row_width_is_rejected() -> None:
    with pytest.raises(ValueError, match="row 3"):
        _postprocess(_zip({"results.csv": b"x;y\n1;2\n3\n"}))


def test_unsafe_zip_member_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsafe ZIP member path"):
        _postprocess(_zip({"../results.csv": b"x;y\n1;2\n"}))


def test_no_temporary_files_are_created(monkeypatch) -> None:
    def fail_mkstemp(*_args, **_kwargs):
        raise AssertionError("temporary files must not be used")

    monkeypatch.setattr(tempfile, "mkstemp", fail_mkstemp)

    _postprocess(_zip({"results.csv": b"x;y\n1;2\n"}))


def _postprocess(
    archive: bytes,
):
    return SystemDiscoverySimulationResultsArchivePostprocessor().postprocess(
        SystemDiscoverySimulationResultsArchive(content=archive)
    )


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def _members(archive: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(archive), mode="r") as zf:
        return {
            name: zf.read(name)
            for name in zf.namelist()
            if not name.endswith("/")
        }


def _rows(content: bytes, *, delimiter: str) -> list[list[str]]:
    return list(
        csv.reader(
            io.StringIO(content.decode("utf-8"), newline=""),
            delimiter=delimiter,
        )
    )
