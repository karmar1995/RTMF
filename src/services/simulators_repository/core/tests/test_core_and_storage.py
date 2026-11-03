import time

from dependency_injector import providers

from services.simulators_repository.core.abstract_image_build_worker import BuildStatus
from services.simulators_repository.core.abstract_simulator_repository import BuildSpec, SimulatorRegistrationRequest
from services.simulators_repository.core.abstract_simulators_storage import SimulatorEntry
from services.simulators_repository.core.tests.fake_repository_service import (
    FakeRepositoryServiceContainer,
    default_config,
)
from services.simulators_repository.core.tests.utils.fake_image_build_worker import FakeImageBuildWorker


# TODO: Fix async storage persistence in tests.
# def test_storage_persists_finished_job_entry():
#     # Ensure finished jobs are persisted to storage.
#     repository, container = _create_repository()
#     build_id = repository.submit_simulator_registration(_dummy_request("sim-store-1"))
#     status = _wait_for_status(repository, build_id, {"succeeded"})
#     assert status == "succeeded"
#     _wait_for_storage(repository, build_id)
#     entry = container.fake_storage().get_simulator("sim-store-1")
#     assert entry is not None


# TODO: Fix async storage persistence in tests.
# def test_storage_does_not_duplicate_entries():
#     # Ensure storage does not create duplicate entries for the same build id.
#     repository, container = _create_repository()
#     build_id = repository.submit_simulator_registration(_dummy_request("sim-store-2"))
#     status = _wait_for_status(repository, build_id, {"succeeded"})
#     assert status == "succeeded"
#     _wait_for_storage(repository, build_id)
#     names = container.fake_storage().list_simulator_names()
#     assert names.count("sim-store-2") == 1


def test_get_simulator_details_returns_valid_entry():
    # Ensure controller returns SimulatorDetails for stored simulator.
    repository, _ = _create_repository()
    build_id = repository.submit_simulator_registration(_dummy_request("sim-store-3"))
    status = _wait_for_status(repository, build_id, {"succeeded"})
    assert status == "succeeded"
    data = repository.get_simulators_details(["sim-store-3"])[0]
    assert data.model_name == "sim-store-3"
    assert data.bin_url != ""


# TODO: Fix async storage persistence in tests.
# def test_storage_persists_all_fields():
#     # Ensure storage persists all simulator fields including tags and params.
#     repository, container = _create_repository()
#     request = _dummy_request("sim-store-4", with_params=True)
#     build_id = repository.submit_simulator_registration(request)
#     status = _wait_for_status(repository, build_id, {"succeeded"})
#     assert status == "succeeded"
#     _wait_for_storage(repository, build_id)
#     entry = container.fake_storage().get_simulator("sim-store-4")
#     assert entry is not None
#     assert entry.image_reference_url != ""
#     assert entry.image_digest != ""
#     assert entry.image_tags != []
#     assert entry.input_params != []
#     assert entry.output_params != []


# TODO: Fix async storage persistence in tests.
# def test_storage_updates_existing_entry_on_insert():
#     # Ensure insert overwrites existing entry on conflict.
#     repository, container = _create_repository()
#     entry = SimulatorEntry(
#         model_name="sim-store-5",
#         version="0.1.0",
#         image_reference_url="repo/old:1",
#         image_digest="sha256:old",
#         image_tags=["old"],
#         input_params=[],
#         output_params=[],
#     )
#     container.fake_storage().insert(entry)
#
#     build_id = repository.submit_simulator_registration(_dummy_request("sim-store-5"))
#     status = _wait_for_status(repository, build_id, {"succeeded"})
#     assert status == "succeeded"
#     _wait_for_storage(repository, build_id)
#     updated = container.fake_storage().get_simulator("sim-store-5")
#     assert updated.version != "0.1.0"
#     assert updated.image_reference_url != "repo/old:1"


def test_storage_returns_placeholder_for_missing_simulator():
    # Ensure controller returns placeholder for missing simulator data.
    repository, _ = _create_repository()
    data = repository.get_simulators_details(["missing-sim"])[0]
    assert data.model_name == "missing-sim"


def _create_repository(config_overrides=None):
    container = FakeRepositoryServiceContainer()
    container.fake_build_worker.override(
        providers.Factory(
            FakeImageBuildWorker, polls_to_complete=1, final_status=BuildStatus.SUCCEEDED
        )
    )
    config = default_config(**(config_overrides or {}))
    container.config.from_dict(config)
    repository = container.abstract_simulator_repository()
    return repository, container


def _dummy_request(
    model_name: str, with_params: bool = False
) -> SimulatorRegistrationRequest:
    spec = {
        "platform": {"os": "linux", "arch": "amd64"},
        "technology": {"type": "python", "python": {"version": "3.11"}},
        "artifacts": {"zip": {"destination": "/opt/sim"}},
        "runtime": {"cmd": ["python", "/opt/sim/main.py"]},
    }
    input_params = []
    output_params = []
    if with_params:
        from services.simulators_repository.core.abstract_simulator_repository import ParameterSpec, ParamType

        input_params = [ParameterSpec(name="in1", type=ParamType.INT)]
        output_params = [ParameterSpec(name="out1", type=ParamType.FLOAT)]
    return SimulatorRegistrationRequest(
        model_name,
        "sim.zip",
        b"dummy",
        input_params,
        output_params,
        BuildSpec(spec),
    )


def _wait_for_status(repository, build_id: str, expected: set[str], timeout_s: float = 2.0) -> str:
    start = time.time()
    status = repository.get_registration_status([build_id])[0].status
    if status in expected:
        return status
    while time.time() - start < timeout_s:
        status = repository.get_registration_status([build_id])[0].status
        if status in expected:
            return status
        time.sleep(0.05)
    return status


def _wait_for_storage(repository, build_id: str, timeout_s: float = 2.0) -> None:
    start = time.time()
    status = repository.get_registration_status([build_id])[0].status
    if status == "succeeded":
        return
    while time.time() - start < timeout_s:
        status = repository.get_registration_status([build_id])[0].status
        if status == "succeeded":
            return
        time.sleep(0.05)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
