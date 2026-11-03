from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import partial
import json

import pytest

import use_case_contracts.dtos as dto_contracts
import use_case_contracts.messages as message_contracts
from adapters.system_discovery_rest_adapter.adapter import RestSystemDiscoveryAdapter
from adapters.system_discovery_training_registry.postgres_registry import (
    PostgresSystemDiscoveryTrainingRegistry,
    _json_nlags_x,
    _record_from_row,
    _saved_model_from_row,
)
from services.use_case.bus import InProcessBus
from services.use_case.composition.build_usecases import build_usecases
from services.use_case.handlers.system_discovery_training import (
    handle_cleanup_expired_system_discovery_training_queue_entries,
    handle_get_saved_system_discovery_model_details,
    handle_get_system_discovery_training_status,
    handle_list_system_discovery_trainings,
    handle_list_saved_system_discovery_models,
    handle_open_system_discovery_training_evaluation,
    handle_remove_saved_system_discovery_model,
    handle_remove_system_discovery_training_queue_entry,
    handle_save_system_discovery_model,
    handle_train_system_discovery,
)
from services.use_case.utils.plot_mapping import PlotMapping
from use_case_contracts.dtos import (
    ListSystemDiscoveryTrainingsResult,
    CleanupExpiredSystemDiscoveryTrainingQueueEntriesResult,
    SystemDiscoveryEvaluationCategory,
    SystemDiscoveryEvaluationMetric,
    SystemDiscoveryParameters,
    SystemDiscoverySavedModelRecord,
    SystemDiscoveryTrainingEvaluationMetadata,
    SystemDiscoveryTrainingEvaluationPlotState,
    SystemDiscoveryTrainingEvaluationState,
    SystemDiscoveryTrainingRecord,
    SystemDiscoveryTrainingResultsArchive,
    SystemDiscoveryTrainingState,
    SystemDiscoveryTrainingStatus,
    SystemDiscoveryTrainingSubmission,
    TrainSystemDiscoveryResult,
)
from use_case_contracts.errors import ExternalServiceError, NotFoundError
from use_case_contracts.messages import (
    CleanupExpiredSystemDiscoveryTrainingQueueEntries,
    GetSystemDiscoveryTrainingStatus,
    GetSavedSystemDiscoveryModelDetails,
    ListSavedSystemDiscoveryModels,
    ListSystemDiscoveryTrainings,
    OpenSystemDiscoveryTrainingEvaluation,
    RemoveSavedSystemDiscoveryModel,
    RemoveSystemDiscoveryTrainingQueueEntry,
    SaveSystemDiscoveryModel,
    TrainSystemDiscovery,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value


class FakeSystemDiscoveryPort:
    def __init__(self) -> None:
        self.submitted = []
        self.statuses = {}
        self.status_calls = []
        self.download_calls = []
        self.fail_status_ids = set()
        self.fail_download_ids = set()

    def submit_training(self, request):
        self.submitted.append(request)
        return SystemDiscoveryTrainingSubmission(training_id="train-1", status="queued")

    def get_training_status(self, training_id: str):
        self.status_calls.append(training_id)
        if training_id in self.fail_status_ids:
            raise RuntimeError("remote status failed")
        return self.statuses.get(
            training_id,
            SystemDiscoveryTrainingStatus(
                training_id=training_id,
                status="completed",
                training_status="done",
                evaluation_status="done",
                error=None,
            ),
        )

    def download_training_results(self, training_id: str):
        self.download_calls.append(training_id)
        if training_id in self.fail_download_ids:
            raise RuntimeError("download failed")
        return SystemDiscoveryTrainingResultsArchive(content=b"zip-bytes")


class FakeTrainingResultsStorage:
    def __init__(self) -> None:
        self.calls = []
        self.content_by_training_id = {}
        self.fail_ids = set()
        self.postprocessing_status = "missing"
        self.start_calls = []
        self.artifact_zip_calls = []
        self.can_save = True
        self.include_initial_conditions = True
        self.build_model_simulation_archive_calls = []
        self.removed_training_workspaces = []
        self.fail_remove_training_ids = set()

    def store_results_archive(self, training_id: str, content: bytes) -> str:
        self.calls.append(training_id)
        if training_id in self.fail_ids:
            raise RuntimeError("storage failed")
        self.content_by_training_id.setdefault(training_id, content)
        return f"{training_id}/results.zip"

    def normalize_results_archive_key(self, training_id: str, stored_reference: str) -> str:
        return stored_reference

    def start_evaluation_postprocessing(self, training_id: str, archive_key: str) -> str:
        self.start_calls.append((training_id, archive_key))
        self.postprocessing_status = "in_progress"
        return self.postprocessing_status

    def get_evaluation_postprocessing_status(self, training_id: str) -> str:
        return self.postprocessing_status

    def get_evaluation_metadata(self, training_id: str):
        return SystemDiscoveryTrainingEvaluationMetadata(
            analysis="Model evaluation based on 50 samples.",
            sample_size="50",
            nse=SystemDiscoveryEvaluationMetric(
                value="0.9697",
                confidence_interval="0.9479 - 0.9815",
                confidence_level="95.00%",
                confidence_method="BCa",
            ),
            rmse=SystemDiscoveryEvaluationMetric(
                value="0.1273",
                confidence_interval="0.1071 - 0.1555",
                confidence_level="95.00%",
                confidence_method="BCa",
            ),
            nrmse=SystemDiscoveryEvaluationMetric(value="17.4029"),
            pbias=SystemDiscoveryEvaluationMetric(value="0.3608", note="Overestimation"),
            p_value="0.0000",
            categories=[
                SystemDiscoveryEvaluationCategory("Very Good", "100.00%"),
                SystemDiscoveryEvaluationCategory("Good", "0.00%"),
                SystemDiscoveryEvaluationCategory("Acceptable", "0.00%"),
                SystemDiscoveryEvaluationCategory("Unsatisfactory", "0.00%"),
            ],
        )

    def get_evaluation_artifact_zip(self, training_id: str, artifact_name: str) -> bytes:
        self.artifact_zip_calls.append((training_id, artifact_name))
        return f"zip:{training_id}:{artifact_name}".encode()

    def get_evaluation_artifact_bounds(self, training_id: str, artifact_name: str):
        if artifact_name != "scatter.csv":
            return None
        return (0.0, 10.0)

    def can_save_evaluation_workspace(self, training_id: str, archive_key: str) -> bool:
        return self.can_save

    def build_model_simulation_archive(
        self,
        training_id: str,
        archive_key: str,
        external_control_signals_archive: bytes | None = None,
    ) -> bytes:
        import io
        import json
        import zipfile

        self.build_model_simulation_archive_calls.append(
            (training_id, archive_key, external_control_signals_archive)
        )
        with io.BytesIO() as buffer:
            with zipfile.ZipFile(buffer, mode="w") as target:
                target.writestr("model.syspy", b"trained-model-bytes")
                if self.include_initial_conditions:
                    target.writestr(
                        "initial_conditions.json", json.dumps([0, 1, 2]).encode()
                    )
            return buffer.getvalue()

    def remove_training_workspace(self, training_id: str) -> None:
        self.removed_training_workspaces.append(training_id)
        if training_id in self.fail_remove_training_ids:
            raise RuntimeError("workspace remove failed")


class FakeSavedModelRegistry:
    def __init__(self) -> None:
        self.records = {}
        self.saved = []
        self.removed = []

    def save_model(self, record: SystemDiscoverySavedModelRecord) -> None:
        self.saved.append(record)
        self.records[record.model_id] = record

    def get_model(self, model_id: str):
        return self.records.get(model_id)

    def get_model_by_source_training_id(self, training_id: str):
        for record in self.records.values():
            if record.source_training_id == training_id:
                return record
        return None

    def list_models(self):
        return sorted(self.records.values(), key=lambda record: record.saved_at, reverse=True)

    def remove_model(self, model_id: str) -> None:
        self.removed.append(model_id)
        self.records.pop(model_id, None)


class FakeSimulatorsRepo:
    def __init__(self) -> None:
        self.register_calls = []
        self.fail_register = False
        self.registration_id = "reg-1"

    def register(self, record):
        self.register_calls.append(record)
        if self.fail_register:
            from use_case_contracts.errors import ExternalServiceError

            raise ExternalServiceError("simulators repo failed")
        return self.registration_id

    def registration_status(self, registration_id: str) -> str:
        return "waiting"


class FakeVisualizationPort:
    def __init__(self) -> None:
        self.render_calls = []
        self.status_by_id = {}
        self.html_by_id = {}
        self.fail_render = False
        self.fail_status = False
        self.fail_html = False

    def supported_plot_types(self):
        return ["Line"]

    def render_plot(self, zip_csv_bytes, plot_spec):
        if self.fail_render:
            raise ExternalServiceError(
                "Visualization service request failed (POST http://localhost:9999/api/v1/generate-plot2D): [Errno 111] Connection refused"
            )
        self.render_calls.append((zip_csv_bytes, plot_spec))
        plot_id = f"plot-{len(self.render_calls)}"
        self.status_by_id.setdefault(plot_id, "processing")
        return plot_id

    def get_plot_html(self, plot_id):
        if self.fail_html:
            raise ExternalServiceError(
                "Visualization service request failed (GET http://localhost:9999/api/v1/get-plot-html/plot-1): timed out"
            )
        return self.html_by_id.get(plot_id, "<div>plot</div>")

    def get_plot_status(self, plot_id):
        if self.fail_status:
            raise ExternalServiceError(
                "Visualization service request failed (GET http://localhost:9999/api/v1/get-plot-status/plot-1): connection reset"
            )
        return self.status_by_id.get(plot_id, "processing")


class FakeTrainingRegistry:
    def __init__(self) -> None:
        self.records = {}
        self.archived = []

    def register_training(self, record: SystemDiscoveryTrainingRecord) -> None:
        self.records[record.training_id] = record

    def get_training(self, training_id: str):
        return self.records.get(training_id)

    def list_trainings(self):
        return sorted(
            self.records.values(),
            key=lambda record: (record.created_at, record.training_id),
            reverse=True,
        )

    def update_training_status(
        self,
        training_id: str,
        *,
        state,
        raw_status,
        training_status,
        evaluation_status,
        error,
        updated_at,
    ):
        record = self.records[training_id]
        updated = replace(
            record,
            state=state,
            raw_status=raw_status,
            training_status=training_status,
            evaluation_status=evaluation_status,
            error=error,
            updated_at=updated_at,
        )
        self.records[training_id] = updated
        return updated

    def update_training_results_cache(
        self,
        training_id: str,
        *,
        results_archive_path,
        results_cached_at,
        results_cache_error,
    ):
        record = self.records[training_id]
        updated = replace(
            record,
            results_archive_path=results_archive_path,
            results_cached_at=results_cached_at,
            results_cache_error=results_cache_error,
        )
        self.records[training_id] = updated
        return updated

    def archive_training(self, training_id: str, *, archived_at) -> None:
        self.archived.append((training_id, archived_at))
        self.records.pop(training_id, None)


def test_given_train_system_discovery_when_handled_then_typed_parameters_and_archive_are_sent_and_record_is_persisted() -> None:
    port = FakeSystemDiscoveryPort()
    registry = FakeTrainingRegistry()
    bus = _bus(port, registry)

    result = bus.handle(
        TrainSystemDiscovery(
            training_data_archive=b"original-zip",
            nlags_x=((1, 2), (3, 4)),
            nlags_y=2,
            basis="Polynomial",
            degree=3,
            model="narmax",
        )
    )

    assert isinstance(result, TrainSystemDiscoveryResult)
    assert result.training_id == "train-1"
    request = port.submitted[0]
    assert request.training_data_archive == b"original-zip"
    assert request.system_parameters == SystemDiscoveryParameters(
        nlags_x=((1, 2), (3, 4)),
        nlags_y=2,
        basis="Polynomial",
        degree=3,
        model="narmax",
    )
    assert registry.get_training("train-1").state == SystemDiscoveryTrainingState.QUEUED


def test_given_train_system_discovery_without_nlags_x_when_handled_then_none_is_sent_and_persisted() -> None:
    port = FakeSystemDiscoveryPort()
    registry = FakeTrainingRegistry()
    bus = _bus(port, registry)

    bus.handle(
        TrainSystemDiscovery(
            training_data_archive=b"original-zip",
            nlags_x=None,
            nlags_y=2,
            basis="Polynomial",
            degree=3,
            model="narmax",
        )
    )

    request = port.submitted[0]
    assert request.system_parameters == SystemDiscoveryParameters(
        nlags_x=None,
        nlags_y=2,
        basis="Polynomial",
        degree=3,
        model="narmax",
    )
    assert registry.get_training("train-1").nlags_x is None


def test_given_training_started_status_when_status_loaded_then_state_is_running() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records("train-1")
    port.statuses["train-1"] = SystemDiscoveryTrainingStatus(
        training_id="train-1",
        status="Training started",
        training_status="training",
        evaluation_status="waiting",
        error=None,
    )

    result = _bus(port, registry).handle(GetSystemDiscoveryTrainingStatus("train-1"))

    assert result.training.state == SystemDiscoveryTrainingState.RUNNING
    assert result.training.raw_status == "Training started"
    assert port.status_calls == ["train-1"]


def test_given_queue_load_when_records_have_mixed_states_then_only_non_finished_are_polled() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(
        ("queued", SystemDiscoveryTrainingState.QUEUED),
        ("running", SystemDiscoveryTrainingState.RUNNING),
        ("failed", SystemDiscoveryTrainingState.FAILED),
        ("completed-cached", SystemDiscoveryTrainingState.COMPLETED, True),
    )
    port.statuses["queued"] = _status("queued", "running")
    port.statuses["running"] = _status("running", "running")

    result = _bus(port, registry).handle(ListSystemDiscoveryTrainings())

    assert isinstance(result, ListSystemDiscoveryTrainingsResult)
    assert port.status_calls == ["running", "queued"]
    assert result.failures == []


def test_given_queue_load_when_completed_lacks_archive_then_results_are_cached_without_status_poll() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED))
    storage = FakeTrainingResultsStorage()

    result = _bus(port, registry, storage).handle(ListSystemDiscoveryTrainings())

    assert port.status_calls == []
    assert port.download_calls == ["train-1"]
    assert storage.calls == ["train-1"]
    assert storage.content_by_training_id["train-1"] == b"zip-bytes"
    assert registry.get_training("train-1").results_archive_path == "train-1/results.zip"
    assert registry.get_training("train-1").results_cached_at is not None
    assert result.failures == []


def test_given_queue_load_when_completed_archive_is_cached_then_no_status_or_results_call_is_made() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(
        ("train-1", SystemDiscoveryTrainingState.COMPLETED, True)
    )
    storage = FakeTrainingResultsStorage()

    _bus(port, registry, storage).handle(ListSystemDiscoveryTrainings())

    assert port.status_calls == []
    assert port.download_calls == []
    assert storage.calls == []


def test_given_many_cached_trainings_when_listed_then_pagination_slices_page() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(
        *(("train-{:02d}".format(index), SystemDiscoveryTrainingState.COMPLETED, True) for index in range(1, 26))
    )
    storage = FakeTrainingResultsStorage()

    first = _bus(port, registry, storage).handle(
        ListSystemDiscoveryTrainings(page=1, per_page=10)
    )
    second = _bus(port, registry, storage).handle(
        ListSystemDiscoveryTrainings(page=3, per_page=10)
    )

    assert [r.training_id for r in first.trainings] == [
        f"train-{index:02d}" for index in range(25, 15, -1)
    ]
    assert [r.training_id for r in second.trainings] == [
        f"train-{index:02d}" for index in range(5, 0, -1)
    ]
    assert first.total == 25
    assert first.page == 1
    assert first.per_page == 10
    assert second.page == 3


def test_given_detail_load_when_training_is_active_then_status_is_polled() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records("train-1")
    port.statuses["train-1"] = _status("train-1", "running")

    result = _bus(port, registry).handle(GetSystemDiscoveryTrainingStatus("train-1"))

    assert port.status_calls == ["train-1"]
    assert result.training.state == SystemDiscoveryTrainingState.RUNNING


def test_given_detail_load_when_training_failed_then_remote_endpoints_are_not_called() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.FAILED))

    result = _bus(port, registry).handle(GetSystemDiscoveryTrainingStatus("train-1"))

    assert port.status_calls == []
    assert port.download_calls == []
    assert result.training.state == SystemDiscoveryTrainingState.FAILED


def test_given_detail_load_when_completed_archive_is_cached_then_remote_endpoints_are_not_called() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(
        ("train-1", SystemDiscoveryTrainingState.COMPLETED, True)
    )

    _bus(port, registry).handle(GetSystemDiscoveryTrainingStatus("train-1"))

    assert port.status_calls == []
    assert port.download_calls == []


def test_given_completed_training_cache_failure_then_completed_state_is_preserved_and_retryable() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED))
    port.fail_download_ids.add("train-1")

    first = _bus(port, registry).handle(ListSystemDiscoveryTrainings())
    port.fail_download_ids.clear()
    second = _bus(port, registry).handle(ListSystemDiscoveryTrainings())

    assert registry.get_training("train-1").state == SystemDiscoveryTrainingState.COMPLETED
    assert first.failures[0].training_id == "train-1"
    assert port.download_calls == ["train-1", "train-1"]
    assert second.failures == []
    assert registry.get_training("train-1").results_cache_error is None
    assert registry.get_training("train-1").results_cached_at is not None


def test_given_one_status_refresh_fails_when_loading_queue_then_other_records_are_updated() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records("train-1", "train-2")
    port.fail_status_ids.add("train-2")

    result = _bus(port, registry).handle(ListSystemDiscoveryTrainings())

    assert [failure.training_id for failure in result.failures] == ["train-2"]
    assert registry.get_training("train-1").state == SystemDiscoveryTrainingState.COMPLETED
    assert registry.get_training("train-2").state == SystemDiscoveryTrainingState.QUEUED


def test_given_non_completed_training_when_evaluation_opened_then_visualization_is_not_requested() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.RUNNING))
    storage = FakeTrainingResultsStorage()
    visualization = FakeVisualizationPort()

    result = _bus(port, registry, storage, visualization).handle(
        OpenSystemDiscoveryTrainingEvaluation("train-1")
    )

    assert result.state == SystemDiscoveryTrainingEvaluationState.NOT_COMPLETED
    assert storage.start_calls == []
    assert visualization.render_calls == []


def test_given_completed_training_without_postprocessing_when_evaluation_opened_then_postprocessing_is_started() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED, True))
    storage = FakeTrainingResultsStorage()

    result = _bus(port, registry, storage).handle(
        OpenSystemDiscoveryTrainingEvaluation("train-1")
    )

    assert result.state == SystemDiscoveryTrainingEvaluationState.POSTPROCESSING
    assert result.message == "Waiting for model evaluation."
    assert storage.start_calls == [("train-1", "stored/train-1.zip")]


def test_given_completed_training_already_postprocessing_when_evaluation_opened_then_duplicate_postprocessing_is_not_started() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED, True))
    storage = FakeTrainingResultsStorage()
    storage.postprocessing_status = "in_progress"

    result = _bus(port, registry, storage).handle(
        OpenSystemDiscoveryTrainingEvaluation("train-1")
    )

    assert result.state == SystemDiscoveryTrainingEvaluationState.POSTPROCESSING
    assert storage.start_calls == [("train-1", "stored/train-1.zip")]


def test_given_postprocessed_training_when_evaluation_opened_then_results_and_cdf_visualizations_are_requested() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED, True))
    storage = FakeTrainingResultsStorage()
    storage.postprocessing_status = "ready"
    visualization = FakeVisualizationPort()

    result = _bus(port, registry, storage, visualization).handle(
        OpenSystemDiscoveryTrainingEvaluation("train-1")
    )

    assert result.state == SystemDiscoveryTrainingEvaluationState.READY
    assert storage.artifact_zip_calls == [
        ("train-1", "results.csv"),
        ("train-1", "cdf.csv"),
        ("train-1", "scatter.csv"),
    ]
    assert len(visualization.render_calls) == 3
    assert result.results_plot.state == SystemDiscoveryTrainingEvaluationPlotState.PENDING
    assert result.cdf_plot.state == SystemDiscoveryTrainingEvaluationPlotState.PENDING
    assert result.results_plot.waiting_message == "Waiting for visualization."
    assert result.cdf_plot.waiting_message == "Waiting for visualization."
    assert result.metadata.sample_size == "50"


def test_given_visualization_jobs_already_submitted_when_evaluation_reopens_then_jobs_are_reused() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED, True))
    storage = FakeTrainingResultsStorage()
    storage.postprocessing_status = "ready"
    visualization = FakeVisualizationPort()
    plot_mapping = PlotMapping()
    bus = _bus(port, registry, storage, visualization, plot_mapping)

    first = bus.handle(OpenSystemDiscoveryTrainingEvaluation("train-1"))
    visualization.status_by_id["plot-1"] = "done"
    visualization.status_by_id["plot-2"] = "done"
    second = bus.handle(OpenSystemDiscoveryTrainingEvaluation("train-1"))

    assert len(visualization.render_calls) == 3
    assert first.results_plot.plot_html is None
    assert second.results_plot.state == SystemDiscoveryTrainingEvaluationPlotState.READY
    assert second.cdf_plot.state == SystemDiscoveryTrainingEvaluationPlotState.READY
    assert second.results_plot.plot_html == "<div>plot</div>"
    assert second.cdf_plot.plot_html == "<div>plot</div>"


def test_given_visualization_service_unavailable_when_evaluation_opened_then_metadata_renders_and_plots_are_blank() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED, True))
    storage = FakeTrainingResultsStorage()
    storage.postprocessing_status = "ready"
    visualization = FakeVisualizationPort()
    visualization.fail_render = True

    result = _bus(port, registry, storage, visualization).handle(
        OpenSystemDiscoveryTrainingEvaluation("train-1")
    )

    assert result.state == SystemDiscoveryTrainingEvaluationState.READY
    assert result.metadata.sample_size == "50"
    assert result.results_plot.state == SystemDiscoveryTrainingEvaluationPlotState.UNAVAILABLE
    assert result.cdf_plot.state == SystemDiscoveryTrainingEvaluationPlotState.UNAVAILABLE
    assert result.results_plot.waiting_message == ""
    assert result.cdf_plot.waiting_message == ""
    assert registry.get_training("train-1").state == SystemDiscoveryTrainingState.COMPLETED
    assert storage.get_evaluation_postprocessing_status("train-1") == "ready"


def test_given_unavailable_visualization_when_evaluation_reopens_then_visualization_is_retried() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED, True))
    storage = FakeTrainingResultsStorage()
    storage.postprocessing_status = "ready"
    visualization = FakeVisualizationPort()
    visualization.fail_render = True
    bus = _bus(port, registry, storage, visualization, PlotMapping())

    first = bus.handle(OpenSystemDiscoveryTrainingEvaluation("train-1"))
    visualization.fail_render = False
    second = bus.handle(OpenSystemDiscoveryTrainingEvaluation("train-1"))

    assert first.results_plot.state == SystemDiscoveryTrainingEvaluationPlotState.UNAVAILABLE
    assert second.results_plot.state == SystemDiscoveryTrainingEvaluationPlotState.PENDING
    assert len(visualization.render_calls) == 3


def test_given_pending_visualization_when_evaluation_opened_then_waiting_message_is_preserved() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED, True))
    storage = FakeTrainingResultsStorage()
    storage.postprocessing_status = "ready"

    result = _bus(port, registry, storage, FakeVisualizationPort()).handle(
        OpenSystemDiscoveryTrainingEvaluation("train-1")
    )

    assert result.results_plot.state == SystemDiscoveryTrainingEvaluationPlotState.PENDING
    assert result.results_plot.waiting_message == "Waiting for visualization."


def test_given_ready_plot_status_when_html_request_unavailable_then_plot_is_unavailable_without_failing_metadata() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED, True))
    storage = FakeTrainingResultsStorage()
    storage.postprocessing_status = "ready"
    visualization = FakeVisualizationPort()
    visualization.status_by_id["plot-1"] = "done"
    visualization.status_by_id["plot-2"] = "done"
    visualization.fail_html = True

    result = _bus(port, registry, storage, visualization).handle(
        OpenSystemDiscoveryTrainingEvaluation("train-1")
    )

    assert result.state == SystemDiscoveryTrainingEvaluationState.READY
    assert result.metadata.sample_size == "50"
    assert result.results_plot.state == SystemDiscoveryTrainingEvaluationPlotState.UNAVAILABLE


def test_given_completed_postprocessed_training_when_saved_then_workspace_promoted_record_saved_and_training_archived() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED, True))
    storage = FakeTrainingResultsStorage()
    storage.postprocessing_status = "ready"
    saved_models = FakeSavedModelRegistry()
    simulators_repo = FakeSimulatorsRepo()

    result = _bus(
        port,
        registry,
        storage,
        saved_models=saved_models,
        simulators_repo=simulators_repo,
    ).handle(SaveSystemDiscoveryModel("train-1"))

    assert result.model_id == "train-1"
    assert result.simulator_registration_id == "reg-1"
    assert storage.build_model_simulation_archive_calls == [
        ("train-1", "stored/train-1.zip", None)
    ]
    saved = saved_models.get_model("train-1")
    assert saved.model_name == "model-train-1"
    assert registry.get_training("train-1") is None
    assert registry.archived[0][0] == "train-1"
    assert port.download_calls == []

    assert len(simulators_repo.register_calls) == 1
    build_record = simulators_repo.register_calls[0]
    assert build_record.model_name == "model-train-1"
    assert build_record.zip_filename == "train-1.zip"
    assert build_record.build_spec.spec["technology"]["python"]["version"] == "3.11"
    assert [p.name for p in build_record.input_params] == [
        "ic_0",
        "ic_1",
        "ic_2",
        "horizon",
    ]
    assert build_record.zip_bytes
    assert build_record.zip_bytes.startswith(b"PK")


def test_given_completed_postprocessed_training_without_initial_conditions_when_saved_then_dimension_from_nlags_y() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(
        ("train-1", SystemDiscoveryTrainingState.COMPLETED, True)
    )
    storage = FakeTrainingResultsStorage()
    storage.postprocessing_status = "ready"
    storage.include_initial_conditions = False
    saved_models = FakeSavedModelRegistry()
    simulators_repo = FakeSimulatorsRepo()

    result = _bus(
        port,
        registry,
        storage,
        saved_models=saved_models,
        simulators_repo=simulators_repo,
    ).handle(SaveSystemDiscoveryModel("train-1"))

    assert result.model_id == "train-1"
    assert result.simulator_registration_id == "reg-1"
    build_record = simulators_repo.register_calls[0]
    assert [p.name for p in build_record.input_params] == [
        "ic_0",
        "horizon",
    ]


def test_given_completed_postprocessed_training_when_saved_and_registration_fails_then_save_fails() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED, True))
    storage = FakeTrainingResultsStorage()
    storage.postprocessing_status = "ready"
    saved_models = FakeSavedModelRegistry()
    simulators_repo = FakeSimulatorsRepo()
    simulators_repo.fail_register = True

    with pytest.raises(ExternalServiceError, match="simulators repo failed"):
        _bus(
            port,
            registry,
            storage,
            saved_models=saved_models,
            simulators_repo=simulators_repo,
        ).handle(SaveSystemDiscoveryModel("train-1"))

    assert saved_models.get_model("train-1") is None
    assert registry.get_training("train-1") is not None


def test_given_training_without_cached_results_when_saved_then_save_is_rejected() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED))
    storage = FakeTrainingResultsStorage()

    with pytest.raises(ValueError, match="not been cached"):
        _bus(port, registry, storage).handle(SaveSystemDiscoveryModel("train-1"))

    assert storage.build_model_simulation_archive_calls == []
    assert registry.get_training("train-1") is not None


def test_given_saved_model_when_saved_again_then_existing_model_id_is_returned_idempotently() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED, True))
    storage = FakeTrainingResultsStorage()
    saved_models = FakeSavedModelRegistry()
    saved_models.save_model(
        SystemDiscoverySavedModelRecord(
            model_id="train-1",
            source_training_id="train-1",
            model_name="model-train-1",
            saved_at=FakeClock().now(),
            nlags_x=((1, 2),),
            nlags_y=1,
            basis="Polynomial",
            degree=2,
        )
    )

    result = _bus(port, registry, storage, saved_models=saved_models).handle(
        SaveSystemDiscoveryModel("train-1")
    )

    assert result.model_id == "train-1"
    assert result.simulator_registration_id is None
    assert storage.build_model_simulation_archive_calls == []
    assert registry.get_training("train-1") is None


@pytest.mark.parametrize(
    "state",
    [
        SystemDiscoveryTrainingState.QUEUED,
        SystemDiscoveryTrainingState.RUNNING,
        SystemDiscoveryTrainingState.COMPLETED,
        SystemDiscoveryTrainingState.FAILED,
    ],
)
def test_given_training_queue_entry_when_removed_then_workspace_removed_record_archived_and_remote_not_called(state) -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", state))
    storage = FakeTrainingResultsStorage()

    result = _bus(port, registry, storage).handle(
        RemoveSystemDiscoveryTrainingQueueEntry("train-1")
    )

    assert result.removed is True
    assert storage.removed_training_workspaces == ["train-1"]
    assert registry.get_training("train-1") is None
    assert registry.archived[0][0] == "train-1"
    assert port.status_calls == []
    assert port.download_calls == []


def test_given_training_removal_for_promoted_model_then_persistent_workspace_is_not_removed() -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records(("train-1", SystemDiscoveryTrainingState.COMPLETED, True))
    storage = FakeTrainingResultsStorage()
    saved_models = FakeSavedModelRegistry()
    saved_models.save_model(
        SystemDiscoverySavedModelRecord(
            model_id="train-1",
            source_training_id="train-1",
            model_name="narmax",
            saved_at=FakeClock().now(),
            nlags_x=((1, 2),),
            nlags_y=1,
            basis="Polynomial",
            degree=2,
        )
    )

    _bus(port, registry, storage, saved_models=saved_models).handle(
        RemoveSystemDiscoveryTrainingQueueEntry("train-1")
    )

    assert storage.removed_training_workspaces == ["train-1"]
    assert saved_models.get_model("train-1") is not None


def test_given_saved_model_when_removed_then_workspace_and_registry_record_are_removed() -> None:
    storage = FakeTrainingResultsStorage()
    saved_models = FakeSavedModelRegistry()
    saved_models.save_model(
        SystemDiscoverySavedModelRecord(
            model_id="model-1",
            source_training_id="train-1",
            model_name="narmax",
            saved_at=FakeClock().now(),
            nlags_x=((1, 2),),
            nlags_y=1,
            basis="Polynomial",
            degree=2,
        )
    )

    result = _bus(
        FakeSystemDiscoveryPort(),
        FakeTrainingRegistry(),
        storage,
        saved_models=saved_models,
    ).handle(RemoveSavedSystemDiscoveryModel("model-1"))

    assert result.removed is True
    assert saved_models.get_model("model-1") is None


def test_cleanup_removes_only_old_terminal_unsaved_entries_and_continues_after_failures() -> None:
    clock = FakeClock()
    old = clock.now() - timedelta(days=31)
    recent = clock.now() - timedelta(days=1)
    registry = FakeTrainingRegistry()
    for training_id, state, finished_at in [
        ("old-completed", SystemDiscoveryTrainingState.COMPLETED, old),
        ("old-failed", SystemDiscoveryTrainingState.FAILED, old),
        ("recent-completed", SystemDiscoveryTrainingState.COMPLETED, recent),
        ("running", SystemDiscoveryTrainingState.RUNNING, old),
        ("saved", SystemDiscoveryTrainingState.COMPLETED, old),
        ("failing", SystemDiscoveryTrainingState.COMPLETED, old),
    ]:
        registry.register_training(
            replace(
                _training_record(training_id, state),
                updated_at=finished_at,
                finished_at=finished_at,
            )
        )
    storage = FakeTrainingResultsStorage()
    storage.fail_remove_training_ids.add("failing")
    saved_models = FakeSavedModelRegistry()
    saved_models.save_model(
        SystemDiscoverySavedModelRecord(
            model_id="saved",
            source_training_id="saved",
            model_name="narmax",
            saved_at=clock.now(),
            nlags_x=((1, 2),),
            nlags_y=1,
            basis="Polynomial",
            degree=2,
        )
    )

    result = _bus(
        FakeSystemDiscoveryPort(),
        registry,
        storage,
        saved_models=saved_models,
    ).handle(CleanupExpiredSystemDiscoveryTrainingQueueEntries(terminal_retention_days=30))

    assert isinstance(result, CleanupExpiredSystemDiscoveryTrainingQueueEntriesResult)
    assert result.examined_count == 6
    assert result.removed_count == 2
    assert result.skipped_count == 3
    assert result.failed_count == 1
    assert registry.get_training("old-completed") is None
    assert registry.get_training("old-failed") is None
    assert registry.get_training("recent-completed") is not None
    assert registry.get_training("running") is not None
    assert registry.get_training("saved") is not None
    assert registry.get_training("failing") is not None


def test_given_training_without_nlags_x_when_saved_then_saved_model_keeps_none() -> None:
    port = FakeSystemDiscoveryPort()
    registry = FakeTrainingRegistry()
    created_at = FakeClock().now()
    registry.register_training(
        SystemDiscoveryTrainingRecord(
            training_id="train-1",
            created_at=created_at,
            updated_at=created_at,
            state=SystemDiscoveryTrainingState.COMPLETED,
            raw_status="completed",
            training_status="done",
            evaluation_status="done",
            error=None,
            basis="Polynomial",
            degree=2,
            model="narmax",
            nlags_x=None,
            nlags_y=1,
            results_archive_path="train-1/results.zip",
            results_cached_at=created_at,
        )
    )
    storage = FakeTrainingResultsStorage()
    saved_models = FakeSavedModelRegistry()

    result = _bus(port, registry, storage, saved_models=saved_models).handle(
        SaveSystemDiscoveryModel("train-1")
    )

    saved = saved_models.get_model(result.model_id)
    assert saved.nlags_x is None


def test_given_registry_rows_with_json_null_nlags_x_when_mapped_then_records_return_none() -> None:
    timestamp = FakeClock().now()

    training = _record_from_row(
        (
            "train-1",
            timestamp,
            timestamp,
            "queued",
            "queued",
            None,
            None,
            None,
            "Polynomial",
            2,
            "narmax",
            "null",
            1,
            None,
            None,
            None,
        )
    )
    saved = _saved_model_from_row(
        (
            "model-1",
            "train-1",
            "narmax",
            timestamp,
            None,
            1,
            "Polynomial",
            2,
        )
    )
    registered = _saved_model_from_row(
        (
            "model-2",
            "train-2",
            "narmax2",
            timestamp,
            None,
            1,
            "Polynomial",
            2,
        )
    )

    assert _json_nlags_x(None) == "null"
    assert training.nlags_x is None
    assert saved.nlags_x is None

    assert _json_nlags_x(None) == "null"
    assert training.nlags_x is None
    assert saved.nlags_x is None


def test_given_saved_model_when_details_loaded_then_model_is_returned() -> None:
    port = FakeSystemDiscoveryPort()
    registry = FakeTrainingRegistry()
    saved_models = FakeSavedModelRegistry()
    saved_models.save_model(
        SystemDiscoverySavedModelRecord(
            model_id="model-1",
            source_training_id="train-1",
            model_name="narmax",
            saved_at=FakeClock().now(),
            nlags_x=((1, 2),),
            nlags_y=1,
            basis="Polynomial",
            degree=2,
        )
    )

    result = _bus(
        port,
        registry,
        saved_models=saved_models,
    ).handle(GetSavedSystemDiscoveryModelDetails("model-1"))

    assert result.model.model_id == "model-1"
    assert result.model.source_training_id == "train-1"
    assert result.model.model_name == "narmax"


def test_given_saved_model_when_details_requested_for_unknown_id_then_not_found() -> None:
    port = FakeSystemDiscoveryPort()
    registry = FakeTrainingRegistry()
    saved_models = FakeSavedModelRegistry()

    with pytest.raises(NotFoundError):
        _bus(
            port,
            registry,
            saved_models=saved_models,
        ).handle(GetSavedSystemDiscoveryModelDetails("unknown"))


def test_given_use_case_bus_when_download_message_removed_then_no_download_handler_is_registered() -> None:
    assert not hasattr(message_contracts, "DownloadSystemDiscoveryTrainingResults")
    assert not hasattr(dto_contracts, "DownloadSystemDiscoveryTrainingResultsResult")


def test_given_use_case_bootstrap_when_system_discovery_training_messages_are_handled_then_registered_handlers_are_used(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _configure_bootstrap(monkeypatch, tmp_path)
    registered_records = []

    monkeypatch.setattr(
        RestSystemDiscoveryAdapter,
        "submit_training",
        lambda _self, _request: SystemDiscoveryTrainingSubmission(
            training_id="train-boot",
            status="queued",
        ),
    )
    monkeypatch.setattr(
        PostgresSystemDiscoveryTrainingRegistry,
        "register_training",
        lambda _self, record: registered_records.append(record),
    )
    monkeypatch.setattr(
        PostgresSystemDiscoveryTrainingRegistry,
        "list_trainings",
        lambda _self: [],
    )
    monkeypatch.setattr(
        PostgresSystemDiscoveryTrainingRegistry,
        "get_training",
        lambda _self, _training_id: None,
    )

    bus = build_usecases()

    train_result = bus.handle(
        TrainSystemDiscovery(
            training_data_archive=b"zip",
            nlags_x=((1,),),
            nlags_y=1,
            basis="Polynomial",
            degree=2,
            model="narmax",
        )
    )
    list_result = bus.handle(ListSystemDiscoveryTrainings())
    with pytest.raises(NotFoundError):
        bus.handle(GetSystemDiscoveryTrainingStatus("unknown"))

    assert train_result.training_id == "train-boot"
    assert registered_records[0].training_id == "train-boot"
    assert list_result.trainings == []


@pytest.mark.parametrize(
    ("status", "error", "expected_state"),
    [
        ("error", None, SystemDiscoveryTrainingState.FAILED),
        ("success", None, SystemDiscoveryTrainingState.COMPLETED),
        ("processing", None, SystemDiscoveryTrainingState.RUNNING),
        ("created", None, SystemDiscoveryTrainingState.QUEUED),
        ("unexpected", None, SystemDiscoveryTrainingState.QUEUED),
        ("running", "boom", SystemDiscoveryTrainingState.FAILED),
    ],
)
def test_given_external_status_when_loading_detail_then_state_is_normalized(status, error, expected_state) -> None:
    port = FakeSystemDiscoveryPort()
    registry = _registry_with_records("train-1")
    port.statuses["train-1"] = SystemDiscoveryTrainingStatus(
        training_id="train-1",
        status=status,
        training_status="diag-training",
        evaluation_status="diag-eval",
        error=error,
    )

    result = _bus(port, registry).handle(GetSystemDiscoveryTrainingStatus("train-1"))

    assert result.training.state == expected_state
    assert result.training.raw_status == status


def _bus(
    port,
    registry,
    storage=None,
    visualization=None,
    plot_mapping=None,
    saved_models=None,
    simulators_repo=None,
) -> InProcessBus:
    bus = InProcessBus()
    clock = FakeClock()
    storage = storage or FakeTrainingResultsStorage()
    saved_models = saved_models or FakeSavedModelRegistry()
    simulators_repo = simulators_repo or FakeSimulatorsRepo()
    bus.register(
        TrainSystemDiscovery,
        partial(
            handle_train_system_discovery,
            system_discovery=port,
            registry=registry,
            clock=clock,
        ),
    )
    bus.register(
        GetSystemDiscoveryTrainingStatus,
        partial(
            handle_get_system_discovery_training_status,
            system_discovery=port,
            registry=registry,
            results_storage=storage,
            clock=clock,
        ),
    )
    bus.register(
        ListSystemDiscoveryTrainings,
        partial(
            handle_list_system_discovery_trainings,
            system_discovery=port,
            registry=registry,
            results_storage=storage,
            clock=clock,
        ),
    )
    bus.register(
        OpenSystemDiscoveryTrainingEvaluation,
        partial(
            handle_open_system_discovery_training_evaluation,
            registry=registry,
            results_storage=storage,
            visualization=visualization or FakeVisualizationPort(),
            plotsIds=plot_mapping or PlotMapping(),
            saved_models=saved_models,
        ),
    )
    bus.register(
        SaveSystemDiscoveryModel,
        partial(
            handle_save_system_discovery_model,
            registry=registry,
            saved_models=saved_models,
            results_storage=storage,
            simulators_repo=simulators_repo,
            clock=clock,
        ),
    )
    bus.register(
        RemoveSystemDiscoveryTrainingQueueEntry,
        partial(
            handle_remove_system_discovery_training_queue_entry,
            registry=registry,
            saved_models=saved_models,
            results_storage=storage,
            clock=clock,
        ),
    )
    bus.register(
        ListSavedSystemDiscoveryModels,
        partial(
            handle_list_saved_system_discovery_models,
            saved_models=saved_models,
        ),
    )
    bus.register(
        RemoveSavedSystemDiscoveryModel,
        partial(
            handle_remove_saved_system_discovery_model,
            saved_models=saved_models,
        ),
    )
    bus.register(
        CleanupExpiredSystemDiscoveryTrainingQueueEntries,
        partial(
            handle_cleanup_expired_system_discovery_training_queue_entries,
            registry=registry,
            saved_models=saved_models,
            results_storage=storage,
            clock=clock,
        ),
    )
    bus.register(
        GetSavedSystemDiscoveryModelDetails,
        partial(
            handle_get_saved_system_discovery_model_details,
            saved_models=saved_models,
        ),
    )
    return bus


def _registry_with_records(*records) -> FakeTrainingRegistry:
    registry = FakeTrainingRegistry()
    for index, item in enumerate(records, start=1):
        if isinstance(item, str):
            training_id = item
            state = SystemDiscoveryTrainingState.QUEUED
            cached = False
        else:
            training_id = item[0]
            state = item[1]
            cached = len(item) > 2 and item[2]
        created_at = datetime(2026, 6, 28, 12, index, tzinfo=timezone.utc)
        registry.register_training(
            replace(
                _training_record(training_id, state),
                created_at=created_at,
                updated_at=created_at,
                results_archive_path=f"stored/{training_id}.zip" if cached else None,
                results_cached_at=created_at if cached else None,
            )
        )
    return registry


def _training_record(
    training_id: str,
    state: SystemDiscoveryTrainingState,
) -> SystemDiscoveryTrainingRecord:
    created_at = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    return SystemDiscoveryTrainingRecord(
        training_id=training_id,
        created_at=created_at,
        updated_at=created_at,
        state=state,
        raw_status=state.value,
        training_status=None,
        evaluation_status=None,
        error=None,
        basis="Polynomial",
        degree=2,
        model=f"model-{training_id}",
        nlags_x=((1, 2),),
        nlags_y=1,
        finished_at=created_at
        if state in {SystemDiscoveryTrainingState.COMPLETED, SystemDiscoveryTrainingState.FAILED}
        else None,
    )


def _status(training_id: str, status: str) -> SystemDiscoveryTrainingStatus:
    return SystemDiscoveryTrainingStatus(
        training_id=training_id,
        status=status,
        training_status="training",
        evaluation_status="evaluation",
        error=None,
    )


def _configure_bootstrap(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    config_path = tmp_path / "rtmf.main.json"
    config_path.write_text(
        json.dumps(
            {
                "services": {
                    "use_case": {
                        "clients": {
                            "jobs_scheduler": {"base_url": "http://jobs", "timeout_seconds": 1, "auth_token": ""},
                            "simulators_repository": {"base_url": "http://sims", "timeout_seconds": 1, "auth_token": ""},
                            "analytics": {"base_url": "http://analytics", "timeout_seconds": 1, "auth_token": ""},
                            "visualization": {"base_url": "http://viz", "timeout_seconds": 1, "auth_token": ""},
                            "parser": {"base_url": "http://parser", "timeout_seconds": 1, "auth_token": ""},
                            "matrix_generator": {"base_url": "http://matrix", "timeout_seconds": 1},
                            "evaluator": {"base_url": "http://evaluator", "timeout_seconds": 1},
                            "system_discovery": {"base_url": "http://system-discovery", "timeout_seconds": 1, "auth_token": ""},
                        },
                        "aistor": {
                            "endpoint": "http://aistor",
                            "secure": False,
                            "access_key": "minio",
                            "secret_key": "password",
                        },
                        "adapters": {
                            "system_discovery_aistor": {
                                "endpoint": "http://aistor",
                                "secure": False,
                                "bucket": "system-discovery",
                                "access_key": "minio",
                                "secret_key": "password",
                            },
                        },
                        "postgres": {
                            "jobs_repository": {"dsn": "postgresql://registry"},
                            "evaluations_store": {"dsn": "postgresql://evaluations"},
                        },
                        "storage": {
                            "system_discovery_training_results": {
                                "endpoint": "http://aistor",
                                "secure": False,
                                "bucket": "system-discovery",
                                "access_key": "minio",
                                "secret_key": "password",
                            }
                        },
                        "authentication": {
                            "identity_provider": "keycloak",
                            "session": {
                                "cookie_name": "rtmf_session",
                                "idle_timeout_seconds": 1800,
                                "absolute_timeout_seconds": 28800,
                                "refresh_skew_seconds": 300,
                                "token_pepper": "test-session-pepper",
                            },
                            "keycloak": {
                                "issuer_url": "https://kc.example/realms/rtmf",
                                "client_id": "rtmf-web",
                                "client_secret": "test-client-secret",
                                "token_encryption_key": "eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg",
                                "permissions_client_id": "rtmf-use-case",
                                "expected_access_token_audience": "rtmf-use-case",
                                "allow_insecure_http_for_local_development": False,
                                "discovery_cache_seconds": 300,
                                "jwks_cache_seconds": 300,
                                "pending_login_ttl_seconds": 300,
                                "token_request_timeout_seconds": 10,
                                "clock_skew_seconds": 60,
                            },
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RTMF_MAIN_CONFIGURATION_FILE", str(config_path))
