from services.simulators_repository.core.abstract_simulator_repository import BuildSpec, SimulatorRegistrationRequest
from services.simulators_repository.core.abstract_simulators_storage import SimulatorEntry
from services.simulators_repository.core.tests.fake_repository_service import (
    FakeRepositoryServiceContainer,
    default_config,
)


def test_core_initialization():
    container = FakeRepositoryServiceContainer()
    container.config.from_dict(default_config())
    repository = container.abstract_simulator_repository()
    assert repository is not None


def test_core_returns_waiting_for_queued_request():
    # Ensure registration status is "waiting" for a newly queued request.
    container = FakeRepositoryServiceContainer()
    container.config.from_dict(default_config())
    repository = container.abstract_simulator_repository()
    repository._builds_processor.stop(wait=True)

    request = _dummy_request("queued_sim")
    build_id = repository.submit_simulator_registration(request)
    status = repository.get_registration_status([build_id])[0]
    assert status.status == "waiting"


def test_core_returns_unknown_for_unknown_registration_id():
    # Ensure registration status is "unknown" for an invalid id.
    container = FakeRepositoryServiceContainer()
    container.config.from_dict(default_config())
    repository = container.abstract_simulator_repository()
    repository._builds_processor.stop(wait=True)

    status = repository.get_registration_status(["missing-id"])[0]
    assert status.status == "unknown"


def test_versioning_defaults_to_1_0_0_when_missing():
    # Ensure version defaults to 1.0.0 when simulator is not in storage.
    container = FakeRepositoryServiceContainer()
    container.config.from_dict(default_config())
    repository = container.abstract_simulator_repository()
    repository._builds_processor.stop(wait=True)

    request = _dummy_request("new_sim")
    build_id = repository.submit_simulator_registration(request)
    queued = repository._requests_queue.get_request(build_id)
    assert queued.version == "1.0.0"


def test_versioning_bumps_minor_when_existing():
    # Ensure version bumps minor and resets patch for existing simulator.
    container = FakeRepositoryServiceContainer()
    container.config.from_dict(default_config())
    repository = container.abstract_simulator_repository()
    repository._builds_processor.stop(wait=True)

    entry = SimulatorEntry(
        model_name="existing_sim",
        version="2.3.4",
        image_reference_url="repo/test:old",
        image_digest="sha256:old",
        image_tags=["old"],
        input_params=[],
        output_params=[],
    )
    repository._simulators_storage.insert(entry)

    request = _dummy_request("existing_sim")
    build_id = repository.submit_simulator_registration(request)
    queued = repository._requests_queue.get_request(build_id)
    assert queued.version == "2.4.0"


def test_versioning_invalid_version_falls_back_to_default():
    # Ensure invalid stored version results in default versioning.
    container = FakeRepositoryServiceContainer()
    container.config.from_dict(default_config())
    repository = container.abstract_simulator_repository()
    repository._builds_processor.stop(wait=True)

    entry = SimulatorEntry(
        model_name="bad_version_sim",
        version="invalid",
        image_reference_url="repo/test:old",
        image_digest="sha256:old",
        image_tags=["old"],
        input_params=[],
        output_params=[],
    )
    repository._simulators_storage.insert(entry)

    request = _dummy_request("bad_version_sim")
    build_id = repository.submit_simulator_registration(request)
    queued = repository._requests_queue.get_request(build_id)
    assert queued.version == "1.0.0"


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


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
