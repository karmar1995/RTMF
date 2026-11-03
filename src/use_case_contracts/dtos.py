from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List
from datetime import datetime


class ParamType(str, Enum):
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    STRING = "string"
    INT_TS = "int_ts"
    FLOAT_TS = "float_ts"
    BOOL_TS = "bool_ts"
    STRING_TS = "string_ts"


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    type: ParamType | str


@dataclass(frozen=True)
class BuildSpec:
    spec: Dict[str, Any]


@dataclass(frozen=True)
class HealthStatus:
    status: str


@dataclass(frozen=True)
class EchoResult:
    payload: Dict[str, Any]


@dataclass(frozen=True)
class BrowserLoginChallenge:
    authorization_url: str
    state: str


@dataclass(frozen=True)
class AuthenticatedIdentity:
    subject_id: str
    permissions: frozenset[str]
    authentication_provider: str
    provider_session_state: bytes = b""
    access_token_expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None


@dataclass(frozen=True)
class LoginCompleted:
    raw_session_credential: str
    expires_at: datetime


@dataclass(frozen=True)
class LogoutCompleted:
    pass


@dataclass(frozen=True)
class CurrentSessionContext:
    subject_id: str
    permissions: frozenset[str]


@dataclass(frozen=True)
class RegistrationSummary:
    registration_id: str
    model_name: str
    status: str
    created_at: str


@dataclass(frozen=True)
class RegistrationDetails:
    registration_id: str
    model_name: str
    status: str
    created_at: str
    version: str | None = None
    build_id: str | None = None


@dataclass(frozen=True)
class SimulatorSummary:
    simulator_id: str
    model_name: str
    version: str
    created_at: str


@dataclass(frozen=True)
class SimulatorDetails:
    model_name: str
    version: str
    created_at: str
    bin_url: str
    build_spec: BuildSpec | None = None
    input_params: List[ParameterSpec] | None = None
    output_params: List[ParameterSpec] | None = None


@dataclass(frozen=True)
class SimulatorRegistrationResult:
    model_name: str
    version: str
    build_id: str
    status: str


@dataclass(frozen=True)
class JobInfo:
    job_id: str
    status: str
    created_at: str | None


@dataclass(frozen=True)
class ScheduledBatchInfo:
    job_id: str
    sub_job_ids: list[str]
    repetitions: int
    matrix_rows: int


@dataclass(frozen=True)
class JobSummary:
    job_id: str


@dataclass(frozen=True)
class EvaluationMonitorEntry:
    """One evaluation shown as a single parent entry on the monitor."""

    evaluation_id: str
    model_name: str
    state: str  # waiting | running | finished
    status: str  # queued | optimizing | success | failed ...
    success: bool | None
    progress: int | None  # percentage, only while running
    created_at: float | None


@dataclass(frozen=True)
class MonitorEntries:
    """Simulation job groups (children of evaluations already removed) plus
    one synthetic entry per evaluation."""

    simulation_group_ids: list[str]
    evaluations: list[EvaluationMonitorEntry]


@dataclass(frozen=True)
class SubJobInfo:
    sub_job_id: str
    job_id: str
    status: str
    params: list[str]
    repetition: int


@dataclass(frozen=True)
class SubJobDetailsDto:
    job_id: str
    sub_job_id: str
    status: str
    standard_output: str
    standard_error: str


@dataclass(frozen=True)
class UploadResult:
    etag: str | None = None
    version_id: str | None = None


@dataclass(frozen=True)
class JobResultRef:
    job_id: str
    simulator_id: str
    created_at: str
    job_root_url: str


@dataclass(frozen=True)
class VisualizationTarget:
    """What a visualization needs to load, for either kind of id.

    An evaluation is presented as one big job, so its id resolves to the
    simulator it used plus the union of every result artifact its jobs
    produced. The analytics service merges that flat list into one dataset.
    """

    id: str
    simulator_id: str
    job_root_url: str
    result_urls: list[ResultRef]
    is_evaluation: bool = False


@dataclass(frozen=True)
class Job4Visualization:
    job_id: str
    model_name: str
    created_at: str
    # "job" for a plain simulation job, "evaluation" for an evaluation
    # presented as one big job.
    kind: str = "job"


@dataclass(frozen=True)
class JobVisualizationPage:
    jobs: list[Job4Visualization]
    page: int
    per_page: int
    total: int


@dataclass(frozen=True)
class ListRecentRegistrationsResult:
    registrations: list[RegistrationSummary]
    page: int
    per_page: int
    total: int


@dataclass(frozen=True)
class ListSimulatorsResult:
    simulators: list[SimulatorSummary]
    page: int
    per_page: int
    total: int


@dataclass(frozen=True)
class ResultRef:
    sub_job_id: str
    url: str


@dataclass(frozen=True)
class ParameterValues:
    name: str
    value: list[int | float | str | bool] | None = None


@dataclass(frozen=True)
class VisualizationSeries:
    x: str
    y: str
    statistic: str
    constants: dict


@dataclass(frozen=True)
class DisasterStageMetrics:
    recovery_time_in_steps: float | None = None
    shock_time_in_steps: float | None = None
    shock_drop_pct_ref_normal: float | None = None
    shock_drop_pct_ref_baseline: float | None = None
    shock_stage_avg: float | None = None
    shock_stage_std: float | None = None


@dataclass(frozen=True)
class DisasterStageRecognitionResult:
    stages: list[tuple[str, float, float]]
    metrics: DisasterStageMetrics | None = None


@dataclass(frozen=True)
class PlotLine:
    point: float
    color: str
    label: str


@dataclass(frozen=True)
class PlotArea:
    begin: float
    end: float
    color: str


@dataclass(frozen=True)
class PlotAnnotation:
    point: float
    text: str
    color: str


@dataclass(frozen=True)
class PlotDiagonalLine:
    p_start: tuple[float, float]
    p_end: tuple[float, float]
    color: str
    dash: str


@dataclass(frozen=True)
class PlotSpec:
    plot_type: str
    vertical_lines: list[PlotLine]
    areas: list[PlotArea]
    annotations: list[PlotAnnotation]
    diagonal_lines: list[PlotDiagonalLine]
    xaxis_title: str | None = None
    yaxis_title: str | None = None
    title: str | None = None
    series_hover_templates: dict[str, str] | None = None
    series_styles: dict[str, dict] | None = None



    fixed_params: dict[str, str] | None = None
    plot_error: str | None = None
    scalar_stat: str | None = None
    ts_mode: str | None = None
    x_values: list[str] | None = None


@dataclass
class JobVisualizationConstants:
    constants: list[tuple[str, list[int | float | str | bool]]] | None = None


@dataclass
class JobVisualizationHeader:
    warning: str | None = None
    input_params: list[tuple[str, str]] | None = None
    output_params: list[tuple[str, str]] | None = None
    constants: JobVisualizationConstants | None = None
    plot_types: list[str] | None = None
    results_status: str | None = None
    results_error: str | None = None


@dataclass(frozen=True)
class JobVisualizationStatus:
    results_status: str
    results_error: str | None = None


@dataclass(frozen=True)
class JobVisualizationRenderedSeries:
    x: str | None = None
    y: str | None = None
    statistic: str | None = None
    constant_params: dict | None = None


@dataclass(frozen=True, init=False)
class JobVisualizationResult:
    series: list[JobVisualizationRenderedSeries]
    plot_type: str
    plot_html: str | None
    waiting_message: str
    disaster_stage_metrics: DisasterStageMetrics | None
    monte_carlo_statistics: list[MonteCarloFilteringStatistic] | None = None
    plot_id: str | None = None
    plot_status: str | None = None

    def __init__(
        self,
        *,
        series: list[JobVisualizationRenderedSeries] | None = None,
        plot_type: str,
        plot_html: str | None,
        waiting_message: str,
        disaster_stage_metrics: DisasterStageMetrics | None = None,
        monte_carlo_statistics: list[MonteCarloFilteringStatistic] | None = None,
        plot_id: str | None = None,
        plot_status: str | None = None,
        x: str | None = None,
        y: str | None = None,
        statistic: str | None = None,
        constant_params: dict | None = None,
    ) -> None:
        normalized_series = list(series or [])
        if not normalized_series and any(
            value is not None for value in (x, y, statistic, constant_params)
        ):
            normalized_series = [
                JobVisualizationRenderedSeries(
                    x=x,
                    y=y,
                    statistic=statistic,
                    constant_params=constant_params,
                )
            ]

        object.__setattr__(self, "series", normalized_series)
        object.__setattr__(self, "plot_type", plot_type)
        object.__setattr__(self, "plot_html", plot_html)
        object.__setattr__(self, "waiting_message", waiting_message)
        object.__setattr__(self, "disaster_stage_metrics", disaster_stage_metrics)
        object.__setattr__(self, "monte_carlo_statistics", monte_carlo_statistics)
        object.__setattr__(self, "plot_id", plot_id)
        object.__setattr__(self, "plot_status", plot_status)


@dataclass(frozen=True, init=False)
class MonteCarloFilteringPlotResult(JobVisualizationResult):
    behavioural_count: int | None = None
    non_behavioural_count: int | None = None
    scatter_plot_id: str | None = None
    scatter_plot_status: str | None = None
    scatter_plot_html: str | None = None
    scatter_x: str | None = None
    scatter_y: str | None = None
    scatter_input_options: list[tuple[str, str]] | None = None
    scatter_output_options: list[tuple[str, str]] | None = None
    simulator_id: str | None = None
    evaluation_output: str | None = None
    evaluation_aggregation: str | None = None
    behavioural_input_ranges: dict[str, list[float]] | None = None

    def __init__(
        self,
        *,
        series: list[JobVisualizationRenderedSeries] | None = None,
        plot_type: str,
        plot_html: str | None,
        waiting_message: str,
        disaster_stage_metrics: DisasterStageMetrics | None = None,
        monte_carlo_statistics: list[MonteCarloFilteringStatistic] | None = None,
        plot_id: str | None = None,
        plot_status: str | None = None,
        behavioural_count: int | None = None,
        non_behavioural_count: int | None = None,
        scatter_plot_id: str | None = None,
        scatter_plot_status: str | None = None,
        scatter_plot_html: str | None = None,
        scatter_x: str | None = None,
        scatter_y: str | None = None,
        scatter_input_options: list[tuple[str, str]] | None = None,
        scatter_output_options: list[tuple[str, str]] | None = None,
        simulator_id: str | None = None,
        evaluation_output: str | None = None,
        evaluation_aggregation: str | None = None,
        behavioural_input_ranges: dict[str, list[float]] | None = None,
        x: str | None = None,
        y: str | None = None,
        statistic: str | None = None,
        constant_params: dict | None = None,
    ) -> None:
        super().__init__(
            series=series,
            plot_type=plot_type,
            plot_html=plot_html,
            waiting_message=waiting_message,
            disaster_stage_metrics=disaster_stage_metrics,
            monte_carlo_statistics=monte_carlo_statistics,
            plot_id=plot_id,
            plot_status=plot_status,
            x=x,
            y=y,
            statistic=statistic,
            constant_params=constant_params,
        )
        object.__setattr__(self, "behavioural_count", behavioural_count)
        object.__setattr__(self, "non_behavioural_count", non_behavioural_count)
        object.__setattr__(self, "scatter_plot_id", scatter_plot_id)
        object.__setattr__(self, "scatter_plot_status", scatter_plot_status)
        object.__setattr__(self, "scatter_plot_html", scatter_plot_html)
        object.__setattr__(self, "scatter_x", scatter_x)
        object.__setattr__(self, "scatter_y", scatter_y)
        object.__setattr__(self, "scatter_input_options", scatter_input_options)
        object.__setattr__(self, "scatter_output_options", scatter_output_options)
        object.__setattr__(self, "simulator_id", simulator_id)
        object.__setattr__(self, "evaluation_output", evaluation_output)
        object.__setattr__(self, "evaluation_aggregation", evaluation_aggregation)
        object.__setattr__(self, "behavioural_input_ranges", behavioural_input_ranges)


@dataclass(frozen=True)
class MonteCarloFilteringPlotState:
    plot_status: str
    plot_html: str | None = None
    scatter_plot_status: str | None = None
    scatter_plot_html: str | None = None


class SystemDiscoveryTrainingEvaluationState(str, Enum):
    NOT_COMPLETED = "not_completed"
    POSTPROCESSING = "postprocessing"
    READY = "ready"
    FAILED = "failed"


class SystemDiscoveryTrainingEvaluationPlotState(str, Enum):
    READY = "ready"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SystemDiscoveryEvaluationMetric:
    value: str
    confidence_interval: str | None = None
    confidence_level: str | None = None
    confidence_method: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class SystemDiscoveryEvaluationCategory:
    label: str
    probability: str


@dataclass(frozen=True)
class SystemDiscoveryTrainingEvaluationMetadata:
    analysis: str | None
    sample_size: str
    nse: SystemDiscoveryEvaluationMetric
    rmse: SystemDiscoveryEvaluationMetric
    nrmse: SystemDiscoveryEvaluationMetric
    pbias: SystemDiscoveryEvaluationMetric
    p_value: str
    categories: list[SystemDiscoveryEvaluationCategory]


@dataclass(frozen=True)
class SystemDiscoveryTrainingEvaluationPlot:
    title: str
    state: SystemDiscoveryTrainingEvaluationPlotState
    plot_html: str | None
    waiting_message: str


@dataclass(frozen=True)
class OpenSystemDiscoveryTrainingEvaluationResult:
    training: "SystemDiscoveryTrainingRecord"
    state: SystemDiscoveryTrainingEvaluationState
    metadata: SystemDiscoveryTrainingEvaluationMetadata | None = None
    results_plot: SystemDiscoveryTrainingEvaluationPlot | None = None
    cdf_plot: SystemDiscoveryTrainingEvaluationPlot | None = None
    scatter_plot: SystemDiscoveryTrainingEvaluationPlot | None = None
    message: str | None = None
    can_save_model: bool = False


@dataclass(frozen=True)
class SaveSystemDiscoveryModelResult:
    model_id: str
    simulator_registration_id: str | None = None


@dataclass(frozen=True)
class SystemDiscoverySavedModelRecord:
    model_id: str
    source_training_id: str
    model_name: str
    saved_at: datetime
    nlags_x: list[list[int]]
    nlags_y: int
    basis: str
    degree: int


@dataclass(frozen=True)
class ListSavedSystemDiscoveryModelsResult:
    models: list[SystemDiscoverySavedModelRecord]
    page: int = 1
    per_page: int = 20
    total: int = 0


@dataclass(frozen=True)
class SensitivityAnalysisResult:
    mean_data_csv: str
    important_parameters: dict[str, list[str]]
    deterministic_indices_csv: str
    stochastic_indices_csv: str


@dataclass(frozen=True)
class MonteCarloFilteringStatistic:
    parameter: str
    d_statistic: float
    p_value: float
    reject_h0: bool
    behavioural_samples: int
    non_behavioural_samples: int
    behavioural_ecdf_x: list[float] = field(default_factory=list)
    behavioural_ecdf_y: list[float] = field(default_factory=list)
    non_behavioural_ecdf_x: list[float] = field(default_factory=list)
    non_behavioural_ecdf_y: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class MonteCarloFilteringRun:
    index: int
    behavioural: bool
    parameters: dict[str, float] = field(default_factory=dict)
    outputs: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MonteCarloFilteringResult:
    output_column: str
    threshold: float
    direction: str
    aggregation: str | None
    behavioural_count: int
    non_behavioural_count: int
    parameters: list[MonteCarloFilteringStatistic]
    runs: list[MonteCarloFilteringRun] = field(default_factory=list)


@dataclass(frozen=True)
class GetSavedSystemDiscoveryModelDetailsResult:
    model: SystemDiscoverySavedModelRecord


@dataclass(frozen=True, slots=True)
class MatrixParameterDefinition:
    name: str
    type: str


@dataclass(frozen=True, slots=True)
class SensitivityAnalysisParameter:
    name: str
    lower_bound: int | float
    upper_bound: int | float


@dataclass(frozen=True, slots=True)
class GeneratedMatrixFile:
    matrix_url: str


@dataclass(frozen=True)
class EvaluationResult:
    evaluation_id: str
    status: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class EvaluationSummary:
    evaluation_id: str
    simulator_id: str
    status: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class EvaluationProgress:
    evaluation_id: str
    status: str
    stage: str | None = None
    iteration: int = 0
    kmax: int = 0
    best_params: dict[str, Any] | None = None
    best_value: float | None = None
    important_parameters: list[str] | None = None
    ssbo_history: list[dict] = field(default_factory=list)
    jobs_submitted: int = 0
    jobs_by_stage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ListEvaluationsResult:
    evaluations: list[EvaluationSummary]
    page: int = 1
    per_page: int = 20
    total: int = 0


@dataclass(frozen=True)
class GetEvaluationDetailsResult:
    evaluation_id: str
    simulator_id: str
    status: str
    created_at: datetime | None = None
    result: EvaluationResult | None = None
    convergence_visualization: EvaluationVisualization | None = None
    exploration_visualization: EvaluationVisualization | None = None
    progress: EvaluationProgress | None = None


class EvaluationVisualizationState(str, Enum):
    NOT_READY = "not_ready"
    PENDING = "pending"
    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class EvaluationVisualization:
    state: EvaluationVisualizationState
    plot_html: str | None = None
    waiting_message: str = ""


@dataclass(frozen=True)
class SimulatorBuildRecord:
    model_name: str
    zip_filename: str
    zip_bytes: bytes
    build_spec: BuildSpec
    input_params: list[ParameterSpec]
    output_params: list[ParameterSpec]
    created_at: datetime | None = None


@dataclass(frozen=True)
class SystemDiscoveryParameters:
    nlags_x: tuple[tuple[int, ...], ...] | None
    nlags_y: int
    basis: str
    degree: int
    model: str


@dataclass(frozen=True)
class SystemDiscoveryTrainingRequest:
    training_data_archive: bytes
    system_parameters: SystemDiscoveryParameters


@dataclass(frozen=True)
class SystemDiscoveryTrainingSubmission:
    training_id: str
    status: str


@dataclass(frozen=True)
class SystemDiscoveryTrainingStatus:
    training_id: str
    status: str
    training_status: str
    evaluation_status: str
    error: str | None


@dataclass(frozen=True)
class SystemDiscoveryTrainingResultsArchive:
    content: bytes


class SystemDiscoveryTrainingState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class SystemDiscoveryTrainingRecord:
    training_id: str
    created_at: datetime
    updated_at: datetime | None
    state: SystemDiscoveryTrainingState
    raw_status: str
    training_status: str | None
    evaluation_status: str | None
    error: str | None
    basis: str
    degree: int
    model: str
    nlags_x: tuple[tuple[int, ...], ...] | None
    nlags_y: int
    results_archive_path: str | None = None
    results_cached_at: datetime | None = None
    results_cache_error: str | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class TrainSystemDiscoveryResult:
    training_id: str
    status: str


@dataclass(frozen=True)
class SystemDiscoveryTrainingRefreshFailure:
    training_id: str
    error: str


@dataclass(frozen=True)
class GetSystemDiscoveryTrainingStatusResult:
    training: SystemDiscoveryTrainingRecord
    failures: list[SystemDiscoveryTrainingRefreshFailure]


@dataclass(frozen=True)
class ListSystemDiscoveryTrainingsResult:
    trainings: list[SystemDiscoveryTrainingRecord]
    failures: list[SystemDiscoveryTrainingRefreshFailure]
    page: int = 1
    per_page: int = 20
    total: int = 0


@dataclass(frozen=True)
class RemoveSystemDiscoveryTrainingQueueEntryResult:
    training_id: str
    removed: bool


@dataclass(frozen=True)
class RemoveSavedSystemDiscoveryModelResult:
    model_id: str
    removed: bool


@dataclass(frozen=True)
class CleanupExpiredSystemDiscoveryTrainingQueueEntriesResult:
    examined_count: int
    removed_count: int
    skipped_count: int
    failed_count: int


@dataclass(frozen=True)
class SystemDiscoverySimulationRequest:
    model_and_input_archive: bytes
    horizon: int | None
    initial_conditions: tuple[float, ...] | None


@dataclass(frozen=True)
class SystemDiscoverySimulationSubmission:
    simulation_id: str
    status: str


@dataclass(frozen=True)
class SystemDiscoverySimulationStatus:
    simulation_id: str
    status: str
    error: str | None


@dataclass(frozen=True)
class SystemDiscoverySimulationResultsArchive:
    content: bytes


@dataclass(frozen=True)
class SystemDiscoverySimulationResultsArchivePostprocessingResult:
    archive: SystemDiscoverySimulationResultsArchive
    was_modified: bool


class SystemDiscoverySimulationState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SystemDiscoverySimulationVisualizationState(str, Enum):
    NOT_READY = "not_ready"
    PENDING = "pending"
    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SystemDiscoverySimulationVisualization:
    state: SystemDiscoverySimulationVisualizationState
    plot_html: str | None = None
    waiting_message: str = ""


@dataclass(frozen=True)
class SystemDiscoverySimulationRecord:
    simulation_id: str
    source_model_id: str
    source_model_name: str
    created_at: datetime
    updated_at: datetime | None
    state: SystemDiscoverySimulationState
    raw_status: str
    error: str | None
    horizon: int | None
    initial_conditions: tuple[float, ...] | None
    uses_external_control_signals: bool = False
    aistor_object_key: str | None = None
    aistor_uploaded_at: datetime | None = None
    aistor_upload_error: str | None = None
    visualization_plot_id: str | None = None





@dataclass(frozen=True)
class SystemDiscoverySimulationRefreshFailure:
    simulation_id: str
    error: str


@dataclass(frozen=True)
class ListSystemDiscoverySimulationsResult:
    simulations: list[SystemDiscoverySimulationRecord]
    failures: list[SystemDiscoverySimulationRefreshFailure]
    page: int = 1
    per_page: int = 20
    total: int = 0


@dataclass(frozen=True)
class GetSystemDiscoverySimulationDetailsResult:
    simulation: SystemDiscoverySimulationRecord
    visualization: SystemDiscoverySimulationVisualization
    failures: list[SystemDiscoverySimulationRefreshFailure]


@dataclass(frozen=True)
class SystemDiscoveryStoredResultsArchive:
    simulation_id: str
    storage_reference: str
