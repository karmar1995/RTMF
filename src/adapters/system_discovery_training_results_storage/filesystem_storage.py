from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from adapters.system_discovery_training_results_storage.processing import (
    artifact_bounds,
    augment_results_archive,
    extract_workspace_artifacts,
    load_evaluation_metadata,
    read_zip_members,
    safe_member_path,
    zip_members,
)
from use_case_contracts.dtos import SystemDiscoveryTrainingEvaluationMetadata
from use_case_contracts.ports import SystemDiscoveryTrainingResultsStoragePort

_ARCHIVE_NAME = "results.zip"
_RESULTS_CSV = "results.csv"
_CDF_CSV = "cdf.csv"
_SCATTER_CSV = "scatter.csv"
_METADATA_JSON = "metadata.json"
_STORAGE_KEY_SEPARATOR = "/"
_DATA_CSV = "data.csv"
_INITIAL_CONDITIONS_JSON = "initial_conditions.json"
_MAX_EXTERNAL_CONTROL_ARCHIVE_BYTES = 50 * 1024 * 1024
_MAX_EXTERNAL_CONTROL_MEMBERS = 10
_MAX_EXTERNAL_CONTROL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024

_ARTIFACT_NAMES = frozenset({_RESULTS_CSV, _CDF_CSV, _SCATTER_CSV})


class FilesystemSystemDiscoveryTrainingResultsStorage(
    SystemDiscoveryTrainingResultsStoragePort
):
    def __init__(self, directory: str) -> None:
        root = Path(directory).expanduser()
        if not str(root).strip():
            raise RuntimeError(
                "Missing System Discovery training results storage directory"
            )
        self._root = root

    def store_results_archive(self, training_id: str, content: bytes) -> str:
        self._root.mkdir(parents=True, exist_ok=True)
        training_dir = self._training_dir(training_id)
        training_dir.mkdir(parents=True, exist_ok=True)
        target = training_dir / _ARCHIVE_NAME
        if target.exists():
            return self._storage_key(training_id, target.name)
        self._write_member_atomically(target, augment_results_archive(content))
        return self._storage_key(training_id, target.name)

    def normalize_results_archive_key(
        self,
        training_id: str,
        stored_reference: str,
    ) -> str:
        target_dir = self._training_dir(training_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        expected_key = self._storage_key(training_id, _ARCHIVE_NAME)
        expected_path = self._path_from_storage_key(expected_key)
        if expected_path.exists():
            return expected_key

        source = self._path_from_reference(training_id, stored_reference)
        if source == expected_path:
            return expected_key
        if not source.exists():
            return stored_reference
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{expected_path.stem}-",
            suffix=".tmp",
            dir=str(target_dir),
        )
        os.close(fd)
        try:
            shutil.copyfile(source, temp_name)
            os.replace(temp_name, expected_path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        return expected_key

    def start_evaluation_postprocessing(
        self, training_id: str, archive_key: str
    ) -> str:
        return self.get_evaluation_postprocessing_status(training_id)

    def get_evaluation_postprocessing_status(self, training_id: str) -> str:
        try:
            self._read_workspace_members(self._training_dir(training_id))
            return "ready"
        except Exception:
            return "missing"

    def get_evaluation_metadata(
        self,
        training_id: str,
    ) -> SystemDiscoveryTrainingEvaluationMetadata:
        members = self._read_workspace_members(self._training_dir(training_id))
        content = members.get(_METADATA_JSON)
        if content is None:
            raise FileNotFoundError(
                f"System Discovery training workspace '{training_id}' has no {_METADATA_JSON}"
            )
        return load_evaluation_metadata(content)

    def get_evaluation_artifact_zip(
        self, training_id: str, artifact_name: str
    ) -> bytes:
        if artifact_name not in _ARTIFACT_NAMES:
            raise ValueError(f"Unsupported evaluation artifact '{artifact_name}'")
        members = self._read_workspace_members(self._training_dir(training_id))
        content = members.get(artifact_name)
        if content is None:
            raise FileNotFoundError(
                f"System Discovery training workspace '{training_id}' has no {artifact_name}"
            )
        return zip_members({artifact_name: content})

    def get_evaluation_artifact_bounds(
        self, training_id: str, artifact_name: str
    ) -> tuple[float, float] | None:
        if artifact_name not in _ARTIFACT_NAMES:
            return None
        try:
            members = self._read_workspace_members(self._training_dir(training_id))
        except Exception:
            return None
        content = members.get(artifact_name)
        if content is None:
            return None
        return artifact_bounds(content, artifact_name)

    def can_save_evaluation_workspace(self, training_id: str, archive_key: str) -> bool:
        try:
            workspace = self._path_from_reference(training_id, archive_key).parent
            return self._workspace_has_required_artifacts(workspace)
        except Exception:
            return False

    def build_model_simulation_archive(
        self,
        training_id: str,
        archive_key: str,
        external_control_signals_archive: bytes | None = None,
    ) -> bytes:
        archive_path = self._path_from_reference(training_id, archive_key)
        if not archive_path.is_file():
            raise ValueError(
                "System Discovery training results archive is missing"
            )
        model_members = model_simulation_members(archive_path.read_bytes())
        if external_control_signals_archive is None:
            return zip_members(model_members)

        external_members = _external_control_signal_members(
            external_control_signals_archive
        )
        return zip_members({**model_members, **external_members})

    def remove_training_workspace(self, training_id: str) -> None:
        training_dir = self._training_dir(training_id)
        self._remove_directory_inside_root(training_dir, self._root)

    @staticmethod
    def _remove_directory_inside_root(path: Path, root: Path) -> None:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        if resolved_root not in (resolved_path, *resolved_path.parents):
            raise ValueError("System Discovery workspace path escaped storage root")
        if not resolved_path.exists():
            return
        if not resolved_path.is_dir():
            raise ValueError("System Discovery workspace path is not a directory")
        shutil.rmtree(resolved_path)

    def prepare_results_csv_zip(self, results_archive: bytes) -> bytes:
        return prepare_results_csv_zip(results_archive)

    @staticmethod
    def _read_workspace_members(workspace: Path) -> dict[str, bytes]:
        archive = workspace / _ARCHIVE_NAME
        content = archive.read_bytes()
        extract_workspace_artifacts(content)
        return read_zip_members(content)

    @staticmethod
    def _workspace_has_required_artifacts(workspace: Path) -> bool:
        archive = workspace / _ARCHIVE_NAME
        if not archive.is_file():
            return False
        try:
            extract_workspace_artifacts(archive.read_bytes())
            return True
        except Exception:
            return False

    def _write_member_atomically(
        self,
        target: Path,
        content: bytes,
    ) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.stem}-",
            suffix=".tmp",
            dir=str(target.parent),
        )
        try:
            with os.fdopen(fd, "wb") as temp_file:
                temp_file.write(content)
            os.replace(temp_name, target)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def _path_from_reference(self, training_id: str, stored_reference: str) -> Path:
        if self._is_storage_key(stored_reference):
            return self._path_from_storage_key(stored_reference)
        reference_path = Path(stored_reference).expanduser()
        if reference_path.is_absolute():
            resolved_root = self._root.resolve()
            resolved_reference = reference_path.resolve()
            if resolved_root not in (resolved_reference, *resolved_reference.parents):
                raise ValueError(
                    "Stored System Discovery archive path is outside storage root"
                )
            return resolved_reference
        legacy_path = self._root / stored_reference
        resolved_root = self._root.resolve()
        resolved_legacy = legacy_path.resolve()
        if resolved_root not in (resolved_legacy, *resolved_legacy.parents):
            raise ValueError(
                "Stored System Discovery archive path is outside storage root"
            )
        return resolved_legacy

    @staticmethod
    def _is_storage_key(stored_reference: str) -> bool:
        reference_path = Path(stored_reference)
        if reference_path.is_absolute():
            return False
        parts = stored_reference.split(_STORAGE_KEY_SEPARATOR)
        return len(parts) == 2 and bool(parts[0]) and parts[1] == _ARCHIVE_NAME

    def _path_from_storage_key(self, storage_key: str) -> Path:
        parts = storage_key.split(_STORAGE_KEY_SEPARATOR)
        if len(parts) != 2 or not parts[0] or parts[1] != _ARCHIVE_NAME:
            raise ValueError("Invalid System Discovery training results storage key")
        path = self._root / parts[0] / parts[1]
        resolved_root = self._root.resolve()
        resolved_path = path.resolve()
        if resolved_root not in (resolved_path, *resolved_path.parents):
            raise ValueError(
                "System Discovery training results storage key escaped root"
            )
        return resolved_path

    def _training_dir(self, training_id: str) -> Path:
        return self._root / self._safe_training_dir_name(training_id)

    def _storage_key(self, training_id: str, filename: str) -> str:
        return (
            f"{self._safe_training_dir_name(training_id)}"
            f"{_STORAGE_KEY_SEPARATOR}{filename}"
        )

    @staticmethod
    def _safe_training_dir_name(training_id: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", training_id).strip(".-")
        digest = hashlib.sha256(training_id.encode("utf-8")).hexdigest()
        prefix = normalized[:64] if normalized else "training"
        return f"{prefix}-{digest[:16]}"


def model_simulation_members(archive_bytes: bytes) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    model_artifacts = 0
    with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as source:
        for info in source.infolist():
            if info.is_dir():
                continue
            normalized = safe_member_path(info.filename)
            basename = normalized.name
            if basename.endswith(".syspy") or basename == _INITIAL_CONDITIONS_JSON:
                if basename in members:
                    raise ValueError(f"Duplicate ZIP member path: {basename}")
                members[basename] = source.read(info.filename)
                if basename.endswith(".syspy"):
                    model_artifacts += 1
    if model_artifacts == 0:
        raise ValueError(
            "System Discovery model archive has no trained model"
        )
    return members


def prepare_results_csv_zip(results_archive: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(results_archive), mode="r") as source:
        member_name: str | None = None
        for info in source.infolist():
            if info.is_dir():
                continue
            normalized = Path(info.filename)
            if normalized.is_absolute() or ".." in normalized.parts:
                raise ValueError(f"Unsafe ZIP member path: {info.filename}")
            if normalized.name == _RESULTS_CSV:
                member_name = info.filename
                break
        if member_name is None:
            raise ValueError(
                "System Discovery simulation results archive is missing results.csv"
            )
        content = source.read(member_name)
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(
            buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            target.writestr(_RESULTS_CSV, content)
        return buffer.getvalue()


def _external_control_signal_members(
    archive_bytes: bytes,
) -> dict[str, bytes]:
    if len(archive_bytes) > _MAX_EXTERNAL_CONTROL_ARCHIVE_BYTES:
        raise ValueError("External control-signal ZIP archive is too large.")
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as source:
            regular_members = [info for info in source.infolist() if not info.is_dir()]
            if len(regular_members) > _MAX_EXTERNAL_CONTROL_MEMBERS:
                raise ValueError(
                    "External control-signal ZIP archive has too many files."
                )
            seen: set[str] = set()
            data_member: zipfile.ZipInfo | None = None
            total_uncompressed = 0
            for info in regular_members:
                total_uncompressed += info.file_size
                if total_uncompressed > _MAX_EXTERNAL_CONTROL_UNCOMPRESSED_BYTES:
                    raise ValueError(
                        "External control-signal ZIP archive uncompressed content is too large."
                    )
                if Path(info.filename).name != _DATA_CSV:
                    continue
                normalized = safe_member_path(info.filename)
                name = normalized.as_posix()
                if name in seen or data_member is not None:
                    raise ValueError(
                        "External control-signal ZIP archive contains multiple data.csv files."
                    )
                seen.add(name)
                data_member = info
            if data_member is None:
                raise ValueError(
                    "External control-signal ZIP archive must contain exactly one data.csv file."
                )
            return {_DATA_CSV: source.read(data_member)}
    except zipfile.BadZipFile as exc:
        raise ValueError(
            "External control-signal archive must be a valid ZIP file."
        ) from exc