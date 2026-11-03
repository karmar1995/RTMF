from __future__ import annotations

import io
import zipfile
from collections import OrderedDict

from adapters.system_discovery_aistor_adapter.client import SystemDiscoveryAIStorClient
from adapters.system_discovery_aistor_adapter.errors import SystemDiscoveryAIStorObjectNotFoundError
from adapters.system_discovery_aistor_adapter.mapping import training_results_key
from adapters.system_discovery_training_results_storage.filesystem_storage import (
    _external_control_signal_members,
    model_simulation_members,
    prepare_results_csv_zip as _prepare_results_csv_zip,
)
from adapters.system_discovery_training_results_storage.processing import (
    artifact_bounds,
    augment_results_archive,
    extract_workspace_artifacts,
    load_evaluation_metadata,
    read_zip_members,
    zip_members,
)
from use_case_contracts.dtos import SystemDiscoveryTrainingEvaluationMetadata
from use_case_contracts.ports import SystemDiscoveryTrainingResultsStoragePort

_ARCHIVE_NAME = "results.zip"
_RESULTS_CSV = "results.csv"
_CDF_CSV = "cdf.csv"
_SCATTER_CSV = "scatter.csv"
_METADATA_JSON = "metadata.json"

_ARTIFACT_NAMES = frozenset({_RESULTS_CSV, _CDF_CSV, _SCATTER_CSV})

_LEGACY_TRAINING_MEMBERS = (
    "results.csv",
    "cdf.csv",
    "scatter.csv",
    "evaluation.json",
    ".postprocessing",
    ".postprocessed",
)

_MAX_CACHED_WORKSPACES = 32


class AIStorSystemDiscoveryTrainingResultsStorage(
    SystemDiscoveryTrainingResultsStoragePort
):
    def __init__(self, client: SystemDiscoveryAIStorClient) -> None:
        self._client = client
        self._members_cache: OrderedDict[str, dict[str, bytes]] = OrderedDict()

    def store_results_archive(self, training_id: str, content: bytes) -> str:
        key = training_results_key(training_id)
        if self._client.object_exists(key=key):
            return key
        augmented = augment_results_archive(content)
        self._client.upload_bytes(
            key=key,
            content=augmented,
            content_type="application/zip",
        )
        self._members_cache.pop(training_id, None)
        return key

    def normalize_results_archive_key(
        self,
        training_id: str,
        stored_reference: str,
    ) -> str:
        canonical = training_results_key(training_id)
        if not self._client.object_exists(key=canonical):
            return stored_reference
        return canonical

    def start_evaluation_postprocessing(
        self, training_id: str, archive_key: str
    ) -> str:
        return self.get_evaluation_postprocessing_status(training_id)

    def get_evaluation_postprocessing_status(self, training_id: str) -> str:
        try:
            self._load_members(training_id)
        except Exception:
            return "missing"
        return "ready"

    def get_evaluation_metadata(
        self,
        training_id: str,
    ) -> SystemDiscoveryTrainingEvaluationMetadata:
        members = self._load_members(training_id)
        content = members.get(_METADATA_JSON)
        if content is None:
            raise SystemDiscoveryAIStorObjectNotFoundError(
                f"System Discovery training workspace '{training_id}' has no {_METADATA_JSON}"
            )
        return load_evaluation_metadata(content)

    def get_evaluation_artifact_zip(
        self, training_id: str, artifact_name: str
    ) -> bytes:
        if artifact_name not in _ARTIFACT_NAMES:
            raise ValueError(f"Unsupported evaluation artifact '{artifact_name}'")
        members = self._load_members(training_id)
        content = members.get(artifact_name)
        if content is None:
            raise SystemDiscoveryAIStorObjectNotFoundError(
                f"System Discovery training workspace '{training_id}' has no {artifact_name}"
            )
        with io.BytesIO() as buffer:
            with zipfile.ZipFile(
                buffer, mode="w", compression=zipfile.ZIP_DEFLATED
            ) as zf:
                zf.writestr(artifact_name, content)
            return buffer.getvalue()

    def get_evaluation_artifact_bounds(
        self, training_id: str, artifact_name: str
    ) -> tuple[float, float] | None:
        if artifact_name not in _ARTIFACT_NAMES:
            return None
        try:
            members = self._load_members(training_id)
        except Exception:
            return None
        content = members.get(artifact_name)
        if content is None:
            return None
        return artifact_bounds(content, artifact_name)

    def can_save_evaluation_workspace(self, training_id: str, archive_key: str) -> bool:
        try:
            self._load_members(training_id)
            return True
        except Exception:
            return False

    def build_model_simulation_archive(
        self,
        training_id: str,
        archive_key: str,
        external_control_signals_archive: bytes | None = None,
    ) -> bytes:
        key = training_results_key(training_id)
        if not self._client.object_exists(key=key):
            raise ValueError(
                "System Discovery training results archive is missing"
            )
        model_members = model_simulation_members(self._client.download_bytes(key=key))
        if external_control_signals_archive is None:
            return zip_members(model_members)

        external_members = _external_control_signal_members(
            external_control_signals_archive
        )
        return zip_members({**model_members, **external_members})

    def remove_training_workspace(self, training_id: str) -> None:
        self._members_cache.pop(training_id, None)
        self._remove_training_objects(training_id, include_legacy_members=True)

    def prepare_results_csv_zip(self, results_archive: bytes) -> bytes:
        return _prepare_results_csv_zip(results_archive)

    def _load_members(self, training_id: str) -> dict[str, bytes]:
        cached = self._members_cache.get(training_id)
        if cached is not None:
            self._members_cache.move_to_end(training_id)
            return cached
        content = self._client.download_bytes(key=training_results_key(training_id))
        extract_workspace_artifacts(content)
        members = read_zip_members(content)
        if len(self._members_cache) >= _MAX_CACHED_WORKSPACES:
            self._members_cache.popitem(last=False)
        self._members_cache[training_id] = members
        return members

    def _remove_training_objects(
        self,
        training_id: str,
        *,
        include_legacy_members: bool,
    ) -> None:
        prefix = training_results_key(training_id).rsplit("/", 1)[0]
        keys = [f"{prefix}/{_ARCHIVE_NAME}"]
        if include_legacy_members:
            keys.extend(f"{prefix}/{member}" for member in _LEGACY_TRAINING_MEMBERS)
        for key in keys:
            self._client.remove_object(key=key)