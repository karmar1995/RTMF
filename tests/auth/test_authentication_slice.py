from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from flask import request

from services.front.auth import RequestBoundUseCases
from services.front.main import app
from services.use_case.composition.build_usecases import _validate_identity_provider_mode
from services.use_case.security.api import DefaultRequestUseCaseAPIProvider
from services.use_case.security.authorization import MessagePermissionAuthorizer
from services.use_case.security.sessions import (
    InMemorySessionStore,
    SessionCredentialCodec,
    SessionService,
)
from use_case_contracts.dtos import (
    AuthenticatedIdentity,
    BrowserLoginChallenge,
    CurrentSessionContext,
    LoginCompleted,
)
from use_case_contracts.errors import (
    AuthorizationDeniedError,
    BrowserLoginFailedError,
    UnauthenticatedError,
)
from use_case_contracts.messages import (
    BeginBrowserLogin,
    CompleteBrowserLogin,
    GetCurrentSessionContext,
    HealthCheck,
    ListJobs,
    Logout,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class FakeInnerUseCases:
    def __init__(self, identity_provider=None, sessions=None) -> None:
        self.messages = []
        self.identity_provider = identity_provider
        self.sessions = sessions

    def handle(self, message):
        self.messages.append(message)
        if isinstance(message, BeginBrowserLogin):
            return self.identity_provider.begin_browser_login(
                callback_url=message.callback_url,
                force_reauthentication=message.force_reauthentication,
            )
        if isinstance(message, CompleteBrowserLogin):
            identity = self.identity_provider.complete_browser_login(
                authorization_code=message.authorization_code,
                state=message.state,
            )
            raw, record = self.sessions.create_session(identity)
            return LoginCompleted(raw_session_credential=raw, expires_at=record.absolute_expires_at)
        if isinstance(message, Logout):
            return type("LogoutCompleted", (), {})()
        if isinstance(message, ListJobs):
            return ["job-1"]
        if isinstance(message, HealthCheck):
            return "ok"
        raise AssertionError(f"Unexpected message: {message!r}")


class _BrowserIdentityProviderDouble:
    def __init__(
        self,
        *,
        clock: MutableClock,
        subject_id: str,
        permissions: list[str],
        pending_login_ttl_seconds: int = 300,
    ) -> None:
        self._clock = clock
        self._subject_id = subject_id
        self._permissions = frozenset(permissions)
        self._ttl = timedelta(seconds=pending_login_ttl_seconds)
        self._pending_by_code = {}

    def begin_browser_login(
        self,
        *,
        callback_url: str,
        force_reauthentication: bool = False,
    ) -> BrowserLoginChallenge:
        code = f"test-code-{len(self._pending_by_code) + 1}"
        state = f"test-state-{len(self._pending_by_code) + 1}"
        self._pending_by_code[code] = {
            "state": state,
            "expires_at": self._clock.now() + self._ttl,
            "used": False,
        }
        return BrowserLoginChallenge(
            authorization_url=f"{callback_url}?code={code}&state={state}",
            state=state,
        )

    def complete_browser_login(
        self,
        *,
        authorization_code: str,
        state: str,
    ) -> AuthenticatedIdentity:
        pending = self._pending_by_code.get(authorization_code)
        if (
            pending is None
            or pending["used"]
            or pending["state"] != state
            or self._clock.now() >= pending["expires_at"]
        ):
            raise BrowserLoginFailedError("Login failed.")
        pending["used"] = True
        return AuthenticatedIdentity(
            self._subject_id,
            self._permissions,
            "test",
        )

    def refresh_provider_session(self, provider_session_state: bytes) -> AuthenticatedIdentity:
        return AuthenticatedIdentity(
            self._subject_id,
            self._permissions,
            "test",
            provider_session_state=provider_session_state,
        )

    def revoke_provider_session(self, provider_session_state: bytes) -> None:
        return None


def test_given_test_login_double_starts_when_following_redirect_then_callback_receives_one_time_code_and_state() -> None:
    clock = MutableClock()
    provider = _BrowserIdentityProviderDouble(
        clock=clock,
        subject_id="user-1",
        permissions=["job.read"],
    )

    challenge = provider.begin_browser_login(callback_url="http://front/auth/callback")
    query = parse_qs(urlparse(challenge.authorization_url).query)
    identity = provider.complete_browser_login(
        authorization_code=query["code"][0],
        state=query["state"][0],
    )

    assert identity.subject_id == "user-1"
    assert identity.permissions == frozenset({"job.read"})
    with pytest.raises(BrowserLoginFailedError):
        provider.complete_browser_login(
            authorization_code=query["code"][0],
            state=query["state"][0],
        )


def test_given_invalid_or_expired_state_when_completing_login_then_authentication_fails() -> None:
    clock = MutableClock()
    provider = _BrowserIdentityProviderDouble(
        clock=clock,
        subject_id="user-1",
        permissions=["job.read"],
        pending_login_ttl_seconds=1,
    )

    invalid = parse_qs(
        urlparse(provider.begin_browser_login(callback_url="http://front/cb").authorization_url).query
    )
    with pytest.raises(BrowserLoginFailedError):
        provider.complete_browser_login(authorization_code=invalid["code"][0], state="wrong")

    expired = parse_qs(
        urlparse(provider.begin_browser_login(callback_url="http://front/cb").authorization_url).query
    )
    clock.advance(2)
    with pytest.raises(BrowserLoginFailedError):
        provider.complete_browser_login(
            authorization_code=expired["code"][0],
            state=expired["state"][0],
        )


def test_given_obsolete_fake_provider_mode_when_runtime_validates_config_then_startup_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="Keycloak only"):
        _validate_identity_provider_mode("fake")


def test_given_new_session_when_stored_then_only_digest_is_persisted_and_resolution_returns_principal() -> None:
    clock = MutableClock()
    store = InMemorySessionStore()
    sessions = SessionService(
        store=store,
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
    )

    first, _ = sessions.create_session(
        AuthenticatedIdentity("subject-1", frozenset({"job.read"}), "fake")
    )
    second, _ = sessions.create_session(
        AuthenticatedIdentity("subject-1", frozenset({"job.read"}), "fake")
    )
    principal = sessions.resolve(first)

    assert first != second
    assert all(ch.isalnum() or ch in "-_" for ch in first)
    assert first not in store.records_by_digest
    assert principal.subject_id == "subject-1"
    assert principal.permissions == frozenset({"job.read"})


def test_given_missing_unknown_expired_or_revoked_session_when_resolving_then_rejected() -> None:
    clock = MutableClock()
    sessions = SessionService(
        store=InMemorySessionStore(),
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=1,
        absolute_timeout_seconds=3,
    )

    with pytest.raises(UnauthenticatedError):
        sessions.resolve(None)
    with pytest.raises(UnauthenticatedError):
        sessions.resolve("unknown")

    raw, _ = sessions.create_session(AuthenticatedIdentity("subject-1", frozenset(), "fake"))
    clock.advance(2)
    with pytest.raises(UnauthenticatedError):
        sessions.resolve(raw)

    raw, _ = sessions.create_session(AuthenticatedIdentity("subject-1", frozenset(), "fake"))
    sessions.revoke(raw)
    with pytest.raises(UnauthenticatedError):
        sessions.resolve(raw)


def test_given_valid_session_when_authorized_message_handled_then_inner_bus_receives_it() -> None:
    clock = MutableClock()
    store = InMemorySessionStore()
    sessions = SessionService(
        store=store,
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
    )
    raw, _ = sessions.create_session(
        AuthenticatedIdentity("subject-1", frozenset({"job.read"}), "fake")
    )
    inner = FakeInnerUseCases()
    api = DefaultRequestUseCaseAPIProvider(
        inner=inner,
        sessions=sessions,
        authorizer=MessagePermissionAuthorizer(),
    ).bind_session(raw)

    assert api.handle(ListJobs()) == ["job-1"]
    assert isinstance(inner.messages[-1], ListJobs)


def test_given_valid_session_when_current_context_requested_then_ui_safe_context_returned() -> None:
    clock = MutableClock()
    sessions = SessionService(
        store=InMemorySessionStore(),
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
    )
    raw, _ = sessions.create_session(
        AuthenticatedIdentity(
            "subject-1",
            frozenset({"job.read", "simulator.read"}),
            "fake",
            provider_session_state=b"encrypted-provider-state",
        )
    )
    inner = FakeInnerUseCases()
    api = DefaultRequestUseCaseAPIProvider(
        inner=inner,
        sessions=sessions,
        authorizer=MessagePermissionAuthorizer(),
    ).bind_session(raw)

    context = api.handle(GetCurrentSessionContext())

    assert context == CurrentSessionContext(
        subject_id="subject-1",
        permissions=frozenset({"job.read", "simulator.read"}),
    )
    assert inner.messages == []


def test_given_missing_or_insufficient_session_when_protected_message_handled_then_denied() -> None:
    clock = MutableClock()
    sessions = SessionService(
        store=InMemorySessionStore(),
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
    )
    provider = DefaultRequestUseCaseAPIProvider(
        inner=FakeInnerUseCases(),
        sessions=sessions,
        authorizer=MessagePermissionAuthorizer(),
    )

    with pytest.raises(UnauthenticatedError):
        provider.bind_session(None).handle(ListJobs())

    raw, _ = sessions.create_session(
        AuthenticatedIdentity("subject-1", frozenset({"system.read"}), "fake")
    )
    with pytest.raises(AuthorizationDeniedError):
        provider.bind_session(raw).handle(ListJobs())


def test_given_unmapped_protected_message_when_handled_then_denied_by_default() -> None:
    @dataclass(frozen=True)
    class KnownButUnmappedMessage:
        value: str

    clock = MutableClock()
    sessions = SessionService(
        store=InMemorySessionStore(),
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
    )
    raw, _ = sessions.create_session(
        AuthenticatedIdentity("subject-1", frozenset({"job.read"}), "fake")
    )
    api = DefaultRequestUseCaseAPIProvider(
        inner=FakeInnerUseCases(),
        sessions=sessions,
        authorizer=MessagePermissionAuthorizer(),
    ).bind_session(raw)

    with pytest.raises(AuthorizationDeniedError):
        api.handle(KnownButUnmappedMessage("x"))


def test_given_front_test_login_when_callback_completes_then_cookie_is_httponly_and_token_not_in_body() -> None:
    clock = MutableClock()
    identity_provider = _BrowserIdentityProviderDouble(
        clock=clock,
        subject_id="user-1",
        permissions=["session.logout", "job.read"],
    )
    sessions = SessionService(
        store=InMemorySessionStore(),
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
    )
    inner = FakeInnerUseCases(identity_provider=identity_provider, sessions=sessions)
    request_provider = DefaultRequestUseCaseAPIProvider(
        inner=inner,
        sessions=sessions,
        authorizer=MessagePermissionAuthorizer(),
    )
    previous_usecases = app.extensions.get("usecases")
    previous_cookie_name = app.config.get("AUTH_SESSION_COOKIE_NAME")
    previous_secure = app.config.get("AUTH_SESSION_COOKIE_SECURE")
    previous_max_age = app.config.get("AUTH_SESSION_COOKIE_MAX_AGE")
    previous_callback_url = app.config.get("AUTH_CALLBACK_URL")
    app.config["AUTH_SESSION_COOKIE_NAME"] = "__Host-rtmf_session"
    app.config["AUTH_SESSION_COOKIE_SECURE"] = False
    app.config["AUTH_SESSION_COOKIE_MAX_AGE"] = 3600
    app.config["AUTH_CALLBACK_URL"] = "http://localhost/auth/callback"
    app.extensions["usecases"] = RequestBoundUseCases(
        provider=request_provider,
        request=request,
        cookie_name="__Host-rtmf_session",
    )
    try:
        client = app.test_client()
        login = client.get("/auth/login", follow_redirects=False)
        callback = client.get(login.headers["Location"], follow_redirects=False)

        set_cookie = callback.headers["Set-Cookie"]
        body = callback.get_data(as_text=True)
        raw_cookie = set_cookie.split("__Host-rtmf_session=", 1)[1].split(";", 1)[0]

        assert callback.status_code == 302
        assert "HttpOnly" in set_cookie
        assert raw_cookie not in body
        assert "code=" not in callback.headers["Location"]
        assert client.post("/auth/logout").status_code == 302
    finally:
        if previous_usecases is None:
            app.extensions.pop("usecases", None)
        else:
            app.extensions["usecases"] = previous_usecases
        app.config["AUTH_SESSION_COOKIE_NAME"] = previous_cookie_name
        app.config["AUTH_SESSION_COOKIE_SECURE"] = previous_secure
        app.config["AUTH_SESSION_COOKIE_MAX_AGE"] = previous_max_age
        app.config["AUTH_CALLBACK_URL"] = previous_callback_url


def test_given_front_login_callback_fails_then_local_cookie_is_cleared_and_browser_redirects_to_fresh_login() -> None:
    clock = MutableClock()
    identity_provider = _BrowserIdentityProviderDouble(
        clock=clock,
        subject_id="user-1",
        permissions=["job.read"],
    )
    sessions = SessionService(
        store=InMemorySessionStore(),
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
    )
    inner = FakeInnerUseCases(identity_provider=identity_provider, sessions=sessions)
    request_provider = DefaultRequestUseCaseAPIProvider(
        inner=inner,
        sessions=sessions,
        authorizer=MessagePermissionAuthorizer(),
    )
    previous_usecases = app.extensions.get("usecases")
    previous_cookie_name = app.config.get("AUTH_SESSION_COOKIE_NAME")
    previous_secure = app.config.get("AUTH_SESSION_COOKIE_SECURE")
    previous_max_age = app.config.get("AUTH_SESSION_COOKIE_MAX_AGE")
    previous_callback_url = app.config.get("AUTH_CALLBACK_URL")
    app.config["AUTH_SESSION_COOKIE_NAME"] = "rtmf_session"
    app.config["AUTH_SESSION_COOKIE_SECURE"] = False
    app.config["AUTH_SESSION_COOKIE_MAX_AGE"] = 3600
    app.config["AUTH_CALLBACK_URL"] = "http://localhost/auth/callback"
    app.extensions["usecases"] = RequestBoundUseCases(
        provider=request_provider,
        request=request,
        cookie_name="rtmf_session",
    )
    try:
        client = app.test_client()

        response = client.get("/auth/callback?code=unknown&state=unknown")

        set_cookie = response.headers["Set-Cookie"]
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/auth/login?fresh=1")
        assert "rtmf_session=" in set_cookie
        assert "Max-Age=0" in set_cookie
    finally:
        if previous_usecases is None:
            app.extensions.pop("usecases", None)
        else:
            app.extensions["usecases"] = previous_usecases
        app.config["AUTH_SESSION_COOKIE_NAME"] = previous_cookie_name
        app.config["AUTH_SESSION_COOKIE_SECURE"] = previous_secure
        app.config["AUTH_SESSION_COOKIE_MAX_AGE"] = previous_max_age
        app.config["AUTH_CALLBACK_URL"] = previous_callback_url
