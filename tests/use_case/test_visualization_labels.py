import csv
import io
import zipfile

from use_case_contracts.dtos import JobVisualizationRenderedSeries


def _csv_in_zip(rows: list[list[str]], filename: str = "series.csv") -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow(row)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, buf.getvalue())
    return out.getvalue()


def _read_csv_rows(zip_bytes: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = [name for name in zf.namelist() if not name.endswith("/")]
        assert len(names) == 1
        content = zf.read(names[0]).decode("utf-8")
    return list(csv.reader(io.StringIO(content)))


from services.use_case.handlers.visualizations import (
    _rename_merged_series_headers,
)


def test_rename_series_headers_renames_columns() -> None:
    original_zip = _csv_in_zip([["time", "y", "y", "y"], [1, 10, 20, 30]])
    rendered = [
        JobVisualizationRenderedSeries(
            x="time", y="y", statistic="none",
            constant_params={"constant_a": "1"},
        ),
        JobVisualizationRenderedSeries(
            x="time", y="y", statistic="none",
            constant_params={"constant_a": "2"},
        ),
        JobVisualizationRenderedSeries(
            x="time", y="y", statistic="none",
            constant_params={"constant_a": "3"},
        ),
    ]

    result_zip = _rename_merged_series_headers(original_zip, rendered)
    rows = _read_csv_rows(result_zip)

    assert rows[0] == ["time", "Series 1", "Series 2", "Series 3"]
    assert rows[1] == ["1", "10", "20", "30"]


def test_rename_series_headers_renames_single_column() -> None:
    original_zip = _csv_in_zip([["time", "y"], [1, 10]])
    rendered = [
        JobVisualizationRenderedSeries(
            x="time", y="y", statistic="none",
            constant_params={"constant_a": "1"},
        ),
    ]

    result_zip = _rename_merged_series_headers(original_zip, rendered)
    rows = _read_csv_rows(result_zip)

    assert rows[0] == ["time", "Series 1"]


def test_rename_series_headers_returns_unchanged_on_mismatch() -> None:
    original_zip = _csv_in_zip([["time", "y", "y"], [1, 10, 20]])
    rendered = [
        JobVisualizationRenderedSeries(
            x="time", y="y", statistic="none",
            constant_params={"constant_a": "1"},
        ),
    ]

    result_zip = _rename_merged_series_headers(original_zip, rendered)
    rows = _read_csv_rows(result_zip)
    assert rows[0] == ["time", "y", "y"]


def test_rename_series_headers_returns_unchanged_on_empty() -> None:
    original_zip = _csv_in_zip([["time", "y"], [1, 10]])
    result_zip = _rename_merged_series_headers(original_zip, [])
    rows = _read_csv_rows(result_zip)
    assert rows[0] == ["time", "y"]