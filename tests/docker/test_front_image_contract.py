from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_front_dockerfile_includes_in_process_use_case_dependency_tree() -> None:
    dockerfile = _read("docker/front/Dockerfile")

    assert "COPY src/services ./src/services" in dockerfile
    assert "COPY src/adapters ./src/adapters" in dockerfile
    assert "COPY src/use_case_contracts ./src/use_case_contracts" in dockerfile
    assert "COPY src/adapters/keycloak_identity_adapter" not in dockerfile


def test_front_dockerfile_has_build_time_import_smoke_check() -> None:
    dockerfile = _read("docker/front/Dockerfile")

    assert "adapters.keycloak_identity_adapter.composition" in dockerfile
    assert "import use_case_contracts" in dockerfile
    assert "services.use_case.composition.build_usecases" in dockerfile
    assert "import services.front.__main__" in dockerfile


def test_dockerignore_keeps_front_shared_packages_in_build_context() -> None:
    dockerignore = _read(".dockerignore").splitlines()
    forbidden_excludes = {
        "src/adapters",
        "src/adapters/",
        "src/adapters/keycloak_identity_adapter",
        "src/adapters/keycloak_identity_adapter/",
        "src/use_case_contracts",
        "src/use_case_contracts/",
        "src/services/use_case",
        "src/services/use_case/",
    }

    assert forbidden_excludes.isdisjoint(set(dockerignore))


def test_front_image_smoke_script_validates_shared_composition_imports() -> None:
    script = _read("docker/scripts/docker_smoke_test_images.sh")

    assert "adapters.keycloak_identity_adapter.composition" in script
    assert "import use_case_contracts" in script
    assert "services.use_case.composition.build_usecases" in script
    assert "import services.front.__main__" in script
