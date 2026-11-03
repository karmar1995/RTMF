from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from functools import partial

from services.use_case.bus import InProcessBus
from adapters.system_discovery_simulation_results_postprocessor import (
    SystemDiscoverySimulationResultsArchivePostprocessor,
)
from adapters.system_discovery_training_registry.postgres_registry import (
    _simulation_from_row,
)
from services.use_case.handlers.system_discovery_simulations import (
    handle_get_system_discovery_simulation_details,
    handle_list_system_discovery_simulations,
)
from services.use_case.utils.plot_mapping import PlotMapping
from use_case_contracts.dtos import (
    SystemDiscoverySavedModelRecord,
    SystemDiscoverySimulationRecord,
    SystemDiscoverySimulationResultsArchive,
    SystemDiscoverySimulationResultsArchivePostprocessingResult,
    SystemDiscoverySimulationState,
    SystemDiscoverySimulationStatus,
    SystemDiscoverySimulationSubmission,
    SystemDiscoverySimulationVisualizationState,
    SystemDiscoveryStoredResultsArchive,
)
from use_case_contracts.errors import ExternalServiceError
from use_case_contracts.messages import (
    GetSystemDiscoverySimulationDetails,
    ListSystemDiscoverySimulations,
)


class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)


class FakeSystemDiscoveryPort:
    def __init__(self) -> None:
        self.submitted = []
        self.statuses = {}
        self.status_calls = []
        self.download_calls = []
        self.fail_status_ids = set()
        self.fail_download_ids = set()

    def submit_system_discovery_simulation(self, request):
        self.submitted.append(request)
        return SystemDiscoverySimulationSubmission(
            simulation_id="sim-1",
            status="Simulation started",
        )

    def get_system_discovery_simulation_status(self, simulation_id: str):
        self.status_calls.append(simulation_id)
        if simulation_id in self.fail_status_ids:
            raise RuntimeError("status failed")
        return self.statuses[simulation_id]

    def download_system_discovery_simulation_results(self, simulation_id: str):
        self.download_calls.append(simulation_id)
        if simulation_id in self.fail_download_ids:
            raise RuntimeError("download failed")
        return SystemDiscoverySimulationResultsArchive(
            content=_zip({"results.csv": b"x;y\n1;2\n3;4\n"})
        )


class FakeSavedModels:
    def __init__(self) -> None:
        self.model = SystemDiscoverySavedModelRecord(
            model_id="model-1",
            source_training_id="train-1",
            model_name="narmax",
            saved_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
            nlags_x=((1,),),
            nlags_y=1,
            basis="Polynomial",
            degree=2,
        )

    def get_model(self, model_id: str):
        return self.model if model_id == self.model.model_id else None


class FakeArtifacts:
    def prepare_results_csv_zip(self, results_archive: bytes):
        return b"results-csv-zip:" + results_archive


class FakePostprocessor:
    def __init__(self) -> None:
        self.calls = []
        self.fail = False

    def postprocess(self, archive: SystemDiscoverySimulationResultsArchive):
        self.calls.append(archive.content)
        if self.fail:
            raise RuntimeError("postprocess failed")
        if _has_canonical_time(archive.content):
            return SystemDiscoverySimulationResultsArchivePostprocessingResult(
                archive=archive,
                was_modified=False,
            )
        return SystemDiscoverySimulationResultsArchivePostprocessingResult(
            archive=SystemDiscoverySimulationResultsArchive(
                content=_zip({"results.csv": b"time;x;y\n0;1;2\n1;3;4\n"})
            ),
            was_modified=True,
        )


class FakeRegistry:
    def __init__(self) -> None:
        self.records = {}

    def register_simulation(self, record):
        self.records[record.simulation_id] = record

    def get_simulation(self, simulation_id: str):
        return self.records.get(simulation_id)

    def list_simulations(self):
        return sorted(
            self.records.values(),
            key=lambda record: record.created_at,
            reverse=True,
        )

    def update_simulation_status(self, simulation_id: str, *, state, raw_status, error, updated_at):
        record = replace(
            self.records[simulation_id],
            state=state,
            raw_status=raw_status,
            error=error,
            updated_at=updated_at,
        )
        self.records[simulation_id] = record
        return record

    def update_simulation_aistor_result(
        self,
        simulation_id: str,
        *,
        aistor_object_key,
        aistor_uploaded_at,
        aistor_upload_error,
    ):
        record = replace(
            self.records[simulation_id],
            aistor_object_key=aistor_object_key,
            aistor_uploaded_at=aistor_uploaded_at,
            aistor_upload_error=aistor_upload_error,
        )
        self.records[simulation_id] = record
        return record

    def update_simulation_visualization(self, simulation_id: str, *, visualization_plot_id):
        record = replace(
            self.records[simulation_id],
            visualization_plot_id=visualization_plot_id,
        )
        self.records[simulation_id] = record
        return record


class FakeAIStor:
    def __init__(self) -> None:
        self.uploads = []
        self.objects = {}
        self.fail_upload = False

    def upload_results_archive(self, simulation_id: str, content: bytes):
        self.uploads.append((simulation_id, content))
        if self.fail_upload:
            raise RuntimeError("upload failed")
        self.objects[simulation_id] = content
        return SystemDiscoveryStoredResultsArchive(
            simulation_id=simulation_id,
            storage_reference=f"system-discovery/simulations/{simulation_id}/results.zip",
        )

    def download_results_archive(self, simulation_id: str):
        return self.objects[simulation_id]


class FakeVisualization:
    def __init__(self) -> None:
        self.rendered = []
        self.status = "pending"
        self.unavailable = False

    def render_plot(self, zip_csv_bytes, plot_spec):
        if self.unavailable:
            raise ExternalServiceError("connection refused")
        self.rendered.append((zip_csv_bytes, plot_spec))
        return "plot-1"

    def get_plot_status(self, plot_id: str):
        if self.unavailable:
            raise ExternalServiceError("connection refused")
        return self.status

    def get_plot_html(self, plot_id: str):
        return "<div>plot</div>"


def test_list_refreshes_running_transfers_completed_results_and_skips_finished() -> None:
    system_discovery = FakeSystemDiscoveryPort()
    registry = FakeRegistry()
    aistor = FakeAIStor()
    registry.records["sim-running"] = _record("sim-running", SystemDiscoverySimulationState.RUNNING)
    registry.records["sim-completed"] = _record("sim-completed", SystemDiscoverySimulationState.COMPLETED)
    registry.records["sim-failed"] = _record("sim-failed", SystemDiscoverySimulationState.FAILED)
    system_discovery.statuses["sim-running"] = SystemDiscoverySimulationStatus(
        simulation_id="sim-running",
        status="completed",
        error=None,
    )
    postprocessor = FakePostprocessor()
    bus = _bus(
        system_discovery,
        registry=registry,
        aistor=aistor,
        postprocessor=postprocessor,
    )

    bus.handle(ListSystemDiscoverySimulations())

    assert system_discovery.status_calls == ["sim-running"]
    assert system_discovery.download_calls == ["sim-running", "sim-completed"]
    assert len(aistor.uploads) == 2
    assert [simulation_id for simulation_id, _content in aistor.uploads] == [
        "sim-running",
        "sim-completed",
    ]
    assert all(
        _has_canonical_time(content) for _simulation_id, content in aistor.uploads
    )
    assert all(
        content != postprocessor.calls[index]
        for index, (_simulation_id, content) in enumerate(aistor.uploads)
    )


def test_given_many_completed_simulations_when_listed_then_pagination_slices_page() -> None:
    registry = FakeRegistry()
    for index in range(25):
        registry.records[f"sim-{index:02d}"] = replace(
            _record(f"sim-{index:02d}", SystemDiscoverySimulationState.COMPLETED),
            aistor_object_key=f"key/{index:02d}",
            aistor_uploaded_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
        )
    bus = _bus(registry=registry)

    first = bus.handle(ListSystemDiscoverySimulations(page=1, per_page=10))
    second = bus.handle(ListSystemDiscoverySimulations(page=3, per_page=10))

    assert [r.simulation_id for r in first.simulations] == [
        f"sim-{index:02d}" for index in range(10)
    ]
    assert [r.simulation_id for r in second.simulations] == [
        f"sim-{index:02d}" for index in range(20, 25)
    ]
    assert first.total == 25
    assert first.page == 1
    assert first.per_page == 10
    assert second.page == 3


def test_upload_failure_preserves_completed_state_and_retries_later() -> None:
    system_discovery = FakeSystemDiscoveryPort()
    registry = FakeRegistry()
    aistor = FakeAIStor()
    aistor.fail_upload = True
    registry.records["sim-1"] = _record("sim-1", SystemDiscoverySimulationState.COMPLETED)
    bus = _bus(system_discovery, registry=registry, aistor=aistor)

    first = bus.handle(ListSystemDiscoverySimulations())
    aistor.fail_upload = False
    second = bus.handle(ListSystemDiscoverySimulations())

    assert len(first.failures) == 1
    assert second.failures == []
    assert registry.records["sim-1"].state == SystemDiscoverySimulationState.COMPLETED
    assert registry.records["sim-1"].aistor_object_key == "system-discovery/simulations/sim-1/results.zip"
    assert system_discovery.status_calls == []
    assert system_discovery.download_calls == ["sim-1", "sim-1"]


def test_postprocessing_failure_preserves_completed_state_and_retries_later() -> None:
    system_discovery = FakeSystemDiscoveryPort()
    registry = FakeRegistry()
    aistor = FakeAIStor()
    postprocessor = FakePostprocessor()
    postprocessor.fail = True
    registry.records["sim-1"] = _record("sim-1", SystemDiscoverySimulationState.COMPLETED)
    bus = _bus(
        system_discovery,
        registry=registry,
        aistor=aistor,
        postprocessor=postprocessor,
    )

    first = bus.handle(ListSystemDiscoverySimulations())
    postprocessor.fail = False
    second = bus.handle(ListSystemDiscoverySimulations())

    assert len(first.failures) == 1
    assert second.failures == []
    assert registry.records["sim-1"].state == SystemDiscoverySimulationState.COMPLETED
    assert registry.records["sim-1"].aistor_upload_error is None
    assert system_discovery.download_calls == ["sim-1", "sim-1"]
    assert len(aistor.uploads) == 1
    assert _has_canonical_time(aistor.uploads[0][1])


def test_detail_reuses_visualization_and_handles_pending_and_unavailable() -> None:
    registry = FakeRegistry()
    aistor = FakeAIStor()
    visualization = FakeVisualization()
    artifacts = FakeArtifacts()
    postprocessor = FakePostprocessor()
    record = _record("sim-1", SystemDiscoverySimulationState.COMPLETED)
    record = replace(
        record,
        aistor_object_key="system-discovery/simulations/sim-1/results.zip",
        aistor_uploaded_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
    )
    registry.records["sim-1"] = record
    aistor.objects[record.simulation_id] = _zip(
        {"results.csv": b"time;x;y\n0;1;2\n1;3;4\n"}
    )
    bus = _bus(
        registry=registry,
        aistor=aistor,
        artifacts=artifacts,
        postprocessor=postprocessor,
        visualization=visualization,
    )

    pending = bus.handle(GetSystemDiscoverySimulationDetails("sim-1"))
    ready = bus.handle(GetSystemDiscoverySimulationDetails("sim-1"))
    visualization.unavailable = True
    unavailable = bus.handle(GetSystemDiscoverySimulationDetails("sim-1"))

    assert pending.visualization.state == SystemDiscoverySimulationVisualizationState.PENDING
    assert pending.visualization.waiting_message == "Waiting for visualization."
    assert ready.simulation.visualization_plot_id == "plot-1"
    assert len(visualization.rendered) == 1
    assert visualization.rendered[0][0] == (
        b"results-csv-zip:" + aistor.objects[record.simulation_id]
    )
    assert aistor.uploads == []
    assert unavailable.visualization.state == SystemDiscoverySimulationVisualizationState.UNAVAILABLE


def test_detail_repairs_legacy_stored_zip_before_visualization() -> None:
    registry = FakeRegistry()
    aistor = FakeAIStor()
    visualization = FakeVisualization()
    postprocessor = SystemDiscoverySimulationResultsArchivePostprocessor()
    record = replace(
        _record("sim-1", SystemDiscoverySimulationState.COMPLETED),
        aistor_object_key="system-discovery/simulations/sim-1/results.zip",
        aistor_uploaded_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
    )
    registry.records["sim-1"] = record
    aistor.objects["sim-1"] = _zip({"results.csv": b"x;y\n1;2\n3;4\n"})
    bus = _bus(
        registry=registry,
        aistor=aistor,
        postprocessor=postprocessor,
        visualization=visualization,
    )

    result = bus.handle(GetSystemDiscoverySimulationDetails("sim-1"))

    assert result.failures == []
    assert len(aistor.uploads) == 1
    assert aistor.uploads[0][0] == "sim-1"
    assert _has_canonical_time(aistor.uploads[0][1])
    rendered_archive = visualization.rendered[0][0].removeprefix(b"results-csv-zip:")
    assert _member_text(rendered_archive, "results.csv").splitlines() == [
        "time;x;y",
        "0;1;2",
        "1;3;4",
    ]
    assert registry.records["sim-1"].state == SystemDiscoverySimulationState.COMPLETED


def test_detail_repairs_comma_delimited_legacy_zip_before_visualization() -> None:
    registry = FakeRegistry()
    aistor = FakeAIStor()
    visualization = FakeVisualization()
    postprocessor = SystemDiscoverySimulationResultsArchivePostprocessor()
    record = replace(
        _record("sim-1", SystemDiscoverySimulationState.COMPLETED),
        aistor_object_key="system-discovery/simulations/sim-1/results.zip",
        aistor_uploaded_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
    )
    registry.records["sim-1"] = record
    aistor.objects["sim-1"] = _zip(
        {"results.csv": b"time,x,y\n10,1,2\n11,3,4\n"}
    )
    bus = _bus(
        registry=registry,
        aistor=aistor,
        postprocessor=postprocessor,
        visualization=visualization,
    )

    result = bus.handle(GetSystemDiscoverySimulationDetails("sim-1"))

    assert result.failures == []
    assert len(aistor.uploads) == 1
    assert _member_text(aistor.uploads[0][1], "results.csv").splitlines() == [
        "time;x;y",
        "0;1;2",
        "1;3;4",
    ]
    rendered_archive = visualization.rendered[0][0].removeprefix(b"results-csv-zip:")
    assert _member_text(rendered_archive, "results.csv").startswith("time;x;y\n")


def test_detail_repair_failure_does_not_change_completed_state() -> None:
    registry = FakeRegistry()
    aistor = FakeAIStor()
    postprocessor = FakePostprocessor()
    postprocessor.fail = True
    record = replace(
        _record("sim-1", SystemDiscoverySimulationState.COMPLETED),
        aistor_object_key="system-discovery/simulations/sim-1/results.zip",
        aistor_uploaded_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
    )
    registry.records["sim-1"] = record
    aistor.objects["sim-1"] = _zip({"results.csv": b"x;y\n1;2\n"})
    bus = _bus(registry=registry, aistor=aistor, postprocessor=postprocessor)

    result = bus.handle(GetSystemDiscoverySimulationDetails("sim-1"))

    assert len(result.failures) == 1
    assert result.visualization.state == SystemDiscoverySimulationVisualizationState.UNAVAILABLE
    assert registry.records["sim-1"].state == SystemDiscoverySimulationState.COMPLETED
    assert aistor.uploads == []


def test_registry_simulation_row_mapping_returns_external_control_metadata() -> None:
    timestamp = datetime(2026, 6, 29, tzinfo=timezone.utc)

    record = _simulation_from_row(
        (
            "sim-1",
            "model-1",
            "narmax",
            timestamp,
            timestamp,
            "completed",
            "completed",
            None,
            12,
            "[1.0, 2.0]",
            True,
            None,
            None,
            None,
            None,
        )
    )

    assert record.uses_external_control_signals is True
    assert record.horizon == 12
    assert record.initial_conditions == (1.0, 2.0)


def _bus(
    system_discovery=None,
    artifacts=None,
    registry=None,
    aistor=None,
    postprocessor=None,
    visualization=None,
):
    system_discovery = system_discovery or FakeSystemDiscoveryPort()
    artifacts = artifacts or FakeArtifacts()
    registry = registry or FakeRegistry()
    aistor = aistor or FakeAIStor()
    postprocessor = postprocessor or FakePostprocessor()
    visualization = visualization or FakeVisualization()
    bus = InProcessBus()
    bus.register(
        ListSystemDiscoverySimulations,
        partial(
            handle_list_system_discovery_simulations,
            system_discovery=system_discovery,
            registry=registry,
            aistor=aistor,
            results_postprocessor=postprocessor,
            clock=FakeClock(),
        ),
    )
    bus.register(
        GetSystemDiscoverySimulationDetails,
        partial(
            handle_get_system_discovery_simulation_details,
            system_discovery=system_discovery,
            registry=registry,
            aistor=aistor,
            results_postprocessor=postprocessor,
            results_preparer=artifacts,
            visualization=visualization,
            plotsIds=PlotMapping(),
            clock=FakeClock(),
        ),
    )
    return bus


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def _has_canonical_time(archive: bytes) -> bool:
    with zipfile.ZipFile(io.BytesIO(archive), mode="r") as zf:
        rows = list(
            csv.reader(
                io.StringIO(zf.read("results.csv").decode("utf-8"), newline=""),
                delimiter=";",
            )
        )
    return rows == [
        ["time", "x", "y"],
        ["0", "1", "2"],
        ["1", "3", "4"],
    ]


def _member_text(archive: bytes, member_name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(archive), mode="r") as zf:
        return zf.read(member_name).decode("utf-8")


def _record(
    simulation_id: str,
    state: SystemDiscoverySimulationState,
) -> SystemDiscoverySimulationRecord:
    return SystemDiscoverySimulationRecord(
        simulation_id=simulation_id,
        source_model_id="model-1",
        source_model_name="narmax",
        created_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
        state=state,
        raw_status=state.value,
        error=None,
        horizon=None,
        initial_conditions=None,
        uses_external_control_signals=False,
    )
