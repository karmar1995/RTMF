from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class BuildStatus(Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class BuildRequest:
    """
    Internal request to build and publish a simulator image.

    Notes:
    - Image registry/repository settings are intentionally NOT included here.
      They belong to the build worker configuration.
    - `zip_bytes` can later be replaced by a zip_uri/object-storage pointer when
      the build worker is moved behind a REST boundary.
    """

    build_id: str

    model_name: str
    version_id: str

    zip_filename: str
    zip_bytes: bytes

    build_spec: dict  # parsed sim.yaml (or your BuildSpec.spec)


@dataclass(frozen=True)
class BuildResult:
    build_id: str
    status: BuildStatus

    # Immutable reference for execution (includes configured registry/repo)
    image_ref: str = None  # e.g. "<registry>/<repo>/<model>@sha256:..."

    # Optional diagnostic/provenance fields
    image_digest: str = None  # e.g. "sha256:..."
    image_tags: list = None
    logs: str = None  # short text; large logs should go to storage and be referenced
    error: str = None  # short failure reason


class AbstractImageBuildWorker(ABC):
    """
    Abstract boundary for building and publishing simulator images.

    The implementation is configured with:
      - registry endpoint / credentials
      - repository naming policy
      - build engine (BuildKit/buildx/buildah/kaniko)
      - caching and logging policy

    Later, you can replace the implementation with a REST client without changing
    the Simulators Repository domain layer.
    """

    @abstractmethod
    def submit_build(self, request: BuildRequest) -> str:
        """
        Start a build and return the build_id.
        Implementations may build synchronously or enqueue asynchronously.
        """
        raise NotImplementedError

    @abstractmethod
    def get_build_status(self, build_id: str) -> BuildResult:
        """
        Return the current status (and any available result fields) for a build_id.
        """
        raise NotImplementedError

    @abstractmethod
    def cancel_build(self, build_id: str) -> bool:
        """
        Attempt to cancel the build. Returns True if cancel was requested/accepted.
        """
        raise NotImplementedError
