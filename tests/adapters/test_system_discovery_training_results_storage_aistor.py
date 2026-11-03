from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest

from adapters.system_discovery_aistor_adapter import SystemDiscoveryAIStorInvalidObjectKeyError
from adapters.system_discovery_aistor_adapter.client import SystemDiscoveryAIStorClient
from adapters.system_discovery_aistor_adapter.config import SystemDiscoveryAIStorConfig
from adapters.system_discovery_training_results_storage import (
    AIStorSystemDiscoveryTrainingResultsStorage,
)


class FakeNoSuchKeyError(Exception):
    pass


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self) -> bytes:
        return self._content

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        pass


class FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.puts: list[tuple[str, str, bytes]] = []
        self.gets: list[tuple[str, str]] = []
        self.stats: list[tuple[str, str]] = []
        self.removes: list[tuple[str, str]] = []

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def put_object(self, bucket, key, data, length, content_type):
        content = data.read()
        self.objects[(bucket, key)] = content
        self.puts.append((bucket, key, content))
        return object()

    def get_object(self, bucket, key):
        self.gets.append((bucket, key))
        if (bucket, key) not in self.objects:
            raise FakeNoSuchKeyError(key)
        return FakeResponse(self.objects[(bucket, key)])

    def stat_object(self, bucket, key):
        self.stats.append((bucket, key))
        if (bucket, key) not in self.objects:
            raise FakeNoSuchKeyError(key)
        return object()

    def remove_object(self, bucket, key):
        self.removes.append((bucket, key))
        self.objects.pop((bucket, key), None)

    def keys_for(self, bucket: str, prefix: str) -> list[str]:
        return [
            key
            for (b, key) in self.objects
            if b == bucket and key.startswith(prefix)
        ]


def _storage(tmp_path):
    fake = FakeMinio()
    config = SystemDiscoveryAIStorConfig(
        endpoint="127.0.0.1:9000",
        secure=False,
        access_key="minio",
        secret_key="password",
        system_discovery_results_bucket="system-discovery",
    )
    client = SystemDiscoveryAIStorClient(config=config, client=fake)
    storage = AIStorSystemDiscoveryTrainingResultsStorage(client=client)
    return storage, fake


def _bucket_objects(fake: FakeMinio, training_id: str) -> dict[str, bytes]:
    bucket = "system-discovery"
    prefix = f"system-discovery/trainings/{training_id}/"
    return {
        key: content
        for (b, key), content in fake.objects.items()
        if b == bucket and key.startswith(prefix)
    }


def test_given_results_archive_when_stored_then_single_augmented_zip_is_uploaded_under_training_results_subfolder(
    tmp_path,
) -> None:
    storage, fake = _storage(tmp_path)

    key = storage.store_results_archive("train-1", _archive_bytes())

    assert key == "system-discovery/trainings/train-1/results.zip"
    assert list(_bucket_objects(fake, "train-1")) == [key]
    contents = _zip_contents(fake.objects[("system-discovery", key)])
    assert "scatter.csv" not in contents
    assert contents["cdf.csv"].decode("utf-8").startswith("x;y")
    assert contents["metadata.json"].startswith(b"{")


def test_given_results_with_simulated_series_when_stored_then_scatter_csv_is_baked_into_the_zip(
    tmp_path,
) -> None:
    storage, fake = _storage(tmp_path)

    key = storage.store_results_archive(
        "train-1",
        _archive_bytes(results="y;y_sim\n1.5;2.5\n3.5;4.0\n"),
    )

    contents = _zip_contents(fake.objects[("system-discovery", key)])
    assert contents["scatter.csv"].decode("utf-8").splitlines() == [
        "y;y_sim",
        "1.5;2.5",
        "3.5;4.0",
    ]
    rows = list(
        csv.reader(io.StringIO(contents["results.csv"].decode("utf-8"), newline=""), delimiter=";")
    )
    assert rows == [
        ["time", "y", "y_sim"],
        ["0", "1.5", "2.5"],
        ["1", "3.5", "4.0"],
    ]


def test_given_archive_already_stored_when_stored_again_then_existing_object_is_not_overwritten(
    tmp_path,
) -> None:
    storage, fake = _storage(tmp_path)

    first = storage.store_results_archive("train-1", _archive_bytes())
    second = storage.store_results_archive(
        "train-1",
        _archive_bytes(results="y;y_sim\n1.5;2.5\n3.5;4.0\n"),
    )

    assert first == second
    assert "scatter.csv" not in _zip_contents(fake.objects[("system-discovery", first)])


def test_given_already_augmented_archive_when_stored_again_then_scatter_is_not_duplicated(
    tmp_path,
) -> None:
    storage, fake = _storage(tmp_path)
    first_key = storage.store_results_archive(
        "train-1",
        _archive_bytes(results="y;y_sim\n1.5;2.5\n3.5;4.0\n"),
    )
    augmented = fake.objects[("system-discovery", first_key)]

    second_key = storage.store_results_archive("train-2", augmented)

    assert fake.objects[("system-discovery", second_key)] == augmented


@pytest.mark.parametrize("training_id", ["../bad", "bad/id", "", "."])
def test_unsafe_training_ids_do_not_escape_object_namespace(training_id, tmp_path) -> None:
    storage, _fake = _storage(tmp_path)

    with pytest.raises(SystemDiscoveryAIStorInvalidObjectKeyError):
        storage.store_results_archive(training_id, _archive_bytes())


def test_given_invalid_zip_when_stored_then_invalid_archive_is_rejected(tmp_path) -> None:
    storage, _fake = _storage(tmp_path)

    with pytest.raises(zipfile.BadZipFile):
        storage.store_results_archive("train-1", b"not-a-zip")


def test_given_stored_workspace_when_status_requested_then_ready_without_marker_objects(
    tmp_path,
) -> None:
    storage, fake = _storage(tmp_path)
    key = storage.store_results_archive("train-1", _archive_bytes())

    assert storage.get_evaluation_postprocessing_status("train-1") == "ready"
    assert storage.start_evaluation_postprocessing("train-1", key) == "ready"

    assert list(_bucket_objects(fake, "train-1")) == [
        "system-discovery/trainings/train-1/results.zip"
    ]


def test_given_unknown_training_when_status_requested_then_missing(tmp_path) -> None:
    storage, _fake = _storage(tmp_path)

    assert storage.get_evaluation_postprocessing_status("train-1") == "missing"


def test_given_stored_workspace_when_metadata_loaded_then_typed_metadata_is_returned(
    tmp_path,
) -> None:
    storage, _fake = _storage(tmp_path)
    storage.store_results_archive("train-1", _archive_bytes())

    metadata = storage.get_evaluation_metadata("train-1")

    assert metadata.sample_size == "50"
    assert metadata.nse.value == "0.9697"
    assert metadata.nse.confidence_interval == "0.9479 - 0.9815"


def test_given_stored_workspace_when_artifact_zip_loaded_then_csv_is_wrapped(tmp_path) -> None:
    storage, _fake = _storage(tmp_path)
    storage.store_results_archive("train-1", _archive_bytes())

    archive = storage.get_evaluation_artifact_zip("train-1", "results.csv")

    with zipfile.ZipFile(io.BytesIO(archive), mode="r") as zf:
        assert zf.namelist() == ["results.csv"]
        assert b"y" in zf.read("results.csv")


def test_given_stored_workspace_when_artifact_bounds_loaded_then_bounds_are_computed(
    tmp_path,
) -> None:
    storage, _fake = _storage(tmp_path)
    storage.store_results_archive(
        "train-1",
        _archive_bytes(results="y;y_sim\n1.5;2.5\n3.5;4.0\n"),
    )

    assert storage.get_evaluation_artifact_bounds("train-1", "scatter.csv") == (1.5, 4.0)
    assert storage.get_evaluation_artifact_bounds("train-1", "results.zip") is None


def test_given_training_without_scatter_when_scatter_bounds_requested_then_none_is_returned(
    tmp_path,
) -> None:
    storage, _fake = _storage(tmp_path)
    storage.store_results_archive("train-1", _archive_bytes())

    assert storage.get_evaluation_artifact_bounds("train-1", "scatter.csv") is None


def test_can_save_evaluation_workspace_reflects_stored_workspace(tmp_path) -> None:
    storage, _fake = _storage(tmp_path)
    key = storage.store_results_archive("train-1", _archive_bytes())

    assert storage.can_save_evaluation_workspace("train-1", key) is True
    assert storage.can_save_evaluation_workspace("unknown", key) is False


def test_build_model_simulation_archive_selects_only_model_members_from_training_archive(
    tmp_path,
) -> None:
    storage, _fake = _storage(tmp_path)
    storage.store_results_archive(
        "train-1",
        _archive_bytes(
            extra={
                "model.syspy": "model-bytes",
                "initial_conditions.json": "[1, 2]",
                "unrelated.txt": "not-a-model-member",
            }
        ),
    )

    archive = storage.build_model_simulation_archive("train-1", "<any-key>")

    contents = _zip_contents(archive)
    assert contents == {
        "initial_conditions.json": b"[1, 2]",
        "model.syspy": b"model-bytes",
    }


def test_build_model_simulation_archive_with_external_control_signals_adds_data_csv(
    tmp_path,
) -> None:
    storage, _fake = _storage(tmp_path)
    storage.store_results_archive(
        "train-1",
        _archive_bytes(extra={"model.syspy": "model-bytes"}),
    )

    external_buffer = io.BytesIO()
    with zipfile.ZipFile(external_buffer, mode="w") as zf:
        zf.writestr("data.csv", "x;y\n1;2\n")

    archive = storage.build_model_simulation_archive(
        "train-1",
        "<any-key>",
        external_control_signals_archive=external_buffer.getvalue(),
    )

    contents = _zip_contents(archive)
    assert contents == {
        "model.syspy": b"model-bytes",
        "data.csv": b"x;y\n1;2\n",
    }


def test_build_model_simulation_archive_without_syspy_raises(tmp_path) -> None:
    storage, _fake = _storage(tmp_path)
    storage.store_results_archive("train-1", _archive_bytes())

    with pytest.raises(ValueError):
        storage.build_model_simulation_archive("train-1", "<any-key>")


def test_build_model_simulation_archive_missing_object_raises(tmp_path) -> None:
    storage, _fake = _storage(tmp_path)

    with pytest.raises(ValueError):
        storage.build_model_simulation_archive("unknown", "<any-key>")


def test_given_training_workspace_when_removed_then_aistor_objects_are_deleted(tmp_path) -> None:
    storage, fake = _storage(tmp_path)
    key = storage.store_results_archive("train-1", _archive_bytes())
    prefix = key.rsplit("/", 1)[0]
    bucket = "system-discovery"
    fake.objects[(bucket, f"{prefix}/scatter.csv")] = b"legacy"

    storage.remove_training_workspace("train-1")

    assert _bucket_objects(fake, "train-1") == {}


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


def _zip_contents(archive: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(archive), mode="r") as zf:
        return {name: zf.read(name) for name in zf.namelist()}