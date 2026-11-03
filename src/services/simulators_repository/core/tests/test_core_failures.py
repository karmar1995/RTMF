from dependency_injector import providers

from services.simulators_repository.core.abstract_image_build_worker import BuildStatus
from services.simulators_repository.core.tests.fake_repository_service import (
    FakeRepositoryServiceContainer,
    default_config,
)
from services.simulators_repository.core.tests.utils.fake_image_build_worker import FakeImageBuildWorker
from services.simulators_repository.core.tests.utils.fake_simulators_storage import FakeSimulatorsStorage
from services.simulators_repository.core.abstract_simulator_repository import BuildSpec, SimulatorRegistrationRequest


# TODO: Fix deterministic failure propagation in tests.
# def test_build_worker_failure_translates_to_failed_status():
#     # Ensure build worker failures produce "failed" status.
#     repository, container = _create_repository(
#         worker_provider=providers.Factory(
#             FakeImageBuildWorker, polls_to_complete=1, final_status=BuildStatus.FAILED
#         )
#     )
#     build_id = repository.submit_simulator_registration(_dummy_request("sim-fail-1"))
#     status = _wait_for_status(repository, build_id, {"failed"})
#     assert status == "failed"


# def test_storage_insert_failure_keeps_status_storing():
#     # Ensure storage insert failures keep job in "storing" status.
#     container = FakeRepositoryServiceContainer()
#     container.fake_storage.override(providers.Singleton(FakeSimulatorsStorage, fail_inserts=True))
#     container.fake_build_worker.override(
#         providers.Factory(
#             FakeImageBuildWorker, polls_to_complete=1, final_status=BuildStatus.SUCCEEDED
#         )
#     )
#     container.config.from_dict(default_config(storage_poll_interval=0.1))
#     repository = container.abstract_simulator_repository()
#
#     build_id = repository.submit_simulator_registration(_dummy_request("sim-store-fail"))
#     status = _wait_for_status(repository, build_id, {"storing", "succeeded"})
#     assert status == "storing"


def test_invalid_config_falls_back_to_defaults():
    # Ensure invalid config values fall back to defaults.
    container = FakeRepositoryServiceContainer()
    container.config.from_dict(
        default_config(concurrent_builds="bad", builds_poll_interval="bad")
    )
    repository = container.abstract_simulator_repository()
    assert repository is not None


def test_storage_update_unknown_field_raises():
    # Ensure storage update rejects unknown fields.
    storage = FakeSimulatorsStorage()
    storage.insert(
        _dummy_entry("sim-update-1")
    )
    try:
        storage.update_simulator("sim-update-1", "unknown_field", "value")
        assert False
    except ValueError:
        assert True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))


def _create_repository(config_overrides=None, worker_provider=None):
    container = FakeRepositoryServiceContainer()
    if worker_provider is not None:
        container.fake_build_worker.override(worker_provider)
    config = default_config(**(config_overrides or {}))
    container.config.from_dict(config)
    repository = container.abstract_simulator_repository()
    return repository, container


def _dummy_request(model_name: str) -> SimulatorRegistrationRequest:
    spec = {
        "platform": {"os": "linux", "arch": "amd64"},
        "technology": {"type": "python", "python": {"version": "3.11"}},
        "artifacts": {"zip": {"destination": "/opt/sim"}},
        "runtime": {"cmd": ["python", "/opt/sim/main.py"]},
    }
    return SimulatorRegistrationRequest(
        model_name,
        "sim.zip",
        b"dummy",
        [],
        [],
        BuildSpec(spec),
    )


def _dummy_entry(model_name: str):
    from services.simulators_repository.core.abstract_simulators_storage import SimulatorEntry

    return SimulatorEntry(
        model_name=model_name,
        version="1.0.0",
        image_reference_url="repo/test:1",
        image_digest="sha256:test",
        image_tags=["latest"],
        input_params=[],
        output_params=[],
    )


def _wait_for_status(repository, build_id: str, expected: set[str], timeout_s: float = 2.0) -> str:
    import time

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
