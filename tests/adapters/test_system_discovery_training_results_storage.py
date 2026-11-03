from __future__ import annotations

import csv
import io
import json
import warnings
import zipfile

import pytest

from adapters.system_discovery_training_results_storage import (
    FilesystemSystemDiscoveryTrainingResultsStorage,
)


def test_given_training_id_with_path_separators_when_archive_stored_then_safe_zip_inside_per_training_directory(
    tmp_path,
) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))

    path = storage.store_results_archive("../unsafe/train-1", _archive_bytes())

    assert "/" in path
    stored = tmp_path / path
    assert stored.parent.parent == tmp_path
    assert stored.name == "results.zip"
    assert ".." not in stored.parent.name
    assert "unsafe/train-1" not in stored.parent.name
    assert _zip_contents(stored.read_bytes()).keys() >= {"results.csv", "cdf.csv", "metadata.json"}


def test_given_archive_already_exists_when_stored_again_then_existing_file_is_not_overwritten(
    tmp_path,
) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    first_bytes = _archive_bytes()
    other_bytes = _archive_bytes(results="y;y_sim\n1.5;2.5\n3.5;4.0\n")

    first_path = storage.store_results_archive("train-1", first_bytes)
    second_path = storage.store_results_archive("train-1", other_bytes)

    assert first_path == second_path
    assert "scatter.csv" not in _zip_contents((tmp_path / first_path).read_bytes())
    assert (tmp_path / first_path).read_bytes() != other_bytes


def test_given_legacy_flat_archive_when_normalized_then_archive_is_copied_into_training_directory(
    tmp_path,
) -> None:
    legacy_bytes = _archive_bytes()
    legacy = tmp_path / "system-discovery-training-old.zip"
    legacy.write_bytes(legacy_bytes)
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))

    key = storage.normalize_results_archive_key("train-1", str(legacy))

    assert key.endswith("/results.zip")
    assert (tmp_path / key).read_bytes() == legacy_bytes


def test_given_training_workspace_when_removed_then_only_training_directory_is_deleted(
    tmp_path,
) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    key = storage.store_results_archive("../unsafe/train-1", _archive_bytes())
    training_dir = (tmp_path / key).parent

    storage.remove_training_workspace("../unsafe/train-1")
    storage.remove_training_workspace("../unsafe/train-1")

    assert not training_dir.exists()
    assert tmp_path.exists()


def test_given_completed_archive_when_stored_then_workspace_is_ready_and_results_gain_time(
    tmp_path,
) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    key = storage.store_results_archive("train-1", _archive_bytes())

    assert storage.get_evaluation_postprocessing_status("train-1") == "ready"
    assert storage.start_evaluation_postprocessing("train-1", key) == "ready"

    with zipfile.ZipFile(tmp_path / key, mode="r") as zf:
        rows = list(
            csv.reader(
                io.StringIO(zf.read("results.csv").decode("utf-8"), newline=""),
                delimiter=";",
            )
        )
        assert zf.read("cdf.csv").decode("utf-8").startswith("x;y")
        assert zf.read("metadata.json").startswith(b"{")

    assert rows == [
        ["time", "x1", "y"],
        ["0", "1.0", "2.0"],
        ["1", "3.0", "4.0"],
    ]


def test_given_results_has_y_and_y_sim_when_stored_then_scatter_csv_is_added_inside_archive(
    tmp_path,
) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    key = storage.store_results_archive(
        "train-1",
        _archive_bytes(results="y;y_sim\n1.5;2.5\n3.5;4.0\n"),
    )

    with zipfile.ZipFile(tmp_path / key, mode="r") as zf:
        assert zf.read("scatter.csv").decode("utf-8").splitlines() == [
            "y;y_sim",
            "1.5;2.5",
            "3.5;4.0",
        ]


def test_given_results_already_has_time_when_stored_then_time_column_is_not_duplicated(
    tmp_path,
) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    key = storage.store_results_archive(
        "train-1",
        _archive_bytes(results="time;x1;y\n10;1.0;2.0\n11;3.0;4.0\n"),
    )

    with zipfile.ZipFile(tmp_path / key, mode="r") as zf:
        assert zf.read("results.csv").decode("utf-8").splitlines() == [
            "time;x1;y",
            "0;1.0;2.0",
            "1;3.0;4.0",
        ]


def test_given_results_has_time_not_first_when_stored_then_time_is_moved_not_duplicated(
    tmp_path,
) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    key = storage.store_results_archive(
        "train-1",
        _archive_bytes(results="x1;time;y\n1.0;10;2.0\n3.0;11;4.0\n"),
    )

    with zipfile.ZipFile(tmp_path / key, mode="r") as zf:
        assert zf.read("results.csv").decode("utf-8").splitlines() == [
            "time;x1;y",
            "0;1.0;2.0",
            "1;3.0;4.0",
        ]


def test_given_already_augmented_archive_when_stored_again_then_scatter_is_not_duplicated(
    tmp_path,
) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    first = storage.store_results_archive(
        "train-1",
        _archive_bytes(results="y;y_sim\n1.5;2.5\n3.5;4.0\n"),
    )
    augmented = (tmp_path / first).read_bytes()

    second = storage.store_results_archive(
        "train-2",
        augmented,
    )

    assert (tmp_path / second).read_bytes() == augmented


def test_given_invalid_zip_when_stored_then_invalid_archive_is_rejected(tmp_path) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))

    with pytest.raises(zipfile.BadZipFile):
        storage.store_results_archive("train-1", b"not-a-zip")


def test_given_zip_slip_archive_when_stored_then_unsafe_member_is_rejected(tmp_path) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))

    with pytest.raises(ValueError, match="Unsafe ZIP member path"):
        storage.store_results_archive(
            "train-1",
            _archive_bytes(extra={"../evil": "x"}),
        )

    assert not (tmp_path / "evil").exists()
    assert not (tmp_path / "train-1" / "results.zip").exists()


def test_given_metadata_json_when_loaded_then_typed_metadata_is_returned(tmp_path) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    storage.store_results_archive("train-1", _archive_bytes())

    metadata = storage.get_evaluation_metadata("train-1")

    assert metadata.sample_size == "50"
    assert metadata.nse.value == "0.9697"
    assert metadata.nse.confidence_interval == "0.9479 - 0.9815"
    assert metadata.nse.confidence_level == "95.00%"
    assert metadata.nse.confidence_method == "BCa"
    assert metadata.pbias.note == "Overestimation"
    assert metadata.p_value == "0.0000"
    assert [(item.label, item.probability) for item in metadata.categories] == [
        ("Very Good", "100.00%"),
        ("Good", "0.00%"),
        ("Acceptable", "0.00%"),
        ("Unsatisfactory", "0.00%"),
    ]


def test_given_stored_workspace_when_artifact_zip_loaded_then_csv_is_wrapped(tmp_path) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    storage.store_results_archive("train-1", _archive_bytes())

    archive = storage.get_evaluation_artifact_zip("train-1", "results.csv")

    with zipfile.ZipFile(io.BytesIO(archive), mode="r") as zf:
        assert zf.namelist() == ["results.csv"]
        assert b"y" in zf.read("results.csv")


def test_given_stored_workspace_when_artifact_bounds_loaded_then_bounds_are_computed(
    tmp_path,
) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    storage.store_results_archive(
        "train-1",
        _archive_bytes(results="y;y_sim\n1.5;2.5\n3.5;4.0\n"),
    )

    assert storage.get_evaluation_artifact_bounds("train-1", "scatter.csv") == (1.5, 4.0)
    assert storage.get_evaluation_artifact_bounds("train-1", "results.zip") is None


def test_build_model_simulation_archive_selects_only_model_members_from_training_archive(
    tmp_path,
) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    key = storage.store_results_archive(
        "train-1",
        _archive_bytes(
            extra={
                "models/model.syspy": "model-bytes",
                "initial_conditions.json": "[1, 2]",
            },
        ),
    )

    archive = storage.build_model_simulation_archive("train-1", key)

    contents = _zip_contents(archive)
    assert contents == {
        "initial_conditions.json": b"[1, 2]",
        "model.syspy": b"model-bytes",
    }


def test_build_model_simulation_archive_with_external_control_signals_adds_data_csv(
    tmp_path,
) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    key = storage.store_results_archive(
        "train-1",
        _archive_bytes(
            extra={
                "models/model.syspy": "model-bytes",
                "initial_conditions.json": "[1, 2]",
            },
        ),
    )
    control_archive = _zip_bytes({"data.csv": b"time;u\n0;1\n"})

    archive = storage.build_model_simulation_archive(
        "train-1",
        key,
        external_control_signals_archive=control_archive,
    )

    contents = _zip_contents(archive)
    assert contents["data.csv"] == b"time;u\n0;1\n"
    assert contents["model.syspy"] == b"model-bytes"
    assert contents["initial_conditions.json"] == b"[1, 2]"


def test_build_model_simulation_archive_without_syspy_raises(tmp_path) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))
    key = storage.store_results_archive(
        "train-1",
        _archive_bytes(extra={"initial_conditions.json": "[1, 2]"}),
    )

    with pytest.raises(ValueError, match="no trained model"):
        storage.build_model_simulation_archive("train-1", key)


def test_build_model_simulation_archive_missing_archive_raises(tmp_path) -> None:
    storage = FilesystemSystemDiscoveryTrainingResultsStorage(str(tmp_path))

    with pytest.raises(ValueError, match="archive is missing"):
        storage.build_model_simulation_archive("train-1", "nonexistent-key")


def _archive_bytes(
    *,
    results: str = "x1;y\n1.0;2.0\n3.0;4.0\n",
    extra: dict[str, str] | None = None,
) -> bytes:
    metadata = {
        "analysis": "Model evaluation based on 50 samples.",
        "metrics": {
            "sample_size": 50,
            "nse": {
                "val": 0.9697138160784027,
                "ci": {"range": [0.9479368711006103, 0.981480148047594], "level": 0.95, "type": "BCa"},
            },
            "rmse": {
                "val": 0.12726276521817773,
                "ci": {"range": [0.10708856847375804, 0.15546229181439916], "level": 0.95, "type": "BCa"},
            },
            "nrmse": {"val": 17.402926168204388},
            "pbias": {"val": 0.36077484469656934, "note": "Overestimation"},
        },
        "evaluation": {
            "nse": {
                "very_good": {"label": "Very Good", "prob": 1.0},
                "good": {"label": "Good", "prob": 0.0},
                "acceptable": {"label": "Acceptable", "prob": 0.0},
                "unsatisfactory": {"label": "Unsatisfactory", "prob": 0.0},
                "p_val": 0.0,
            }
        },
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        zf.writestr("results.csv", results)
        zf.writestr("cdf.csv", "x;y\n0.1;0.2\n")
        zf.writestr("metadata.json", json.dumps(metadata))
        for name, content in (extra or {}).items():
            zf.writestr(name, content)
    return buffer.getvalue()


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def _zip_contents(archive: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(archive), mode="r") as zf:
        return {name: zf.read(name) for name in zf.namelist()}
