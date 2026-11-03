from __future__ import annotations

from services.use_case.security.sessions import SessionService
from use_case_contracts.dtos import LoginCompleted, LogoutCompleted
from use_case_contracts.messages import (
    BeginBrowserLogin,
    CompleteBrowserLogin,
    Logout,
    OpenEvaluationRunForm,
    OpenRegisterSimulatorForm,
    OpenSimulationRunForm,
    OpenSystemDiscoveryTrainingForm,
    RequireAuthenticatedSession,
)
from use_case_contracts.ports import BrowserIdentityProvider


def handle_begin_browser_login(
    message: BeginBrowserLogin,
    *,
    identity_provider: BrowserIdentityProvider,
):
    return identity_provider.begin_browser_login(
        callback_url=message.callback_url,
        force_reauthentication=message.force_reauthentication,
    )


def handle_complete_browser_login(
    message: CompleteBrowserLogin,
    *,
    identity_provider: BrowserIdentityProvider,
    sessions: SessionService,
) -> LoginCompleted:
    identity = identity_provider.complete_browser_login(
        authorization_code=message.authorization_code,
        state=message.state,
    )
    raw_session_credential, record = sessions.create_session(identity)
    return LoginCompleted(
        raw_session_credential=raw_session_credential,
        expires_at=record.absolute_expires_at,
    )


def handle_logout(message: Logout) -> LogoutCompleted:
    return LogoutCompleted()


def handle_require_authenticated_session(message: RequireAuthenticatedSession) -> None:
    return None


def handle_open_register_simulator_form(message: OpenRegisterSimulatorForm) -> None:
    return None


def handle_open_simulation_run_form(message: OpenSimulationRunForm) -> None:
    return None


def handle_open_evaluation_run_form(message: OpenEvaluationRunForm) -> None:
    return None


def handle_open_system_discovery_training_form(
    message: OpenSystemDiscoveryTrainingForm,
) -> None:
    return None
