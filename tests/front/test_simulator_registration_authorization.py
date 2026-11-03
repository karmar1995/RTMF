from __future__ import annotations

from services.front.main import app
from use_case_contracts.errors import AuthorizationDeniedError
from use_case_contracts.messages import OpenRegisterSimulatorForm, RequireAuthenticatedSession


def test_simulator_registration_form_checks_write_permission_before_rendering() -> None:
    fake = _AllowingUseCases()

    with _installed_usecases(fake):
        response = app.test_client().get("/register_model")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'method="post"' in body
    assert 'action="/auth/logout"' in body
    assert ">Logout</button>" in body
    assert any(isinstance(message, OpenRegisterSimulatorForm) for message in fake.messages)


def test_simulator_registration_form_is_denied_without_write_permission() -> None:
    with _installed_usecases(_DenyingUseCases()):
        response = app.test_client().get("/register_model")

    assert response.status_code == 403


class _installed_usecases:
    def __init__(self, usecases) -> None:
        self._usecases = usecases
        self._previous = None

    def __enter__(self):
        self._previous = app.extensions.get("usecases")
        app.extensions["usecases"] = self._usecases
        return self._usecases

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._previous is None:
            app.extensions.pop("usecases", None)
        else:
            app.extensions["usecases"] = self._previous


class _AllowingUseCases:
    def __init__(self) -> None:
        self.messages = []

    def handle(self, message):
        self.messages.append(message)
        if isinstance(message, (RequireAuthenticatedSession, OpenRegisterSimulatorForm)):
            return None
        raise AssertionError(f"Unexpected message: {message!r}")


class _DenyingUseCases:
    def handle(self, message):
        if isinstance(message, RequireAuthenticatedSession):
            return None
        raise AuthorizationDeniedError("Not authorized.")
