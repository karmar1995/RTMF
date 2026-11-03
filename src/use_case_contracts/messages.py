from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from use_case_contracts.dtos import ParameterSpec, VisualizationSeries


@dataclass(frozen=True)
class HealthCheck:
    pass


@dataclass(frozen=True)
class Echo:
    payload: Dict[str, Any]


@dataclass(frozen=True)
class BeginBrowserLogin:
    callback_url: str
    force_reauthentication: bool = False


@dataclass(frozen=True)
class CompleteBrowserLogin:
    authorization_code: str
    state: str


@dataclass(frozen=True)
class RequireAuthenticatedSession:
    pass


@dataclass(frozen=True)
class GetCurrentSessionContext:
    pass


@dataclass(frozen=True)
class Logout:
    pass


@dataclass(frozen=True)
class PlatformSpec:
    os: str
    arch: str


@dataclass(frozen=True)
class PackageSpec:
    name: str
    version: Optional[str] = None


@dataclass(frozen=True)
class PythonSpec:
    version: Optional[str] = None
    packages: Optional[List[PackageSpec]] = None


@dataclass(frozen=True)
class JavaSpec:
    distribution: Optional[str] = None
    version: Optional[str] = None
    app_type: Optional[str] = None


@dataclass(frozen=True)
class DotnetSpec:
    version: Optional[str] = None
    flavor: Optional[str] = None


@dataclass(frozen=True)
class TechnologySpec:
    type: str
    python: Optional[PythonSpec] = None
    java: Optional[JavaSpec] = None
    dotnet: Optional[DotnetSpec] = None


@dataclass(frozen=True)
class ModelFileSpec:
    filename: str
    content_type: str | None
    bytes: bytes


@dataclass(frozen=True)
class RegisterSimulator:
    name: str
    platform: PlatformSpec
    technology: TechnologySpec
    input_params: List[ParameterSpec]
    output_params: List[ParameterSpec]
    model_file: ModelFileSpec | None = None


@dataclass(frozen=True)
class OpenRegisterSimulatorForm:
    pass


@dataclass(frozen=True)
class OpenSimulationRunForm:
    pass


@dataclass(frozen=True)
class OpenEvaluationRunForm:
    pass


@dataclass(frozen=True)
class ListRecentRegistrations:
    query: str | None = None
    status: str | None = None
    page: int = 1
    per_page: int = 20


@dataclass(frozen=True)
class GetRegistrationDetails:
    registration_id: str


@dataclass(frozen=True)
class ListSimulators:
    query: str | None = None
    page: int = 1
    per_page: int = 20


@dataclass(frozen=True)
class GetSimulatorDetails:
    simulator_id: str


@dataclass(frozen=True)
class ScheduleSimulationRun:
    simulator_id: str
    repetitions: int
    fixed_params: dict[str, str]
    sweep_params: dict[str, list[str]]


@dataclass(frozen=True)
class GetJob:
    job_id: str


@dataclass(frozen=True)
class ListJobs:
    pass

@dataclass(frozen=True)
class ListMonitorEntries:
    """Monitor listing: simulation groups plus one entry per evaluation.

    An evaluator submits many Slurm jobs (one per SSBO point), so the monitor
    hides those individual jobs and shows the evaluation as a single parent.
    """

    pass


@dataclass(frozen=True)
class ListVisualizationJobs:
    page: int = 1
    per_page: int = 20


@dataclass(frozen=True)
class GetJobSubJobs:
    job_id: str


@dataclass(frozen=True)
class GetSubJobDetails:
    job_id: str
    sub_job_id: str


@dataclass(frozen=True)
class BeginJobVisualization:
    job_id: str


@dataclass(frozen=True)
class RetryJobResults:
    job_id: str

@dataclass(frozen=True)
class GetVisualizationConstantParams:
    job_id: str
    selected_x: str

@dataclass(frozen=True)
class GetJobRepetitions:
    job_id: str


@dataclass(frozen=True)
class GetJobVisualizationStatus:
    job_id: str


@dataclass(frozen=True)
class VisualizeJob:
    job_id: str
    series: list[VisualizationSeries]
    plot_type: str

@dataclass(frozen=True)
class VisualizeDisasterStages:
    job_id: str
    series: VisualizationSeries
    plot_type: str


@dataclass(frozen=True)
class VisualizeMonteCarloFiltering:
    job_id: str
    output_column: str
    threshold: float
    direction: str
    aggregation: str | None = None
    scatter_x: str | None = None
    scatter_y: str | None = None
    scatter_aggregation: str | None = None


@dataclass(frozen=True)
class GetMonteCarloFilteringPlotState:
    job_id: str
    plot_id: str
    scatter_plot_id: str | None = None


@dataclass(frozen=True)
class TrainSystemDiscovery:
    training_data_archive: bytes
    nlags_x: tuple[tuple[int, ...], ...] | None
    nlags_y: int
    basis: str
    degree: int
    model: str


@dataclass(frozen=True)
class OpenSystemDiscoveryTrainingForm:
    pass


@dataclass(frozen=True)
class GetSystemDiscoveryTrainingStatus:
    training_id: str


@dataclass(frozen=True)
class ListSystemDiscoveryTrainings:
    page: int = 1
    per_page: int = 20


@dataclass(frozen=True)
class OpenSystemDiscoveryTrainingEvaluation:
    training_id: str


@dataclass(frozen=True)
class SaveSystemDiscoveryModel:
    training_id: str


@dataclass(frozen=True)
class RemoveSystemDiscoveryTrainingQueueEntry:
    training_id: str


@dataclass(frozen=True)
class ListSavedSystemDiscoveryModels:
    page: int = 1
    per_page: int = 20


@dataclass(frozen=True)
class GetSavedSystemDiscoveryModelDetails:
    model_id: str


@dataclass(frozen=True)
class RemoveSavedSystemDiscoveryModel:
    model_id: str


@dataclass(frozen=True)
class CleanupExpiredSystemDiscoveryTrainingQueueEntries:
    terminal_retention_days: int


@dataclass(frozen=True)
class ListSystemDiscoverySimulations:
    page: int = 1
    per_page: int = 20


@dataclass(frozen=True)
class GetSystemDiscoverySimulationDetails:
    simulation_id: str


@dataclass(frozen=True)
class RunEvaluation:
    simulator_id: str
    kmax: int = 30
    epsilon: float = 1e-3
    batch_size: int = 1
    lhs_candidates: int = 1500
    random_state: int = 42
    number_of_repetitions: int = 128
    problem: dict[str, Any] | None = None
    aggregation: str | None = None


@dataclass(frozen=True)
class ListEvaluations:
    page: int = 1
    per_page: int = 20


@dataclass(frozen=True)
class GetEvaluationDetails:
    evaluation_id: str
