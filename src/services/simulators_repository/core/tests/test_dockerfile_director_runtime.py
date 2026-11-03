from services.simulators_repository.build_worker.details.dockerfile_builder import DockerfileBuilder
from services.simulators_repository.build_worker.details.dockerfile_director import BaseImageCatalog, DockerfileDirector


def test_director_emits_no_cmd_or_entrypoint():
    director = _director()
    config = _base_config()
    dockerfile = director.render(config)
    assert "CMD " not in dockerfile
    assert "ENTRYPOINT " not in dockerfile


def test_python_deps_install_into_simulator_venv():
    director = _director()
    config = _base_config()
    config["artifacts"] = {"zip": {"path": "upload.zip"}}
    config["technology"]["python"]["packages"] = [{"name": "numpy"}]
    dockerfile = director.render(config)
    assert "COPY upload.zip /tmp/user_sim.zip" in dockerfile
    assert ".venv/" in dockerfile
    assert "/opt/simulator/.venv/bin/python -m pip install --no-cache-dir numpy" in dockerfile
    assert "/opt/venv" not in dockerfile
    assert "python -m venv" not in dockerfile
    assert "FROM base/worker-0.1.0-base-python-311" in dockerfile


def test_unknown_top_level_key_is_rejected():
    director = _director()
    config = _base_config()
    config["unknown"] = {}
    try:
        director.render(config)
        assert False
    except ValueError as exc:
        assert str(exc) == "Unknown field: config.unknown"


def test_artifacts_destination_is_rejected():
    director = _director()
    config = _base_config()
    config["artifacts"] = {"zip": {"path": "upload.zip", "destination": "/opt/simulator"}}
    try:
        director.render(config)
        assert False
    except ValueError as exc:
        assert (
            str(exc)
            == "artifacts.zip.destination is not supported; destination is fixed to /opt/simulator"
        )


def test_windows_platform_is_not_supported():
    director = _director()
    config = _base_config()
    config["platform"]["os"] = "windows"
    try:
        director.render(config)
        assert False
    except NotImplementedError:
        assert True


def test_non_python_technology_is_not_supported():
    director = _director()
    config = _base_config()
    config["technology"]["type"] = "java"
    del config["technology"]["python"]
    try:
        director.render(config)
        assert False
    except NotImplementedError:
        assert True


def test_unknown_python_key_is_rejected():
    director = _director()
    config = _base_config()
    config["technology"]["python"]["requirements_file"] = "requirements.txt"
    try:
        director.render(config)
        assert False
    except ValueError as exc:
        assert str(exc) == "Unknown field: technology.python.requirements_file"


def test_missing_required_version_is_rejected():
    director = _director()
    config = _base_config()
    del config["technology"]["python"]["version"]
    try:
        director.render(config)
        assert False
    except ValueError as exc:
        assert str(exc) == "technology.python.version is required"


def test_missing_platform_is_rejected():
    director = _director()
    config = _base_config()
    del config["platform"]
    try:
        director.render(config)
        assert False
    except ValueError as exc:
        assert str(exc) == "platform is required and must be a dict"


def test_missing_technology_type_is_rejected():
    director = _director()
    config = _base_config()
    del config["technology"]["type"]
    try:
        director.render(config)
        assert False
    except ValueError as exc:
        assert str(exc) == "technology.type must be a non-empty string"


def _director() -> DockerfileDirector:
    builder = DockerfileBuilder()
    catalog = BaseImageCatalog(
        python_prefix="base/worker-0.1.0-base-python",
        java_prefix="base/worker-0.1.0-base-java",
        native_image="base/worker-0.1.0-base-native",
    )
    return DockerfileDirector(builder, catalog)


def _base_config() -> dict:
    return {
        "platform": {"os": "linux", "arch": "amd64"},
        "technology": {"type": "python", "python": {"version": "3.11"}},
        "artifacts": {"zip": {"path": "upload.zip"}},
    }

if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
