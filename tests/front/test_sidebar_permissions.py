from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from services.front.navigation import SidebarItem, is_sidebar_item_visible
from services.front.main import app
from use_case_contracts.dtos import CurrentSessionContext
from use_case_contracts.errors import AuthorizationDeniedError, UnauthenticatedError
from use_case_contracts.messages import (
    GetCurrentSessionContext,
    OpenRegisterSimulatorForm,
    OpenSimulationRunForm,
    RequireAuthenticatedSession,
)
from use_case_contracts.permissions import (
    JOB_CREATE,
    JOB_READ,
    SIMULATION_READ,
    SIMULATOR_READ,
    SIMULATOR_WRITE,
    SYSTEM_DISCOVERY_MODEL_READ,
    SYSTEM_DISCOVERY_SIMULATION_READ,
    SYSTEM_DISCOVERY_TRAINING_READ,
    SYSTEM_DISCOVERY_TRAINING_WRITE,
)


ROOT = Path(__file__).resolve().parents[2]


def test_user_with_required_permission_sees_matching_sidebar_item() -> None:
    with _installed_auth(_FakeUseCases({SIMULATOR_WRITE})):
        body = app.test_client().get("/").get_data(as_text=True)

    assert 'href="/register_model"' in body
    assert "Register" in body


def test_user_without_required_permission_does_not_see_sidebar_item() -> None:
    with _installed_auth(_FakeUseCases({SIMULATOR_READ})):
        body = app.test_client().get("/").get_data(as_text=True)

    assert 'href="/register_model"\n         class="btn btn-outline-light' not in body
    assert "\n         Register\n" not in body


def test_user_with_one_any_of_permission_satisfies_sidebar_predicate() -> None:
    item = SidebarItem(
        key="visualization",
        label="Visualization",
        endpoint="onSimulationVisualization",
        required_permissions=frozenset({JOB_READ, SIMULATION_READ}),
        permission_mode="any",
    )

    assert is_sidebar_item_visible(item, frozenset({SIMULATION_READ}))


def test_user_missing_one_all_of_permission_does_not_see_sidebar_item() -> None:
    with _installed_auth(_FakeUseCases({JOB_CREATE})):
        body = app.test_client().get("/").get_data(as_text=True)

    assert 'href="/run_simulation"\n         class="btn btn-outline-light' not in body
    assert "\n         Run Simulation\n" not in body


def test_empty_navigation_group_is_hidden() -> None:
    with _installed_auth(_FakeUseCases({SIMULATOR_READ})):
        body = app.test_client().get("/").get_data(as_text=True)

    assert "System Discovery</span>" not in body
    assert "Train Model" not in body
    assert "Saved models" not in body


def test_common_navigation_remains_visible_to_authenticated_user() -> None:
    with _installed_auth(_FakeUseCases(set())):
        body = app.test_client().get("/").get_data(as_text=True)

    assert 'href="/"' in body
    assert "Home" in body


def test_unauthenticated_request_does_not_render_protected_sidebar_entries() -> None:
    with _installed_auth(_UnauthenticatedUseCases()):
        response = app.test_client().get("/")

    body = response.get_data(as_text=True)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")
    assert 'href="/register_model"\n         class="btn btn-outline-light' not in body
    assert "\n         Run Simulation\n" not in body


def test_manually_entered_protected_route_remains_denied_without_permission() -> None:
    with _installed_auth(_FakeUseCases({SIMULATOR_READ})):
        register_response = app.test_client().get("/register_model")
        run_response = app.test_client().get("/run_simulation")

    assert register_response.status_code == 403
    assert run_response.status_code == 403


def test_sidebar_code_does_not_depend_on_keycloak_jwts_session_store_or_cookie_values() -> None:
    navigation_source = (ROOT / "src/services/front/navigation.py").read_text(encoding="utf-8")
    sidebar_source = (ROOT / "src/services/front/templates/_sidebar.html").read_text(
        encoding="utf-8"
    )

    combined = f"{navigation_source}\n{sidebar_source}".lower()
    for forbidden in (
        "keycloak",
        "jwt",
        "principal",
        "sessionstore",
        "session_store",
        "cookie",
        "access_token",
        "refresh_token",
        "id_token",
    ):
        assert forbidden not in combined


def test_fully_authorized_sidebar_preserves_existing_links_ordering_and_active_state() -> None:
    permissions = {
        SIMULATOR_WRITE,
        SIMULATOR_READ,
        JOB_CREATE,
        JOB_READ,
        SIMULATION_READ,
        SYSTEM_DISCOVERY_TRAINING_WRITE,
        SYSTEM_DISCOVERY_TRAINING_READ,
        SYSTEM_DISCOVERY_MODEL_READ,
        SYSTEM_DISCOVERY_SIMULATION_READ,
    }
    with _installed_auth(_FakeUseCases(permissions)):
        body = app.test_client().get("/").get_data(as_text=True)

    expected_links = (
        'href="/"',
        'href="/register_model"',
        'href="/simulators/registration_status"',
        'href="/simulators/browse"',
        'href="/run_simulation"',
        'href="/simulation_monitor"',
        'href="/simulation_visualization"',
        'href="/system_discovery_train"',
        'href="/system-discovery/trainings"',
        'href="/system-discovery/models"',
        'href="/system-discovery/simulations"',
    )
    positions = [body.index(link) for link in expected_links]

    assert positions == sorted(positions)
    assert 'btn btn-outline-light mb-2 w-100 active' in body
    assert "Simulators</span>" in body
    assert "Simulation</span>" in body
    assert "System Discovery</span>" in body
    assert 'method="post"' in body
    assert 'action="/auth/logout"' in body
    assert ">Logout</button>" in body


@contextmanager
def _installed_auth(usecases):
    previous_usecases = app.extensions.get("usecases")
    previous_auth_enforced = app.config.get("AUTH_ENFORCED")
    previous_callback_url = app.config.get("AUTH_CALLBACK_URL")
    app.extensions["usecases"] = usecases
    app.config["AUTH_ENFORCED"] = True
    app.config["AUTH_CALLBACK_URL"] = "/auth/login"
    try:
        yield
    finally:
        if previous_usecases is None:
            app.extensions.pop("usecases", None)
        else:
            app.extensions["usecases"] = previous_usecases
        if previous_auth_enforced is None:
            app.config.pop("AUTH_ENFORCED", None)
        else:
            app.config["AUTH_ENFORCED"] = previous_auth_enforced
        if previous_callback_url is None:
            app.config.pop("AUTH_CALLBACK_URL", None)
        else:
            app.config["AUTH_CALLBACK_URL"] = previous_callback_url


class _FakeUseCases:
    def __init__(self, permissions: set[str]) -> None:
        self.permissions = frozenset(permissions)

    def handle(self, message):
        if isinstance(message, RequireAuthenticatedSession):
            return None
        if isinstance(message, GetCurrentSessionContext):
            return CurrentSessionContext(
                subject_id="subject-1",
                permissions=self.permissions,
            )
        if isinstance(message, OpenRegisterSimulatorForm):
            if SIMULATOR_WRITE in self.permissions:
                return None
            raise AuthorizationDeniedError("Not authorized.")
        if isinstance(message, OpenSimulationRunForm):
            if JOB_CREATE in self.permissions:
                return None
            raise AuthorizationDeniedError("Not authorized.")
        raise AssertionError(f"Unexpected message: {message!r}")


class _UnauthenticatedUseCases:
    def handle(self, message):
        raise UnauthenticatedError("Authentication is required.")
