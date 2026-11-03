from __future__ import annotations

from datetime import datetime, timezone

from services.use_case.handlers.evaluations import handle_list_evaluations
from services.use_case.handlers.registrations import handle_list_recent_registrations
from services.use_case.handlers.simulators_browse import handle_list_simulators
from services.use_case.handlers.system_discovery_training import (
    handle_list_saved_system_discovery_models,
)
from services.use_case.utils.pagination import paginate
from use_case_contracts.dtos import (
    EvaluationSummary,
    ListEvaluationsResult,
    ListRecentRegistrationsResult,
    ListSavedSystemDiscoveryModelsResult,
    ListSimulatorsResult,
    RegistrationSummary,
    SimulatorSummary,
    SystemDiscoverySavedModelRecord,
)
from use_case_contracts.messages import (
    ListEvaluations,
    ListRecentRegistrations,
    ListSavedSystemDiscoveryModels,
    ListSimulators,
)


def test_paginate_slices_and_reports_total() -> None:
    items = list(range(25))
    page, total = paginate(items, 2, 10)
    assert list(page) == list(range(10, 20))
    assert total == 25


def test_paginate_clamps_negative_page_to_first() -> None:
    items = list(range(5))
    page, total = paginate(items, 0, 3)
    assert list(page) == [0, 1, 2]
    assert total == 5


def test_paginate_returns_empty_for_page_beyond_end() -> None:
    items = list(range(5))
    page, total = paginate(items, 99, 10)
    assert list(page) == []
    assert total == 5


def test_paginate_returns_everything_when_per_page_is_non_positive() -> None:
    items = list(range(5))
    page, total = paginate(items, 2, 0)
    assert list(page) == [0, 1, 2, 3, 4]
    assert total == 5


def test_recent_registrations_are_paginated() -> None:
    records = [
        RegistrationSummary(
            registration_id=f"r-{index}",
            model_name="model",
            status="Running",
            created_at="2026-01-01T00:00:00Z",
        )
        for index in range(25)
    ]
    result = handle_list_recent_registrations(
        ListRecentRegistrations(page=2, per_page=10),
        repo=_RegistrationsRepository(records),
    )

    assert isinstance(result, ListRecentRegistrationsResult)
    assert [item.registration_id for item in result.registrations] == [
        f"r-{index}" for index in range(10, 20)
    ]
    assert result.total == 25
    assert result.page == 2
    assert result.per_page == 10


def test_recent_registrations_respect_default_pagination() -> None:
    records = [
        RegistrationSummary(
            registration_id=f"r-{index}",
            model_name="model",
            status="Running",
            created_at="2026-01-01T00:00:00Z",
        )
        for index in range(30)
    ]
    result = handle_list_recent_registrations(
        ListRecentRegistrations(), repo=_RegistrationsRepository(records)
    )

    assert len(result.registrations) == 20
    assert result.total == 30


def test_simulators_are_paginated() -> None:
    records = [
        SimulatorSummary(
            simulator_id=f"sim-{index}",
            model_name="model",
            version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        for index in range(25)
    ]
    result = handle_list_simulators(
        ListSimulators(page=3, per_page=5), repo=_SimulatorsRepository(records)
    )

    assert isinstance(result, ListSimulatorsResult)
    assert [item.simulator_id for item in result.simulators] == [
        f"sim-{index}" for index in range(10, 15)
    ]
    assert result.total == 25
    assert result.page == 3
    assert result.per_page == 5


def test_evaluations_are_paginated() -> None:
    records = [
        EvaluationSummary(
            evaluation_id=f"eval-{index}",
            simulator_id="sim-1",
            status="success",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        for index in range(12)
    ]
    result = handle_list_evaluations(
        ListEvaluations(page=1, per_page=10), evaluator=_Evaluator(records)
    )

    assert isinstance(result, ListEvaluationsResult)
    assert len(result.evaluations) == 10
    assert result.total == 12


def test_evaluations_are_sorted_by_created_at_desc() -> None:
    records = [
        EvaluationSummary(
            evaluation_id="oldest",
            simulator_id="sim-1",
            status="success",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        EvaluationSummary(
            evaluation_id="newest",
            simulator_id="sim-1",
            status="queued",
            created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        ),
        EvaluationSummary(
            evaluation_id="no-timestamp",
            simulator_id="sim-1",
            status="queued",
            created_at=None,
        ),
        EvaluationSummary(
            evaluation_id="middle",
            simulator_id="sim-1",
            status="success",
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ),
    ]
    result = handle_list_evaluations(
        ListEvaluations(), evaluator=_Evaluator(records)
    )

    assert [item.evaluation_id for item in result.evaluations] == [
        "newest",
        "middle",
        "oldest",
        "no-timestamp",
    ]
    assert result.total == 4


def test_saved_models_are_paginated() -> None:
    records = [
        SystemDiscoverySavedModelRecord(
            model_id=f"model-{index}",
            source_training_id="train-1",
            model_name="narmax",
            saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            nlags_x=((1,),),
            nlags_y=1,
            basis="Polynomial",
            degree=3,
        )
        for index in range(25)
    ]
    result = handle_list_saved_system_discovery_models(
        ListSavedSystemDiscoveryModels(page=2, per_page=10),
        saved_models=_SavedModelsRegistry(records),
    )

    assert isinstance(result, ListSavedSystemDiscoveryModelsResult)
    assert [item.model_id for item in result.models] == [
        f"model-{index}" for index in range(10, 20)
    ]
    assert result.total == 25
    assert result.page == 2
    assert result.per_page == 10


class _RegistrationsRepository:
    def __init__(self, records) -> None:
        self._records = records

    def list_recent_registrations(self, limit: int = 100):
        return self._records


class _SimulatorsRepository:
    def __init__(self, records) -> None:
        self._records = records

    def list_simulators(self):
        return self._records


class _Evaluator:
    def __init__(self, records) -> None:
        self._records = records

    def list_evaluations(self):
        return self._records


class _SavedModelsRegistry:
    def __init__(self, records) -> None:
        self._records = records

    def list_models(self):
        return self._records
