from __future__ import annotations

from datetime import datetime, timezone

from services.front.main import app
from use_case_contracts.dtos import (
    EvaluationSummary,
    ListEvaluationsResult,
    MonitorEntries,
    ListRecentRegistrationsResult,
    ListSavedSystemDiscoveryModelsResult,
    ListSimulatorsResult,
    ListSystemDiscoverySimulationsResult,
    ListSystemDiscoveryTrainingsResult,
    RegistrationSummary,
    SimulatorSummary,
    SubJobInfo,
    SystemDiscoverySavedModelRecord,
    SystemDiscoverySimulationRecord,
    SystemDiscoverySimulationState,
    SystemDiscoveryTrainingRecord,
    SystemDiscoveryTrainingState,
)
from use_case_contracts.messages import (
    GetJobSubJobs,
    ListEvaluations,
    ListMonitorEntries,
    ListRecentRegistrations,
    ListSavedSystemDiscoveryModels,
    ListSimulators,
    ListSystemDiscoverySimulations,
    ListSystemDiscoveryTrainings,
)
from conftest import _installed

_REGISTRATION_TOTAL = 25
_SIMULATOR_TOTAL = 25
_EVALUATION_TOTAL = 25
_TRAINING_TOTAL = 25
_MODEL_TOTAL = 25
_SIMULATION_TOTAL = 25


def test_recent_registrations_renders_pagination_and_preserves_filters() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulators/registration_status?page=2&q=traffic&status=running"
        )

    assert response.status_code == 200
    assert usecases.messages[-1] == ListRecentRegistrations(
        query="traffic", status="running", page=2, per_page=20
    )
    body = response.get_data(as_text=True)
    assert "Showing 21\u201325 of 25 registrations" in body
    assert "href=\"/simulators/registration_status?page=1&amp;per_page=20&amp;q=traffic&amp;status=running\"" in body
    assert "page=2" in body
    assert "q=traffic" in body


def test_recent_registrations_clamps_per_page() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        app.test_client().get("/simulators/registration_status?per_page=500")

    assert usecases.messages[-1] == ListRecentRegistrations(page=1, per_page=100)


def test_simulators_browse_renders_pagination_and_preserves_query() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get("/simulators/browse?q=warehouse")

    assert usecases.messages[-1] == ListSimulators(query="warehouse", page=1, per_page=20)
    body = response.get_data(as_text=True)
    assert "Showing 1\u201320 of 25 simulators" in body
    assert "q=warehouse" in body
    assert "Previous" in body
    assert "Next" in body


def test_evaluation_queue_renders_pagination() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get("/evaluations?page=2")

    assert usecases.messages[-1] == ListEvaluations(page=2, per_page=20)
    body = response.get_data(as_text=True)
    assert "Showing 21\u201325 of 25 evaluations" in body
    assert "page=2" in body


def test_training_queue_renders_pagination() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get("/system-discovery/trainings?page=2")

    assert usecases.messages[-1] == ListSystemDiscoveryTrainings(page=2, per_page=20)
    body = response.get_data(as_text=True)
    assert "Showing 21\u201325 of 25 trainings" in body
    assert "page=2" in body


def test_saved_models_renders_pagination() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get("/system-discovery/models?page=2")

    assert usecases.messages[-1] == ListSavedSystemDiscoveryModels(page=2, per_page=20)
    body = response.get_data(as_text=True)
    assert "Showing 21\u201325 of 25 models" in body
    assert "page=2" in body


def test_system_discovery_simulations_renders_pagination() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get("/system-discovery/simulations?page=2")

    assert usecases.messages[-1] == ListSystemDiscoverySimulations(page=2, per_page=20)
    body = response.get_data(as_text=True)
    assert "Showing 21\u201325 of 25 simulations" in body
    assert "page=2" in body


def test_monitor_shows_full_totals_and_slices_columns() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation_monitor?per_page=10&waiting_page=2"
        )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert ">11<" in body  # waiting total badge (11 waiting jobs)
    assert ">11<" in body  # running total badge
    assert ">11<" in body  # finished total badge
    assert "waiting_page=2" in body
    assert "waiting_page=1" in body
    assert "running_page=1" in body
    assert "finished_page=1" in body
    assert "Showing 11\u201311 of 11 jobs" in body
    assert "d-flex justify-content-between align-items-center flex-wrap gap-2 p-3" in body


def test_monitor_slices_columns_into_pages() -> None:
    usecases = _FakeUseCases()
    with _installed(usecases):
        response = app.test_client().get(
            "/simulation_monitor?per_page=10&finished_page=2"
        )

    body = response.get_data(as_text=True)
    assert "finished_page=2" in body
    assert "finished_page=1" in body
    assert "Showing 11\u201311 of 11 jobs" in body


class _FakeUseCases:
    def __init__(self) -> None:
        self.messages: list = []
        self._registrations = [
            RegistrationSummary(
                registration_id=f"reg-{index:02d}",
                model_name="model",
                status="Running",
                created_at="2026-01-01T00:00:00Z",
            )
            for index in range(_REGISTRATION_TOTAL)
        ]
        self._simulators = [
            SimulatorSummary(
                simulator_id=f"sim-{index:02d}",
                model_name="model",
                version="1.0",
                created_at="2026-01-01T00:00:00Z",
            )
            for index in range(_SIMULATOR_TOTAL)
        ]
        self._evaluations = [
            EvaluationSummary(
                evaluation_id=f"eval-{index:02d}",
                simulator_id="sim-1",
                status="success",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            for index in range(_EVALUATION_TOTAL)
        ]
        self._trainings = [
            _training(index)
            for index in range(_TRAINING_TOTAL)
        ]
        self._models = [
            _saved_model(index)
            for index in range(_MODEL_TOTAL)
        ]
        self._simulations = [
            _simulation(index)
            for index in range(_SIMULATION_TOTAL)
        ]

    def handle(self, message):
        self.messages.append(message)
        if isinstance(message, ListRecentRegistrations):
            return _result(
                ListRecentRegistrationsResult,
                message,
                self._registrations,
                "registrations",
            )
        if isinstance(message, ListSimulators):
            return _result(
                ListSimulatorsResult,
                message,
                self._simulators,
                "simulators",
            )
        if isinstance(message, ListEvaluations):
            return _result(
                ListEvaluationsResult,
                message,
                self._evaluations,
                "evaluations",
            )
        if isinstance(message, ListSystemDiscoveryTrainings):
            return _result(
                ListSystemDiscoveryTrainingsResult,
                message,
                self._trainings,
                "trainings",
                extra={"failures": []},
            )
        if isinstance(message, ListSavedSystemDiscoveryModels):
            return _result(
                ListSavedSystemDiscoveryModelsResult,
                message,
                self._models,
                "models",
            )
        if isinstance(message, ListSystemDiscoverySimulations):
            return _result(
                ListSystemDiscoverySimulationsResult,
                message,
                self._simulations,
                "simulations",
                extra={"failures": []},
            )
        if isinstance(message, ListMonitorEntries):
            return MonitorEntries(
                simulation_group_ids=[f"g-{index:02d}" for index in range(33)],
                evaluations=[],
            )
        if isinstance(message, GetJobSubJobs):
            index = int(message.job_id.split("-")[1])
            if index < 11:
                status = "waiting"
            elif index < 22:
                status = "running"
            else:
                status = "successful"
            return [
                SubJobInfo(
                    sub_job_id="sub-1",
                    job_id=message.job_id,
                    status=status,
                    params=[],
                    repetition=0,
                )
            ]
        raise AssertionError(f"Unexpected message: {message!r}")


def _result(result_type, message, items, field, extra=None):
    start = (message.page - 1) * message.per_page
    kwargs = {
        "page": message.page,
        "per_page": message.per_page,
        "total": len(items),
    }
    kwargs[field] = items[start : start + message.per_page]
    if extra:
        kwargs.update(extra)
    return result_type(**kwargs)


def _training(index: int) -> SystemDiscoveryTrainingRecord:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return SystemDiscoveryTrainingRecord(
        training_id=f"train-{index:02d}",
        created_at=created_at,
        updated_at=created_at,
        state=SystemDiscoveryTrainingState.COMPLETED,
        raw_status=SystemDiscoveryTrainingState.COMPLETED.value,
        training_status=None,
        evaluation_status=None,
        error=None,
        basis="Polynomial",
        degree=2,
        model="narmax",
        nlags_x=((1,),),
        nlags_y=1,
    )


def _saved_model(index: int) -> SystemDiscoverySavedModelRecord:
    return SystemDiscoverySavedModelRecord(
        model_id=f"model-{index:02d}",
        source_training_id="train-1",
        model_name="narmax",
        saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        nlags_x=((1,),),
        nlags_y=1,
        basis="Polynomial",
        degree=3,
    )


def _simulation(index: int) -> SystemDiscoverySimulationRecord:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return SystemDiscoverySimulationRecord(
        simulation_id=f"sim-{index:02d}",
        source_model_id="model-1",
        source_model_name="narmax",
        created_at=created_at,
        updated_at=created_at,
        state=SystemDiscoverySimulationState.COMPLETED,
        raw_status=SystemDiscoverySimulationState.COMPLETED.value,
        error=None,
        horizon=10,
        initial_conditions=None,
    )
