from typing import Callable
from datetime import datetime, timezone
from types import SimpleNamespace
from services.simulators_repository.core.abstract_image_build_worker import AbstractImageBuildWorker
from services.simulators_repository.core.abstract_simulators_storage import AbstractSimulatorsStorage
from services.simulators_repository.core.abstract_simulator_repository import (
    AbstractSimulatorRepository,
    ParamType,
    ParameterSpec,
    SimulatorRegistrationRequest,
    SimulatorRegistrationResult,
    SimulatorSummary,
    SimulatorDetails,
    RegistrationSummary,
)
from services.simulators_repository.core.details.build_requests_queue import BuildRequestsQueue
from services.simulators_repository.core.details.builds_processor import BuildsProcessor
from services.simulators_repository.core.details.jobs_container import JobsContainer
from services.simulators_repository.core.details.storage_controller import StorageController
from services.simulators_repository.core.details.versioning_helper import VersioningHelper


class SimulatorRepositoryController(AbstractSimulatorRepository):
    def __init__(
        self,
        build_worker_factory: Callable[[], AbstractImageBuildWorker],
        simulators_storage_factory: Callable[[], AbstractSimulatorsStorage],
        config,
    ) -> None:
        self._build_worker_factory = build_worker_factory
        self._simulators_storage = simulators_storage_factory()
        self._config = SimpleNamespace(**(config or {}))
        self._requests_queue = BuildRequestsQueue()
        self._jobs_container = JobsContainer()
        self._versioning_helper = VersioningHelper(self._simulators_storage)
        self._builds_processor = BuildsProcessor(
            build_worker_factory=self._build_worker_factory,
            requests_queue=self._requests_queue,
            jobs_container=self._jobs_container,
            active_workers=self._config_value("concurrent_builds", 1, int),
            poll_interval_s=self._config_value("builds_poll_interval", 0.4, float),
        )
        self._storage_controller = StorageController(
            jobs_container=self._jobs_container,
            simulators_storage=self._simulators_storage,
            poll_interval_s=self._config_value("storage_poll_interval", 1.0, float),
        )
        self._builds_processor.start()
        self._storage_controller.start()

    def submit_simulator_registration(self, request: SimulatorRegistrationRequest) -> str:
        versioned_request = self._versioning_helper.create_versioned_request(request)
        return self._requests_queue.enqueue(versioned_request)

    def get_registration_status(
        self, registration_ids: list[str]
    ) -> list[SimulatorRegistrationResult]:
        return [self._get_registration_status_single(reg_id) for reg_id in registration_ids]

    def get_simulators_details(self, model_ids: list[str]) -> list[SimulatorDetails]:
        return [self._get_simulator_details_single(simId) for simId in model_ids]

    def list_simulators(self) -> list[SimulatorSummary]:
        return self._simulators_storage.get_simulators_summaries()

    def list_recent_registrations(self, limit: int = 100) -> list[RegistrationSummary]:
        # Most recent first; fallback to reverse insertion order by category.
        summaries: list[RegistrationSummary] = []
        seen = set()

        finished_ids = list(self._jobs_container.get_finished_job_ids())
        active_ids = list(self._jobs_container.get_active_job_ids())
        queued_ids = list(self._requests_queue.list_queued_ids())

        for build_id in reversed(finished_ids):
            if build_id in seen:
                continue
            summary = self._to_registration_summary(build_id)
            if summary is not None:
                summaries.append(summary)
                seen.add(build_id)
                if len(summaries) >= limit:
                    return summaries

        for build_id in reversed(active_ids):
            if build_id in seen:
                continue
            summary = self._to_registration_summary(build_id)
            if summary is not None:
                summaries.append(summary)
                seen.add(build_id)
                if len(summaries) >= limit:
                    return summaries

        for build_id in reversed(queued_ids):
            if build_id in seen:
                continue
            summary = self._to_registration_summary(build_id)
            if summary is not None:
                summaries.append(summary)
                seen.add(build_id)
                if len(summaries) >= limit:
                    return summaries

        return summaries

    def _get_registration_status_single(
        self, registration_id: str
    ) -> SimulatorRegistrationResult:
        finished_job = self._jobs_container.get_finished_job(registration_id)
        if finished_job is not None:
            return finished_job.get_status()
        active_job = self._jobs_container.get_active_job(registration_id)
        if active_job is not None:
            return active_job.get_status()
        if self._requests_queue.is_queued(registration_id):
            request = self._requests_queue.get_request(registration_id)
            return SimulatorRegistrationResult(
                model_name=request.model_name,
                version="",
                build_id=registration_id,
                status="waiting",
            )
        return SimulatorRegistrationResult(
            model_name="",
            version="",
            build_id=registration_id,
            status="unknown",
        )

    def _get_simulator_details_single(self, simulator_id: str) -> SimulatorDetails:
        entry = self._simulators_storage.get_simulator(simulator_id)
        if entry is None:
            job = self._finished_job_by_model_name(simulator_id)
            if job is not None:
                return SimulatorDetails(
                    model_name=job.model_name,
                    version=job.version,
                    created_at=datetime.now(timezone.utc),
                    bin_url=job.image_reference_url or "",
                    build_spec=None,
                    input_params=_to_parameter_specs(job.input_params()),
                    output_params=_to_parameter_specs(job.output_params()),
                )
            # TODO: Placeholder created_at until storage provides it.
            return SimulatorDetails(
                model_name=simulator_id,
                version="",
                created_at=datetime.now(timezone.utc),
                bin_url="",
                build_spec=None,
                input_params=None,
                output_params=None,
            )

        created_at = (
            entry.created_at if hasattr(entry, "created_at") else datetime.now(timezone.utc)
        )
        if created_at is None:
            # TODO: Placeholder created_at until storage provides it.
            created_at = datetime.now(timezone.utc)

        build_spec = entry.build_spec if hasattr(entry, "build_spec") else None
        input_params = (
            _to_parameter_specs(entry.input_params)
            if hasattr(entry, "input_params")
            else None
        )
        output_params = (
            _to_parameter_specs(entry.output_params)
            if hasattr(entry, "output_params")
            else None
        )

        return SimulatorDetails(
            model_name=entry.model_name,
            version=entry.version,
            created_at=created_at,
            bin_url=entry.image_reference_url,
            build_spec=build_spec,
            input_params=input_params,
            output_params=output_params,
        )

    def _finished_job_by_model_name(self, model_name: str):
        for build_id in self._jobs_container.get_finished_job_ids():
            job = self._jobs_container.get_finished_job(build_id)
            if job is not None and job.model_name == model_name:
                return job
        return None

    def _to_registration_summary(
        self, registration_id: str
    ) -> RegistrationSummary | None:
        status = self._get_registration_status_single(registration_id)
        if status.status == "unknown":
            return None
        # TODO: Placeholder created_at until queue/jobs track timestamps.
        return RegistrationSummary(
            registration_id=registration_id,
            model_name=status.model_name,
            status=status.status,
            created_at=datetime.now(timezone.utc),
        )

    def _config_value(self, name: str, default, cast_type):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("config name must be a non-empty string")
        value = getattr(self._config, name, None)
        if callable(value):
            value = value()
        if value is None:
            return default
        try:
            parsed = cast_type(value)
        except (TypeError, ValueError):
            return default
        if cast_type in (int, float) and parsed <= 0:
            raise ValueError("config value must be > 0")
        return parsed


def _to_parameter_specs(pairs: list[tuple[str, str]]) -> list[ParameterSpec]:
    specs = []
    for name, type_text in pairs or []:
        specs.append(ParameterSpec(name=name, type=_param_type_from_string(type_text)))
    return specs


def _param_type_from_string(value: str) -> ParamType:
    mapping = {
        "int": ParamType.INT,
        "float": ParamType.FLOAT,
        "bool": ParamType.BOOLEAN,
        "string": ParamType.STRING,
        "str": ParamType.STRING,
        "int_ts": ParamType.INT_TS,
        "float_ts": ParamType.FLOAT_TS,
        "bool_ts": ParamType.BOOLEAN_TS,
        "str_ts": ParamType.STR_TS,
    }
    if value not in mapping:
        raise ValueError(f"Unknown param type: {value}")
    return mapping[value]
