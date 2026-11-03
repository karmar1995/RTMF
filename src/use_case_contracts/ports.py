from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from use_case_contracts.dtos import (
    SimulatorBuildRecord,
    SimulatorDetails,
    SimulatorSummary,
    RegistrationSummary,
    RegistrationDetails,
    ScheduledBatchInfo,
    JobInfo,
    JobSummary,
    SubJobInfo,
    Job4Visualization,
    JobVisualizationPage,
    JobResultRef,
    ResultRef,
    VisualizationTarget,
    ParameterValues,
    PlotSpec,
    MatrixParameterDefinition,
    GeneratedMatrixFile,
    SensitivityAnalysisParameter,
    SensitivityAnalysisResult,
    MonteCarloFilteringResult,
    EvaluationProgress,
    EvaluationResult,
    EvaluationSummary,
    SystemDiscoveryTrainingRequest,
    SystemDiscoveryTrainingSubmission,
    SystemDiscoveryTrainingStatus,
    SystemDiscoveryTrainingResultsArchive,
    SystemDiscoverySimulationRequest,
    SystemDiscoverySimulationSubmission,
    SystemDiscoverySimulationStatus,
    SystemDiscoverySimulationResultsArchive,
    SystemDiscoveryTrainingRecord,
    SystemDiscoveryTrainingEvaluationMetadata,
    SystemDiscoverySavedModelRecord,
    SystemDiscoverySimulationRecord,
    SystemDiscoveryStoredResultsArchive,
    SystemDiscoverySimulationResultsArchivePostprocessingResult,
    BrowserLoginChallenge,
    AuthenticatedIdentity,
    DisasterStageRecognitionResult,
)


class UseCaseAPI(Protocol):
    def handle(self, message: Any) -> Any: ...


class RequestUseCaseAPIProvider(Protocol):
    def bind_session(self, raw_session_credential: str | None) -> UseCaseAPI: ...


class BrowserIdentityProvider(Protocol):
    def begin_browser_login(
        self,
        *,
        callback_url: str,
        force_reauthentication: bool = False,
    ) -> BrowserLoginChallenge: ...

    def complete_browser_login(
        self,
        *,
        authorization_code: str,
        state: str,
    ) -> AuthenticatedIdentity: ...

    def refresh_provider_session(
        self,
        provider_session_state: bytes,
    ) -> AuthenticatedIdentity: ...

    def revoke_provider_session(self, provider_session_state: bytes) -> None: ...


class CommandBus(Protocol):
    def handle(self, message: Any) -> Any: ...


class QueryBus(Protocol):
    def handle(self, message: Any) -> Any: ...


class SimulatorRepository(Protocol):
    def register(self, record: SimulatorBuildRecord) -> str: ...

    def registration_status(self, registration_id: str) -> str: ...

    def get(self, simulator_id: str) -> SimulatorDetails | None: ...

    def list_simulators(self) -> list[SimulatorSummary]: ...

    def list_recent_registrations(
        self, limit: int = 100
    ) -> list[RegistrationSummary]: ...

    def get_registration_details(
        self, registration_id: str
    ) -> RegistrationDetails | None: ...


class JobsSchedulerPort(Protocol):
    def submit_simulation_batch(
        self, simulator_uri: str, matrix_uri: str, combinations: int, simulator_id: str
    ) -> ScheduledBatchInfo: ...

    def get_job(self, job_id: str) -> JobInfo | None: ...

    def list_jobs(self) -> list[JobSummary]: ...

    def get_job_sub_jobs(self, job_id: str) -> list[SubJobInfo]: ...

    def get_sub_job_stderr(self, job_id: str, sub_job_id: str) -> str: ...

    def get_sub_job_stdout(self, job_id: str, sub_job_id: str) -> str: ...


class JobsRepositoryReaderPort(Protocol):
    def list_jobs(self) -> list[str]: ...

    def list_jobs_for_visualization(self, page: int = 1, per_page: int = 20) -> JobVisualizationPage: ...

    def job_details(self, job_id) -> JobResultRef: ...

    def list_results(self, job_id: str) -> list[ResultRef]: ...

    def resolve_visualization_target(self, target_id: str) -> VisualizationTarget:
        """Resolve either a job id or an evaluation id into a plot source.

        An evaluation is presented as one big job, so its id resolves to the
        union of every result artifact its jobs produced. This lives here so
        callers never hit the BIGINT-only ``job_id`` parsing themselves.
        """


class JobsRepositoryWriterPort(Protocol):
    def store_job(self, job_id, simulator_id, status): ...

    def update_jobs_statuses(self, job_ids_to_statuses): ...

    def get_started_jobs(self) -> list[str]: ...


class EvaluationMonitorStorePort(Protocol):
    """Read side of the evaluations store needed to build monitor entries.

    Declared here rather than reusing the evaluator's own port so the use-case
    layer keeps depending only on the contracts layer. The Postgres adapter
    satisfies this structurally.
    """

    def list_evaluation_job_links(self) -> dict[str, set[str]]:
        """Map each evaluation id to the Slurm job ids it submitted, as strings.

        The monitor needs the flat set to hide evaluation jobs from the
        simulation list, and the per-evaluation grouping to keep a finished
        evaluation visible only while one of its jobs is still live.
        """

    def list_summaries(self) -> list[dict]:
        """Per-evaluation monitor metadata, without the large JSONB payloads."""


class EvaluationResultsStorePort(Protocol):
    """Evaluations store as seen by the jobs repository.

    The jobs reader needs it to resolve an evaluation id into the union of its
    result artifacts when an evaluation is presented as one big job.
    """

    def list_results_for_evaluation(self, evaluation_id: str) -> list: ...

    def simulator_id_for_evaluation(self, evaluation_id: str) -> str: ...

    def evaluation_status(self, evaluation_id: str) -> str | None: ...


class ResultsRepositoryPort(Protocol):
    def download(self, url: str) -> bytes: ...


class SystemDiscoveryTrainingRegistryPort(Protocol):
    def register_training(self, record: SystemDiscoveryTrainingRecord) -> None: ...

    def get_training(
        self, training_id: str
    ) -> SystemDiscoveryTrainingRecord | None: ...

    def list_trainings(self) -> list[SystemDiscoveryTrainingRecord]: ...

    def update_training_status(
        self,
        training_id: str,
        *,
        state: Any,
        raw_status: str,
        training_status: str | None,
        evaluation_status: str | None,
        error: str | None,
        updated_at: Any,
    ) -> SystemDiscoveryTrainingRecord: ...

    def update_training_results_cache(
        self,
        training_id: str,
        *,
        results_archive_path: str | None,
        results_cached_at: Any | None,
        results_cache_error: str | None,
    ) -> SystemDiscoveryTrainingRecord: ...

    def archive_training(self, training_id: str, *, archived_at: Any) -> None: ...


class SystemDiscoverySavedModelRegistryPort(Protocol):
    def save_model(self, record: SystemDiscoverySavedModelRecord) -> None: ...

    def get_model(self, model_id: str) -> SystemDiscoverySavedModelRecord | None: ...

    def get_model_by_source_training_id(
        self,
        training_id: str,
    ) -> SystemDiscoverySavedModelRecord | None: ...

    def list_models(self) -> list[SystemDiscoverySavedModelRecord]: ...

    def remove_model(self, model_id: str) -> None: ...


class SystemDiscoveryTrainingResultsStoragePort(Protocol):
    def store_results_archive(self, training_id: str, content: bytes) -> str: ...

    def normalize_results_archive_key(
        self,
        training_id: str,
        stored_reference: str,
    ) -> str: ...

    def start_evaluation_postprocessing(
        self, training_id: str, archive_key: str
    ) -> str: ...

    def get_evaluation_postprocessing_status(self, training_id: str) -> str: ...

    def get_evaluation_metadata(
        self,
        training_id: str,
    ) -> SystemDiscoveryTrainingEvaluationMetadata: ...

    def get_evaluation_artifact_zip(
        self, training_id: str, artifact_name: str
    ) -> bytes: ...

    def get_evaluation_artifact_bounds(
        self, training_id: str, artifact_name: str
    ) -> tuple[float, float] | None: ...

    def can_save_evaluation_workspace(
        self, training_id: str, archive_key: str
    ) -> bool: ...

    def build_model_simulation_archive(
        self,
        training_id: str,
        archive_key: str,
        external_control_signals_archive: bytes | None = None,
    ) -> bytes: ...

    def remove_training_workspace(self, training_id: str) -> None: ...


class SystemDiscoverySimulationRegistryPort(Protocol):
    def register_simulation(self, record: SystemDiscoverySimulationRecord) -> None: ...

    def get_simulation(
        self, simulation_id: str
    ) -> SystemDiscoverySimulationRecord | None: ...

    def list_simulations(self) -> list[SystemDiscoverySimulationRecord]: ...

    def update_simulation_status(
        self,
        simulation_id: str,
        *,
        state: Any,
        raw_status: str,
        error: str | None,
        updated_at: Any,
    ) -> SystemDiscoverySimulationRecord: ...

    def update_simulation_aistor_result(
        self,
        simulation_id: str,
        *,
        aistor_object_key: str | None,
        aistor_uploaded_at: Any | None,
        aistor_upload_error: str | None,
    ) -> SystemDiscoverySimulationRecord: ...

    def update_simulation_visualization(
        self,
        simulation_id: str,
        *,
        visualization_plot_id: str | None,
    ) -> SystemDiscoverySimulationRecord: ...


@runtime_checkable
class SystemDiscoveryAIStorPort(Protocol):
    def upload_results_archive(
        self,
        simulation_id: str,
        content: bytes,
    ) -> SystemDiscoveryStoredResultsArchive: ...

    def download_results_archive(self, simulation_id: str) -> bytes: ...


class SystemDiscoverySimulationResultsPreparerPort(Protocol):
    def prepare_results_csv_zip(self, results_archive: bytes) -> bytes: ...


class SystemDiscoverySimulationResultsArchivePostprocessorPort(Protocol):
    def postprocess(
        self,
        archive: SystemDiscoverySimulationResultsArchive,
    ) -> SystemDiscoverySimulationResultsArchivePostprocessingResult: ...


class AnalyticsPort(Protocol):
    def initialize_job(
        self,
        job_id: str,
        job_root_url: str,
        results_urls: list[ResultRef],
        input_parameters: list[tuple[str, str]],
        output_parameters: list[tuple[str, str]],
    ) -> None: ...

    def job_results_status(self, job_id: str) -> str: ...

    def job_results_error(self, job_id: str) -> str | None: ...

    def retry_job_results(
        self,
        job_id: str,
        job_root_url: str,
        results_urls: list[ResultRef],
        input_parameters: list[tuple[str, str]],
        output_parameters: list[tuple[str, str]],
    ) -> None: ...

    def input_parameters_values(self, job_id: str) -> list[ParameterValues] | None: ...

    def job_repetitions(self, job_id: str) -> list[int] | None: ...

    def prepare_series(
        self,
        job_id: str,
        x_param: str,
        y_param: str,
        constants: list[tuple[str, str]],
        statistic: str,
    ) -> str: ...

    def get_series_status(self, series_id: str) -> str: ...

    def download_series(self, series_id: str) -> bytes: ...

    def supported_statistics(self) -> list[str]: ...

    def merge_series(self, seriesIds: list[str]) -> str: ...

    def analyze_sensitivity(
        self,
        csv_data: str | None = None,
        problem: dict[str, object] | None = None,
        n_real: int | None = None,
        output_names: list[str] | None = None,
        results_urls: list[str] | None = None,
        aggregation: str | None = None,
    ) -> SensitivityAnalysisResult: ...

    def analyze_monte_carlo_filtering(
        self,
        csv_data: str | None = None,
        problem: dict[str, object] | None = None,
        output_column: str | None = None,
        threshold: float | None = None,
        direction: str | None = None,
        results_urls: list[str] | None = None,
        aggregation: str | None = None,
        alpha: float = 0.05,
        output_aggregations: dict[str, str] | None = None,
        run_output_columns: list[str] | None = None,
    ) -> MonteCarloFilteringResult: ...


class ParserPort(Protocol):
    def recognize_stages(self, time_series_csv_bytes: bytes) -> str: ...

    def get_recognition_status(self, recognition_id: str) -> str: ...

    def get_disaster_stage_recognition(
        self, recognition_id: str
    ) -> DisasterStageRecognitionResult: ...

    def get_disaster_stages(
        self, recognition_id: str
    ) -> list[tuple[str, float, float]]: ...

    def recognition_finished_successfully(self, recognition_id: str) -> bool: ...


class VisualizationPort(Protocol):
    def supported_plot_types(self) -> list[str]: ...

    def render_plot(self, zip_csv_bytes: bytes, plot_spec: PlotSpec) -> str: ...

    def get_plot_html(self, plot_id: str) -> str | None: ...

    def get_plot_status(self, plot_id: str) -> str: ...


class MatrixGenerationPort(Protocol):
    def generate_linear_combinations(
        self,
        matrix_id: str,
        repetitions: int,
        parameter_definitions: list[MatrixParameterDefinition],
        fixed_params: dict[str, str],
        sweep_params: dict[str, list[str]],
    ) -> GeneratedMatrixFile:
        """Generate a matrix file from linear-combination parameters."""

    def generate_sensitivity_analysis(
        self,
        matrix_id: str,
        parameters: list[SensitivityAnalysisParameter],
        sample_size: int,
        calc_second_order: bool,
        round_to_int: bool,
    ) -> GeneratedMatrixFile:
        """Generate a matrix file from sensitivity-analysis parameters."""

    def generate_satelli_matrix_combinations(
        self,
        matrix_id: str,
        repetitions: int,
        parameter_definitions: list[MatrixParameterDefinition],
        fixed_params: dict[str, str],
        sweep_params: dict[str, list[str]],
        sample_size: int = 128,
        seed: int | None = None,
    ) -> GeneratedMatrixFile:
        """Generate a Sobol/Satelli matrix for sensitivity analysis."""

    def upload_matrix(
        self,
        matrix_id: str,
        matrix_text: str,
    ) -> GeneratedMatrixFile:
        """Upload a raw matrix text and return the stored matrix URL."""


@runtime_checkable
class EvaluatorPort(Protocol):
    def evaluate(
        self,
        simulator_id: str,
        number_of_repetitions=128,
        *,
        kmax: int = 30,
        epsilon: float = 1e-3,
        batch_size: int = 1,
        lhs_candidates: int = 1500,
        random_state: int = 42,
        problem: dict | None = None,
        aggregation: str | None = None,
    ) -> str: ...

    def get_evaluation_status(self, evaluation_id: str) -> str: ...

    def get_evaluation_progress(self, evaluation_id: str) -> EvaluationProgress: ...

    def get_evaluation_results(self, evaluation_id: str) -> EvaluationResult: ...

    def list_evaluations(self) -> list[EvaluationSummary]: ...


@runtime_checkable
class SystemDiscoveryPort(Protocol):
    def submit_training(
        self,
        request: SystemDiscoveryTrainingRequest,
    ) -> SystemDiscoveryTrainingSubmission: ...

    def get_training_status(
        self,
        training_id: str,
    ) -> SystemDiscoveryTrainingStatus: ...

    def download_training_results(
        self,
        training_id: str,
    ) -> SystemDiscoveryTrainingResultsArchive: ...

    def submit_system_discovery_simulation(
        self,
        request: SystemDiscoverySimulationRequest,
    ) -> SystemDiscoverySimulationSubmission: ...

    def get_system_discovery_simulation_status(
        self,
        simulation_id: str,
    ) -> SystemDiscoverySimulationStatus: ...

    def download_system_discovery_simulation_results(
        self,
        simulation_id: str,
    ) -> SystemDiscoverySimulationResultsArchive: ...
