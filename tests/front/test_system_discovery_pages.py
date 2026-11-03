from __future__ import annotations

from pathlib import Path

from services.front.main import app
from datetime import datetime, timezone

from use_case_contracts.dtos import (
    GetSavedSystemDiscoveryModelDetailsResult,
    ListSavedSystemDiscoveryModelsResult,
    ListSystemDiscoverySimulationsResult,
    SystemDiscoverySavedModelRecord,
)
from use_case_contracts.errors import AuthorizationDeniedError
from use_case_contracts.messages import (
    GetSavedSystemDiscoveryModelDetails,
    ListSavedSystemDiscoveryModels,
    ListSystemDiscoverySimulations,
    OpenSystemDiscoveryTrainingForm,
    RequireAuthenticatedSession,
)


ROOT = Path(__file__).resolve().parents[2]


def test_system_discovery_page_routes_render_successfully() -> None:
    client = app.test_client()
    previous = app.extensions.get("usecases")
    app.extensions["usecases"] = _FakeUseCases()

    try:
        for route in (
            "/system_discovery_register",
            "/system_discovery_train",
            "/system-discovery/models",
            "/system-discovery/simulations",
        ):
            response = client.get(route)

            assert response.status_code == 200, route
    finally:
        if previous is None:
            app.extensions.pop("usecases", None)
        else:
            app.extensions["usecases"] = previous


def test_system_discovery_sidebar_entries_are_enabled_and_link_to_pages() -> None:
    response = app.test_client().get("/")
    body = response.get_data(as_text=True)

    assert 'href="/system_discovery_train"' in body
    assert 'href="/system-discovery/models"' in body
    assert 'href="/system-discovery/simulations"' in body
    assert "System Discovery Simulations" in body
    assert 'href="/system_discovery_visualization"' not in body
    assert "System Discovery</span>" in body
    assert 'aria-disabled="true"' not in body
    assert 'href="#"' not in body
    assert 'method="post"' in body
    assert 'action="/auth/logout"' in body
    assert ">Logout</button>" in body


def test_system_discovery_training_page_matches_current_contract() -> None:
    previous = app.extensions.get("usecases")
    app.extensions["usecases"] = _FakeUseCases()
    try:
        body = app.test_client().get("/system_discovery_train").get_data(as_text=True)
    finally:
        if previous is None:
            app.extensions.pop("usecases", None)
        else:
            app.extensions["usecases"] = previous

    assert "data_train.csv" in body
    assert "data_test.csv" in body
    assert 'name="nlags-x"' in body
    nlags_x_input = next(line for line in body.splitlines() if 'name="nlags-x"' in line)
    assert "required" not in nlags_x_input
    assert "Optional." in body
    assert 'name="nlags-y"' in body
    assert 'name="basis"' in body
    assert 'name="degree"' in body
    assert 'name="model"' in body
    assert 'accept=".zip"' in body
    assert 'type="submit"' in body
    assert "presentation-only" not in body


def test_system_discovery_training_form_is_denied_without_write_permission() -> None:
    previous = app.extensions.get("usecases")
    app.extensions["usecases"] = _DenyingUseCases()
    try:
        response = app.test_client().get("/system_discovery_train")
    finally:
        if previous is None:
            app.extensions.pop("usecases", None)
        else:
            app.extensions["usecases"] = previous

    assert response.status_code == 403


def test_system_discovery_simulation_page_matches_current_contract() -> None:
    assert "/system-discovery/models/<model_id>/simulate" not in {
        rule.rule for rule in app.url_map.iter_rules()
    }


def test_legacy_system_discovery_execution_endpoints_are_not_registered() -> None:
    rules = {(rule.rule, tuple(sorted(rule.methods))) for rule in app.url_map.iter_rules()}
    rule_paths = {rule for rule, _methods in rules}

    assert "/system_discovery_train/submit" not in rule_paths
    assert "/system_discovery_visualization" not in rule_paths
    assert "/system_discovery_visualize/<job_uuid>" not in rule_paths
    assert "/system_discovery_simulate/submit" not in rule_paths
    assert "/system_discovery_simulate" not in rule_paths
    assert "/api/discovery-models/<model_id>/params" not in rule_paths
    assert "/system_discovery_save_model/<job_uuid>" not in rule_paths
    assert "/system_discovery_delete" not in rule_paths
    assert all(
        "POST" not in methods
        for rule, methods in rules
        if rule.startswith("/system_discovery")
        and rule != "/system_discovery_train"
    )


class _FakeUseCases:
    def handle(self, message):
        if isinstance(message, RequireAuthenticatedSession):
            return None
        if isinstance(message, OpenSystemDiscoveryTrainingForm):
            return None
        if isinstance(message, ListSavedSystemDiscoveryModels):
            return ListSavedSystemDiscoveryModelsResult(models=[_model()])
        if isinstance(message, GetSavedSystemDiscoveryModelDetails):
            return GetSavedSystemDiscoveryModelDetailsResult(model=_model())
        if isinstance(message, ListSystemDiscoverySimulations):
            return ListSystemDiscoverySimulationsResult(simulations=[], failures=[])
        raise AssertionError(f"Unexpected message: {message!r}")


class _DenyingUseCases:
    def handle(self, message):
        if isinstance(message, RequireAuthenticatedSession):
            return None
        raise AuthorizationDeniedError("Not authorized.")


def _model() -> SystemDiscoverySavedModelRecord:
    return SystemDiscoverySavedModelRecord(
        model_id="model-1",
        source_training_id="train-1",
        model_name="narmax",
        saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        nlags_x=((1, 2),),
        nlags_y=1,
        basis="Polynomial",
        degree=2,
    )


def _metadata() -> SystemDiscoveryTrainingEvaluationMetadata:
    metric = SystemDiscoveryEvaluationMetric(value="1")
    return SystemDiscoveryTrainingEvaluationMetadata(
        analysis=None,
        sample_size="1",
        nse=metric,
        rmse=metric,
        nrmse=metric,
        pbias=metric,
        p_value="1",
        categories=[SystemDiscoveryEvaluationCategory("Good", "100%")],
    )


def test_front_no_longer_imports_legacy_system_discovery_modules() -> None:
    main_source = (ROOT / "src/services/front/main.py").read_text(encoding="utf-8")

    assert "endpoints.system_discovery.train_system_discovery" not in main_source
    assert "endpoints.system_discovery.register_system_discovery_engine" not in main_source
    assert "system_discovery_service" not in main_source
    assert "SystemDiscoveryPort" not in main_source
    assert "system_discovery_rest_adapter" not in main_source


def test_legacy_system_discovery_front_modules_were_removed() -> None:
    removed_paths = (
        "src/services/front/endpoints/system_discovery/train_system_discovery.py",
        "src/services/front/endpoints/system_discovery/register_system_discovery_engine.py",
        "src/services/front/endpoints/system_discovery/details/run_system_discovery_impl.py",
        "src/services/front/endpoints/system_discovery/details/register_system_discovery_model_impl.py",
    )

    for path in removed_paths:
        assert not (ROOT / path).exists()
