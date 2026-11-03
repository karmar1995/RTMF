from services.simulators_repository.build_worker.details.dockerfile_builder import DockerfileBuilder
from services.simulators_repository.build_worker.details.dockerfile_director import BaseImageCatalog, DockerfileDirector
from services.simulators_repository.build_worker.details.buildkit_worker import BuildKitImageBuildWorker
from services.simulators_repository.core.abstract_image_build_worker import BuildRequest


def test_dockerfile_director_stores_base_image_catalog():
    builder = DockerfileBuilder()
    catalog = BaseImageCatalog(
        python_prefix="base/python",
        java_prefix="base/java",
        native_image="base/native:latest",
    )
    director = DockerfileDirector(builder, catalog)
    assert director._base_images == catalog


def test_build_worker_creates_base_image_catalog_from_config():
    worker = BuildKitImageBuildWorker(
        {
            "harbor_registry": "172.16.237.193:80",
            "base_python_image_prefix": "base/python",
            "base_java_image_prefix": "base/java",
            "base_native_image": "base/native:latest",
        }
    )
    catalog = worker._base_image_catalog()
    assert catalog.python_prefix == "172.16.237.193:80/base/python"
    assert catalog.java_prefix == "172.16.237.193:80/base/java"
    assert catalog.native_image == "172.16.237.193:80/base/native:latest"


def test_build_worker_does_not_double_prefix_existing_registry():
    worker = BuildKitImageBuildWorker(
        {
            "harbor_registry": "172.16.237.193:80",
            "base_python_image_prefix": "172.16.237.193:80/base/python",
            "base_java_image_prefix": "172.16.237.193:80/base/java",
            "base_native_image": "172.16.237.193:80/base/native:latest",
        }
    )
    catalog = worker._base_image_catalog()
    assert catalog.python_prefix == "172.16.237.193:80/base/python"
    assert catalog.java_prefix == "172.16.237.193:80/base/java"
    assert catalog.native_image == "172.16.237.193:80/base/native:latest"


def test_python_version_to_suffix():
    builder = DockerfileBuilder()
    catalog = BaseImageCatalog(
        python_prefix="base/worker-0.1.0-base-python",
        java_prefix="base/worker-0.1.0-base-java",
        native_image="base/worker-0.1.0-base-native",
    )
    director = DockerfileDirector(builder, catalog)
    assert director._python_version_to_suffix("3.9") == "309"
    assert director._python_version_to_suffix("3.10") == "310"
    assert director._python_version_to_suffix("3.11") == "311"


def test_select_base_image_uses_python_prefix():
    builder = DockerfileBuilder()
    catalog = BaseImageCatalog(
        python_prefix="base/worker-0.1.0-base-python",
        java_prefix="base/worker-0.1.0-base-java",
        native_image="base/worker-0.1.0-base-native",
    )
    director = DockerfileDirector(builder, catalog)
    platform = {"os": "linux", "arch": "amd64"}
    technology = {"type": "python", "python": {"version": "3.10"}}
    build = {}
    assert (
        director._select_base_image(platform, technology, build)
        == "base/worker-0.1.0-base-python-310"
    )


def test_select_base_image_respects_override():
    builder = DockerfileBuilder()
    catalog = BaseImageCatalog(
        python_prefix="base/worker-0.1.0-base-python",
        java_prefix="base/worker-0.1.0-base-java",
        native_image="base/worker-0.1.0-base-native",
    )
    director = DockerfileDirector(builder, catalog)
    platform = {"os": "linux", "arch": "amd64"}
    technology = {"type": "python", "python": {"version": "3.10"}}
    build = {"base_image": "override/image:latest"}
    assert (
        director._select_base_image(platform, technology, build)
        == "override/image:latest"
    )


def test_build_worker_defaults_artifacts_zip_path_to_upload_zip():
    worker = BuildKitImageBuildWorker(
        {
            "harbor_registry": "172.16.237.193:80",
            "base_python_image_prefix": "base/worker-0.1.0-base-python",
            "base_java_image_prefix": "base/worker-0.1.0-base-java",
            "base_native_image": "base/worker-0.1.0-base-native",
        }
    )
    request = BuildRequest(
        build_id="build-1",
        model_name="sim",
        version_id="1.0.0",
        zip_filename="sim.zip",
        zip_bytes=b"dummy-zip",
        build_spec={
            "platform": {"os": "linux", "arch": "amd64"},
            "technology": {"type": "python", "python": {"version": "3.11"}},
        },
    )

    dockerfile = worker._generate_dockerfile(request)
    assert "COPY upload.zip /tmp/user_sim.zip" in dockerfile
