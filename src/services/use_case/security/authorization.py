from __future__ import annotations

from typing import Any

from services.use_case.security.types import Principal
from use_case_contracts.errors import AuthorizationDeniedError
from use_case_contracts.messages import (
    BeginBrowserLogin,
    BeginJobVisualization,
    CleanupExpiredSystemDiscoveryTrainingQueueEntries,
    CompleteBrowserLogin,
    Echo,
    RetryJobResults,
    GetCurrentSessionContext,
    GetEvaluationDetails,
    GetJob,
    GetJobRepetitions,
    GetJobVisualizationStatus,
    GetJobSubJobs,
    GetMonteCarloFilteringPlotState,
    GetRegistrationDetails,
    GetSavedSystemDiscoveryModelDetails,
    GetSimulatorDetails,
    GetSubJobDetails,
    GetSystemDiscoverySimulationDetails,
    GetSystemDiscoveryTrainingStatus,
    GetVisualizationConstantParams,
    HealthCheck,
    ListEvaluations,
    ListJobs,
    ListMonitorEntries,
    ListRecentRegistrations,
    ListSavedSystemDiscoveryModels,
    ListSimulators,
    ListSystemDiscoverySimulations,
    ListSystemDiscoveryTrainings,
    ListVisualizationJobs,
    Logout,
    OpenRegisterSimulatorForm,
    OpenSimulationRunForm,
    OpenEvaluationRunForm,
    OpenSystemDiscoveryTrainingForm,
    OpenSystemDiscoveryTrainingEvaluation,
    RegisterSimulator,
    RequireAuthenticatedSession,
    RemoveSavedSystemDiscoveryModel,
    RemoveSystemDiscoveryTrainingQueueEntry,
    RunEvaluation,
    SaveSystemDiscoveryModel,
    ScheduleSimulationRun,
    TrainSystemDiscovery,
    VisualizeDisasterStages,
    VisualizeJob,
    VisualizeMonteCarloFiltering,
)
from use_case_contracts.permissions import (
    JOB_CREATE,
    JOB_READ,
    SIMULATION_READ,
    SIMULATOR_READ,
    SIMULATOR_WRITE,
    SYSTEM_DISCOVERY_MODEL_READ,
    SYSTEM_DISCOVERY_MODEL_WRITE,
    SYSTEM_DISCOVERY_SIMULATION_READ,
    SYSTEM_DISCOVERY_TRAINING_READ,
    SYSTEM_DISCOVERY_TRAINING_WRITE,
    SYSTEM_READ,
)


PUBLIC_MESSAGE_TYPES = (BeginBrowserLogin, CompleteBrowserLogin)
AUTHENTICATED_ONLY = "__authenticated__"


class MessagePermissionAuthorizer:
    def __init__(self, permissions_by_message_type: dict[type[Any], str] | None = None) -> None:
        self._permissions_by_message_type = permissions_by_message_type or _default_permissions()

    def is_public(self, message: Any) -> bool:
        return isinstance(message, PUBLIC_MESSAGE_TYPES)

    def assert_allowed(self, principal: Principal, message: Any) -> None:
        required = self._permissions_by_message_type.get(type(message))
        if required is None:
            raise AuthorizationDeniedError("Not authorized.")
        if required == AUTHENTICATED_ONLY:
            return
        if required not in principal.permissions:
            raise AuthorizationDeniedError("Not authorized.")


def _default_permissions() -> dict[type[Any], str]:
    return {
        HealthCheck: SYSTEM_READ,
        Echo: SYSTEM_READ,
        RequireAuthenticatedSession: AUTHENTICATED_ONLY,
        GetCurrentSessionContext: AUTHENTICATED_ONLY,
        Logout: AUTHENTICATED_ONLY,
        OpenRegisterSimulatorForm: SIMULATOR_WRITE,
        RegisterSimulator: SIMULATOR_WRITE,
        ListRecentRegistrations: SIMULATOR_READ,
        GetRegistrationDetails: SIMULATOR_READ,
        ListSimulators: SIMULATOR_READ,
        GetSimulatorDetails: SIMULATOR_READ,
        OpenSimulationRunForm: JOB_CREATE,
        ScheduleSimulationRun: JOB_CREATE,
        OpenEvaluationRunForm: JOB_CREATE,
        RunEvaluation: JOB_CREATE,
        ListEvaluations: JOB_READ,
        GetEvaluationDetails: JOB_READ,
        GetJob: JOB_READ,
        ListJobs: JOB_READ,
        ListMonitorEntries: JOB_READ,
        ListVisualizationJobs: JOB_READ,
        GetJobSubJobs: JOB_READ,
        GetSubJobDetails: JOB_READ,
        BeginJobVisualization: SIMULATION_READ,
        RetryJobResults: SIMULATION_READ,
        GetVisualizationConstantParams: SIMULATION_READ,
        GetJobRepetitions: SIMULATION_READ,
        GetJobVisualizationStatus: SIMULATION_READ,
        VisualizeJob: SIMULATION_READ,
        VisualizeDisasterStages: SIMULATION_READ,
        VisualizeMonteCarloFiltering: SIMULATION_READ,
        GetMonteCarloFilteringPlotState: SIMULATION_READ,
        OpenSystemDiscoveryTrainingForm: SYSTEM_DISCOVERY_TRAINING_WRITE,
        TrainSystemDiscovery: SYSTEM_DISCOVERY_TRAINING_WRITE,
        GetSystemDiscoveryTrainingStatus: SYSTEM_DISCOVERY_TRAINING_READ,
        ListSystemDiscoveryTrainings: SYSTEM_DISCOVERY_TRAINING_READ,
        OpenSystemDiscoveryTrainingEvaluation: SYSTEM_DISCOVERY_TRAINING_READ,
        SaveSystemDiscoveryModel: SYSTEM_DISCOVERY_MODEL_WRITE,
        RemoveSystemDiscoveryTrainingQueueEntry: SYSTEM_DISCOVERY_TRAINING_WRITE,
        ListSavedSystemDiscoveryModels: SYSTEM_DISCOVERY_MODEL_READ,
        GetSavedSystemDiscoveryModelDetails: SYSTEM_DISCOVERY_MODEL_READ,
        RemoveSavedSystemDiscoveryModel: SYSTEM_DISCOVERY_MODEL_WRITE,
        CleanupExpiredSystemDiscoveryTrainingQueueEntries: SYSTEM_DISCOVERY_TRAINING_WRITE,
        ListSystemDiscoverySimulations: SYSTEM_DISCOVERY_SIMULATION_READ,
        GetSystemDiscoverySimulationDetails: SYSTEM_DISCOVERY_SIMULATION_READ,
    }
