from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from use_case_contracts.dtos import (
    SystemDiscoveryEvaluationCategory,
    SystemDiscoveryEvaluationMetric,
    SystemDiscoveryTrainingEvaluationMetadata,
)

_RESULTS_CSV = "results.csv"
_CDF_CSV = "cdf.csv"
_SCATTER_CSV = "scatter.csv"
_METADATA_JSON = "metadata.json"


def postprocess_results_csv(content: bytes) -> bytes:
    text = content.decode("utf-8")
    sample = text[:4096]
    dialect = csv.Sniffer().sniff(sample, delimiters=";,")
    reader = csv.reader(io.StringIO(text, newline=""), dialect)
    rows = list(reader)
    if not rows:
        raise ValueError("results.csv is empty")
    header = rows[0]
    data_rows = rows[1:]
    if "time" in header:
        time_index = header.index("time")
        non_time_header = [
            column for index, column in enumerate(header) if index != time_index
        ]
        processed_header = ["time", *non_time_header]
        processed_rows = []
        for row_index, row in enumerate(data_rows):
            non_time_values = [
                value for index, value in enumerate(row) if index != time_index
            ]
            processed_rows.append([str(row_index), *non_time_values])
    else:
        processed_header = ["time", *header]
        processed_rows = [[str(index), *row] for index, row in enumerate(data_rows)]

    output = io.StringIO(newline="")
    writer = csv.writer(output, dialect)
    writer.writerow(processed_header)
    writer.writerows(processed_rows)
    return output.getvalue().encode("utf-8")


def generate_scatter_csv(content: bytes) -> bytes | None:
    text = content.decode("utf-8")
    sample = text[:4096]
    dialect = csv.Sniffer().sniff(sample, delimiters=";,")
    rows = list(csv.reader(io.StringIO(text, newline=""), dialect))
    if not rows:
        return None
    header = rows[0]
    y_index = None
    if "y" in header:
        y_index = header.index("y")
    elif "value" in header:
        y_index = header.index("value")
    y_sim_index = header.index("y_sim") if "y_sim" in header else None
    if y_index is None or y_sim_index is None:
        return None
    scatter_header = ["y", "y_sim"]
    scatter_rows = [[row[y_index], row[y_sim_index]] for row in rows[1:]]
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(scatter_header)
    writer.writerows(scatter_rows)
    return output.getvalue().encode("utf-8")


def read_zip_members(zip_bytes: bytes) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            normalized = safe_member_path(info.filename)
            basename = normalized.name
            if basename in members:
                raise ValueError(f"Duplicate ZIP member path: {basename}")
            members[basename] = zf.read(info.filename)
    return members


def augment_results_archive(zip_bytes: bytes) -> bytes:
    members = read_zip_members(zip_bytes)
    if _SCATTER_CSV in members:
        return zip_bytes
    results = members.get(_RESULTS_CSV)
    if results is None:
        raise ValueError("System Discovery results archive is missing results.csv")
    normalized_results = postprocess_results_csv(results)
    members[_RESULTS_CSV] = normalized_results
    scatter = generate_scatter_csv(normalized_results)
    if scatter is not None:
        members[_SCATTER_CSV] = scatter
    return zip_members(members)


def extract_workspace_artifacts(zip_bytes: bytes) -> dict[str, bytes]:
    found: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            normalized = safe_member_path(info.filename)
            basename = normalized.name
            if basename == _RESULTS_CSV:
                found[_RESULTS_CSV] = info.filename
            elif basename == _CDF_CSV:
                found[_CDF_CSV] = info.filename
            elif basename in {_METADATA_JSON, "evaluation.json"}:
                found[_METADATA_JSON] = info.filename

        missing = {_RESULTS_CSV, _CDF_CSV, _METADATA_JSON} - set(found)
        if missing:
            raise ValueError(
                "System Discovery results archive is missing: "
                + ", ".join(sorted(missing))
            )
        return {
            target: zf.read(member_name)
            for target, member_name in found.items()
        }


def artifact_bounds(content: bytes, artifact_name: str) -> tuple[float, float] | None:
    if artifact_name not in {_RESULTS_CSV, _CDF_CSV, _SCATTER_CSV}:
        return None
    try:
        text = content.decode("utf-8", errors="replace")
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        rows = list(csv.reader(io.StringIO(text, newline=""), dialect))
        if len(rows) < 2:
            return None
        data_min = None
        data_max = None
        for row in rows[1:]:
            for cell in row:
                try:
                    value = float(cell)
                except (ValueError, TypeError):
                    continue
                if data_min is None or value < data_min:
                    data_min = value
                if data_max is None or value > data_max:
                    data_max = value
        if data_min is None or data_max is None:
            return None
        return (data_min, data_max)
    except Exception:
        return None


def zip_members(members: dict[str, bytes]) -> bytes:
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(
            buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for name in sorted(members):
                target.writestr(name, members[name])
        return buffer.getvalue()


def safe_member_path(name: str) -> Path:
    normalized = Path(name)
    if normalized.is_absolute() or normalized.as_posix().startswith("/"):
        raise ValueError(f"Unsafe ZIP member path: {name}")
    if ".." in normalized.parts:
        raise ValueError(f"Unsafe ZIP member path: {name}")
    return normalized


def metadata_from_payload(
    payload: dict[str, Any],
) -> SystemDiscoveryTrainingEvaluationMetadata:
    metrics = _object(payload.get("metrics"))
    evaluation = _object(payload.get("evaluation"))
    nse_eval = _object(evaluation.get("nse"))
    return SystemDiscoveryTrainingEvaluationMetadata(
        analysis=_optional_str(payload.get("analysis")),
        sample_size=_format_value(metrics.get("sample_size")),
        nse=_metric_from_payload(_object(metrics.get("nse"))),
        rmse=_metric_from_payload(_object(metrics.get("rmse"))),
        nrmse=_metric_from_payload(_object(metrics.get("nrmse"))),
        pbias=_metric_from_payload(_object(metrics.get("pbias"))),
        p_value=_format_value(nse_eval.get("p_val")),
        categories=[
            _category_from_payload(_object(nse_eval.get(name)), fallback_label)
            for name, fallback_label in (
                ("very_good", "Very Good"),
                ("good", "Good"),
                ("acceptable", "Acceptable"),
                ("unsatisfactory", "Unsatisfactory"),
            )
        ],
    )


def _metric_from_payload(payload: dict[str, Any]) -> SystemDiscoveryEvaluationMetric:
    ci = _object(payload.get("ci"))
    ci_range = ci.get("range")
    confidence_interval = None
    if isinstance(ci_range, list) and len(ci_range) == 2:
        confidence_interval = (
            f"{_format_value(ci_range[0])} - {_format_value(ci_range[1])}"
        )
    return SystemDiscoveryEvaluationMetric(
        value=_format_value(payload.get("val")),
        confidence_interval=confidence_interval,
        confidence_level=_format_percent(ci.get("level"))
        if ci.get("level") is not None
        else None,
        confidence_method=_optional_str(ci.get("type")),
        note=_optional_str(payload.get("note")),
    )


def _category_from_payload(
    payload: dict[str, Any],
    fallback_label: str,
) -> SystemDiscoveryEvaluationCategory:
    return SystemDiscoveryEvaluationCategory(
        label=_optional_str(payload.get("label")) or fallback_label,
        probability=_format_percent(payload.get("prob")),
    )


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _format_percent(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{value * 100:.2f}%"
    return str(value)


def load_evaluation_metadata(payload_bytes: bytes) -> SystemDiscoveryTrainingEvaluationMetadata:
    payload = json.loads(payload_bytes)
    if not isinstance(payload, dict):
        raise ValueError(
            "System Discovery evaluation metadata must be a JSON object"
        )
    return metadata_from_payload(payload)