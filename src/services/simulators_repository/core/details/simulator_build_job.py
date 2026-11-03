import uuid

from services.simulators_repository.core.abstract_image_build_worker import AbstractImageBuildWorker, BuildRequest
from services.simulators_repository.core.abstract_simulator_repository import SimulatorRegistrationResult
from services.simulators_repository.core.details.versioned_simulator_registration_request import (
    VersionedSimulatorRegistrationRequest,
)


class SimulatorBuildJob:
    """
    Encapsulates a single simulator build request and its lifecycle.
    """

    def __init__(
        self,
        build_worker: AbstractImageBuildWorker,
        request: VersionedSimulatorRegistrationRequest,
        build_id: str | None = None,
    ) -> None:
        if build_worker is None:
            raise ValueError("build_worker is required")
        if request is None:
            raise ValueError("request is required")

        self._build_worker = build_worker
        self._request = request
        self._build_id = build_id or str(uuid.uuid4())
        self._submitted = False
        self._cached_status = None
        self._image_reference_url = None
        self._image_digest = None
        self._image_tags = None

        self._build_request = BuildRequest(
            build_id=self._build_id,
            model_name=self._request.model_name,
            version_id=self._request.version,
            zip_filename=self._request.zip_filename,
            zip_bytes=self._request.zip_bytes,
            build_spec=self._request.build.spec,
        )

    @property
    def build_id(self) -> str:
        return self._build_id

    @property
    def model_name(self) -> str:
        return self._request.model_name

    @property
    def version(self) -> str:
        return self._request.version

    @property
    def image_reference_url(self) -> str | None:
        return self._image_reference_url

    @property
    def image_digest(self) -> str | None:
        return self._image_digest

    @property
    def image_tags(self) -> list[str] | None:
        return list(self._image_tags) if self._image_tags is not None else None

    def input_params(self) -> list[tuple[str, str]]:
        params = self._request.input_params or []
        return [(param.name, param.type.value) for param in params]

    def output_params(self) -> list[tuple[str, str]]:
        params = self._request.output_params or []
        return [(param.name, param.type.value) for param in params]

    def submit(self) -> str:
        if not self._submitted:
            self._build_worker.submit_build(self._build_request)
            self._submitted = True
            self._cached_status = "running"
        return self._build_id

    def get_status(self) -> SimulatorRegistrationResult:
        return SimulatorRegistrationResult(
            model_name=self.model_name,
            version=self.version,
            build_id=self._build_id,
            status=self._cached_status or "running",
        )

    def update_build_status(self) -> SimulatorRegistrationResult:
        if self._build_worker is not None:
            result = self._build_worker.get_build_status(self._build_id)
            self._cached_status = result.status.value
            self._image_reference_url = result.image_ref
            self._image_digest = result.image_digest
            self._image_tags = list(result.image_tags or [])
        return self.get_status()

    def on_job_finished(self) -> None:
        self._build_worker = None
