from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from adapters.keycloak_identity_adapter.browser_login import KeycloakBrowserIdentityProvider
from adapters.keycloak_identity_adapter.config import KeycloakIdentityConfig, read_keycloak_config
from adapters.keycloak_identity_adapter.oidc_discovery import OIDCDiscovery
from adapters.keycloak_identity_adapter.pending_login_store import InMemoryPendingLoginStore
from adapters.keycloak_identity_adapter.token_cipher import KeycloakTokenCipher
from adapters.keycloak_identity_adapter.token_exchange import KeycloakTokenClient
from adapters.keycloak_identity_adapter.token_validation import JWKSCache, TokenValidator
from services.front.auth import RequestBoundUseCases
from services.front.main import app
from services.use_case.composition.build_usecases import (
    UseCaseContainer,
    _validate_identity_provider_mode,
)
from services.use_case.security.api import DefaultRequestUseCaseAPIProvider
from services.use_case.security.authorization import MessagePermissionAuthorizer
from services.use_case.security.sessions import InMemorySessionStore, SessionCredentialCodec, SessionService
from use_case_contracts.dtos import AuthenticatedIdentity, LoginCompleted, MonitorEntries
from use_case_contracts.messages import (
    BeginBrowserLogin,
    CompleteBrowserLogin,
    GetJobSubJobs,
    ListJobs,
    ListMonitorEntries,
    RequireAuthenticatedSession,
)
from use_case_contracts.errors import BrowserLoginFailedError, IdentityProviderUnavailableError, UnauthenticatedError

ROOT = Path(__file__).resolve().parents[2]


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime.now(timezone.utc)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def test_given_valid_discovery_document_when_loaded_then_metadata_is_accepted() -> None:
    env = _env()
    provider, calls = _provider(env)

    challenge = provider.begin_browser_login(callback_url="https://front.example/auth/callback")

    assert challenge.authorization_url.startswith(f"{env.issuer}/protocol/openid-connect/auth?")
    assert calls["discovery"] == 1


def test_given_discovery_issuer_mismatch_or_missing_endpoint_when_loaded_then_rejected() -> None:
    env = _env()

    provider, _calls = _provider(env, discovery_override={"issuer": "https://other.example/realms/rtmf"})
    with pytest.raises(BrowserLoginFailedError):
        provider.begin_browser_login(callback_url="https://front.example/auth/callback")

    provider, _calls = _provider(env, discovery_override={"token_endpoint": None})
    with pytest.raises(BrowserLoginFailedError):
        provider.begin_browser_login(callback_url="https://front.example/auth/callback")


def test_given_insecure_http_not_allowed_when_http_issuer_then_rejected() -> None:
    with pytest.raises(RuntimeError, match="HTTPS"):
        KeycloakIdentityConfig(
            issuer_url="http://localhost:8080/realms/rtmf",
            client_id="rtmf-web",
            client_secret="secret",
            token_encryption_key=b"x" * 32,
            permissions_client_id="rtmf-use-case",
            expected_access_token_audience="rtmf-use-case",
            allow_insecure_http_for_local_development=False,
        ).validate()


def test_given_missing_keycloak_value_or_bad_encryption_key_when_building_config_then_fails() -> None:
    with pytest.raises(RuntimeError, match="issuer URL"):
        read_keycloak_config(
            issuer_url="",
            client_id="rtmf-web",
            client_secret="secret",
            token_encryption_key="bad",
            permissions_client_id="rtmf-use-case",
            expected_access_token_audience="rtmf-use-case",
            allow_insecure_http_for_local_development=False,
        )

    with pytest.raises(RuntimeError, match="32 bytes"):
        read_keycloak_config(
            issuer_url="https://kc.example/realms/rtmf",
            client_id="rtmf-web",
            client_secret="secret",
            token_encryption_key="bad",
            permissions_client_id="rtmf-use-case",
            expected_access_token_audience="rtmf-use-case",
            allow_insecure_http_for_local_development=False,
        )


def test_given_obsolete_fake_provider_mode_when_runtime_validates_config_then_rejected() -> None:
    with pytest.raises(RuntimeError, match="Keycloak only"):
        _validate_identity_provider_mode("fake")


def test_runtime_source_tree_has_no_fake_identity_provider_adapter() -> None:
    assert not (ROOT / "src/adapters/fake_identity_provider").exists()


def test_supported_configuration_has_no_fake_identity_provider_keys() -> None:
    for path in (
        ROOT / "config/deployment.example.json",
        ROOT / "config/rtmf.local.example.json",
    ):
        content = path.read_text(encoding="utf-8")

        assert "fake_identity_provider" not in content
        assert "default_subject_id" not in content
        assert "default_permissions" not in content
        assert '"identity_provider": "fake"' not in content


def test_given_keycloak_runtime_config_when_composed_then_identity_provider_is_keycloak() -> None:
    container = UseCaseContainer()
    container.config.from_dict(_minimal_use_case_auth_config())

    provider = container.identity_provider()

    assert isinstance(provider, KeycloakBrowserIdentityProvider)


def test_given_login_started_when_authorization_url_built_then_contains_callback_state_nonce_and_pkce() -> None:
    env = _env()
    provider, _calls = _provider(env)

    challenge = provider.begin_browser_login(callback_url="https://front.example/auth/callback")
    params = _authorization_params(env, challenge)

    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["rtmf-web"]
    assert params["redirect_uri"] == ["https://front.example/auth/callback"]
    assert params["scope"] == ["openid profile"]
    assert params["state"] == [challenge.state]
    assert len(params["nonce"][0]) >= 43
    assert params["code_challenge_method"] == ["S256"]
    assert len(params["code_challenge"][0]) >= 43


def test_given_forced_reauthentication_when_login_starts_then_authorization_url_requests_login_prompt() -> None:
    env = _env()
    provider, _calls = _provider(env)

    normal = provider.begin_browser_login(callback_url="https://front.example/auth/callback")
    forced = provider.begin_browser_login(
        callback_url="https://front.example/auth/callback",
        force_reauthentication=True,
    )

    assert "prompt" not in _authorization_params(env, normal)
    assert _authorization_params(env, forced)["prompt"] == ["login"]


def test_given_callback_when_completed_then_code_exchange_uses_redirect_uri_verifier_and_basic_auth() -> None:
    env = _env()
    provider, calls = _provider(env)
    challenge = provider.begin_browser_login(callback_url="https://front.example/auth/callback")
    params = _authorization_params(env, challenge)

    identity = provider.complete_browser_login(
        authorization_code="auth-code",
        state=params["state"][0],
    )

    token_request = calls["token_requests"][0]
    assert token_request["data"]["grant_type"] == "authorization_code"
    assert token_request["data"]["code"] == "auth-code"
    assert token_request["data"]["redirect_uri"] == "https://front.example/auth/callback"
    assert token_request["data"]["code_verifier"]
    assert token_request["auth"] == ("rtmf-web", "client-secret")
    assert identity.subject_id == "subject-1"
    assert identity.permissions == frozenset({"job.read"})
    with pytest.raises(BrowserLoginFailedError):
        provider.complete_browser_login(authorization_code="auth-code", state=params["state"][0])


def test_given_failed_code_exchange_when_completed_then_authentication_fails_without_provider_details() -> None:
    env = _env()
    provider, _calls = _provider(env, token_status=400, token_body={"error": "invalid_grant", "detail": "secret"})
    challenge = provider.begin_browser_login(callback_url="https://front.example/auth/callback")
    state = _authorization_params(env, challenge)["state"][0]

    with pytest.raises(BrowserLoginFailedError) as exc:
        provider.complete_browser_login(authorization_code="bad", state=state)

    assert "secret" not in str(exc.value)


def test_given_valid_signed_tokens_when_completed_then_identity_and_encrypted_state_are_returned() -> None:
    env = _env()
    provider, _calls = _provider(env)
    challenge = provider.begin_browser_login(callback_url="https://front.example/auth/callback")
    state = _authorization_params(env, challenge)["state"][0]

    identity = provider.complete_browser_login(authorization_code="auth-code", state=state)

    assert identity.subject_id == "subject-1"
    assert identity.permissions == frozenset({"job.read"})
    assert b"access-token" not in identity.provider_session_state
    assert b"refresh-token" not in identity.provider_session_state


def test_given_invalid_jwt_claims_when_completed_then_rejected() -> None:
    for override in (
        {"issuer": "https://wrong.example/realms/rtmf"},
        {"id_aud": "other-client"},
        {"access_aud": "other-audience"},
        {"access_azp": "other-client"},
        {"nonce": "wrong-nonce"},
        {"access_sub": "other-subject"},
        {"expired": True},
    ):
        env = _env()
        provider, _calls = _provider(env, claim_override=override)
        challenge = provider.begin_browser_login(callback_url="https://front.example/auth/callback")
        state = _authorization_params(env, challenge)["state"][0]

        with pytest.raises(BrowserLoginFailedError):
            provider.complete_browser_login(authorization_code="auth-code", state=state)


def test_given_unknown_kid_when_validating_then_jwks_refreshes_once() -> None:
    first_key = _jwt_key("old-kid")
    second_key = _jwt_key("new-kid")
    env = _env(key=second_key)
    provider, calls = _provider(env, jwks_sequence=[first_key.jwk, second_key.jwk])
    challenge = provider.begin_browser_login(callback_url="https://front.example/auth/callback")
    state = _authorization_params(env, challenge)["state"][0]

    provider.complete_browser_login(authorization_code="auth-code", state=state)

    assert calls["jwks"] == 2


def test_given_unknown_roles_when_mapping_then_they_do_not_grant_permissions() -> None:
    env = _env()
    provider, _calls = _provider(env, roles=["job.read", "unknown.role"])
    challenge = provider.begin_browser_login(callback_url="https://front.example/auth/callback")
    state = _authorization_params(env, challenge)["state"][0]

    identity = provider.complete_browser_login(authorization_code="auth-code", state=state)

    assert identity.permissions == frozenset({"job.read"})


def test_given_valid_user_without_rtmf_roles_when_mapping_then_login_succeeds_with_no_permissions() -> None:
    env = _env()
    provider, _calls = _provider(
        env,
        claim_override={"access_aud": None},
        omit_resource_access=True,
    )
    challenge = provider.begin_browser_login(callback_url="https://front.example/auth/callback")
    state = _authorization_params(env, challenge)["state"][0]

    identity = provider.complete_browser_login(authorization_code="auth-code", state=state)

    assert identity.subject_id == "subject-1"
    assert identity.permissions == frozenset()


def test_given_encrypted_state_when_encrypting_twice_then_ciphertexts_differ_and_malformed_rejected() -> None:
    cipher = KeycloakTokenCipher(b"x" * 32)

    first = cipher.encrypt({"access_token": "access-token", "refresh_token": "refresh-token"})
    second = cipher.encrypt({"access_token": "access-token", "refresh_token": "refresh-token"})

    assert first != second
    assert b"access-token" not in first
    assert b"refresh-token" not in first
    with pytest.raises(BrowserLoginFailedError):
        cipher.decrypt(b"not-json")


def test_given_non_expiring_session_when_resolved_then_refresh_is_not_called() -> None:
    clock = MutableClock()
    provider = CountingProvider()
    sessions = SessionService(
        store=InMemorySessionStore(),
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
        refresh_skew_seconds=30,
        identity_provider=provider,
    )
    raw, _record = sessions.create_session(
        AuthenticatedIdentity(
            "subject-1",
            frozenset({"job.read"}),
            "keycloak",
            provider_session_state=b"encrypted",
            access_token_expires_at=clock.now() + timedelta(seconds=300),
        )
    )

    sessions.resolve(raw)

    assert provider.refresh_calls == 0


def test_given_near_expiry_session_when_resolved_then_refresh_updates_permissions() -> None:
    clock = MutableClock()
    provider = CountingProvider(
        refreshed=AuthenticatedIdentity(
            "subject-1",
            frozenset({"system.read"}),
            "keycloak",
            provider_session_state=b"new-encrypted",
            access_token_expires_at=clock.now() + timedelta(seconds=300),
        )
    )
    sessions = SessionService(
        store=InMemorySessionStore(),
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
        refresh_skew_seconds=30,
        identity_provider=provider,
    )
    raw, _record = sessions.create_session(
        AuthenticatedIdentity(
            "subject-1",
            frozenset({"job.read"}),
            "keycloak",
            provider_session_state=b"encrypted",
            access_token_expires_at=clock.now() + timedelta(seconds=5),
        )
    )

    principal = sessions.resolve(raw)

    assert principal.permissions == frozenset({"system.read"})
    assert provider.refresh_calls == 1


def test_given_refresh_invalid_grant_when_resolved_then_local_session_is_revoked() -> None:
    clock = MutableClock()
    provider = CountingProvider(refresh_error=BrowserLoginFailedError("Login failed."))
    store = InMemorySessionStore()
    sessions = SessionService(
        store=store,
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
        refresh_skew_seconds=30,
        identity_provider=provider,
    )
    raw, record = sessions.create_session(
        AuthenticatedIdentity(
            "subject-1",
            frozenset({"job.read"}),
            "keycloak",
            provider_session_state=b"encrypted",
            access_token_expires_at=clock.now() + timedelta(seconds=5),
        )
    )

    with pytest.raises(UnauthenticatedError):
        sessions.resolve(raw)

    assert store.get(record.token_digest).revoked_at is not None


def test_given_refresh_provider_unavailable_when_resolved_then_local_session_remains_active() -> None:
    clock = MutableClock()
    provider = CountingProvider(refresh_error=IdentityProviderUnavailableError("Identity provider unavailable."))
    store = InMemorySessionStore()
    sessions = SessionService(
        store=store,
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
        refresh_skew_seconds=30,
        identity_provider=provider,
    )
    raw, record = sessions.create_session(
        AuthenticatedIdentity(
            "subject-1",
            frozenset({"job.read"}),
            "keycloak",
            provider_session_state=b"encrypted",
            access_token_expires_at=clock.now() + timedelta(seconds=5),
        )
    )

    with pytest.raises(IdentityProviderUnavailableError):
        sessions.resolve(raw)

    assert store.get(record.token_digest).revoked_at is None


def test_given_logout_when_provider_revocation_fails_then_local_session_stays_revoked() -> None:
    clock = MutableClock()
    provider = CountingProvider(revoke_error=RuntimeError("outage"))
    store = InMemorySessionStore()
    sessions = SessionService(
        store=store,
        codec=SessionCredentialCodec("pepper"),
        clock=clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
        identity_provider=provider,
    )
    raw, record = sessions.create_session(
        AuthenticatedIdentity(
            "subject-1",
            frozenset({"job.read"}),
            "keycloak",
            provider_session_state=b"encrypted",
        )
    )

    sessions.logout(raw)

    assert store.get(record.token_digest).revoked_at is not None
    assert provider.revoke_calls == 1
    with pytest.raises(UnauthenticatedError):
        sessions.resolve(raw)


def test_given_front_keycloak_login_when_cookie_used_then_protected_operation_obeys_roles() -> None:
    env = _env()
    keycloak_provider, _calls = _provider(env)
    sessions = SessionService(
        store=InMemorySessionStore(),
        codec=SessionCredentialCodec("pepper"),
        clock=env.clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
        refresh_skew_seconds=30,
        identity_provider=keycloak_provider,
    )
    request_provider = DefaultRequestUseCaseAPIProvider(
        inner=FrontInnerUseCases(keycloak_provider, sessions),
        sessions=sessions,
        authorizer=MessagePermissionAuthorizer(),
    )
    previous = _install_front_auth(request_provider)
    try:
        client = app.test_client()
        unauthenticated = client.get("/simulation_monitor", follow_redirects=False)
        login = client.get("/auth/login", follow_redirects=False)
        params = parse_qs(urlparse(login.headers["Location"]).query)
        env.current_nonce = params["nonce"][0]
        callback = client.get(
            f"/auth/callback?code=auth-code&state={params['state'][0]}",
            follow_redirects=False,
        )
        protected = client.get("/simulation_monitor")

        assert unauthenticated.status_code == 302
        assert unauthenticated.headers["Location"].endswith("/auth/login")
        assert callback.status_code == 302
        assert "HttpOnly" in callback.headers["Set-Cookie"]
        assert "access_token" not in callback.get_data(as_text=True)
        assert "refresh_token" not in callback.get_data(as_text=True)
        assert protected.status_code == 200
    finally:
        _restore_front_auth(previous)


def test_given_front_keycloak_login_without_permission_when_welcome_page_then_visible_but_protected_operation_forbidden() -> None:
    env = _env()
    keycloak_provider, _calls = _provider(env, roles=[])
    sessions = SessionService(
        store=InMemorySessionStore(),
        codec=SessionCredentialCodec("pepper"),
        clock=env.clock,
        idle_timeout_seconds=60,
        absolute_timeout_seconds=3600,
        refresh_skew_seconds=30,
        identity_provider=keycloak_provider,
    )
    request_provider = DefaultRequestUseCaseAPIProvider(
        inner=FrontInnerUseCases(keycloak_provider, sessions),
        sessions=sessions,
        authorizer=MessagePermissionAuthorizer(),
    )
    previous = _install_front_auth(request_provider)
    try:
        client = app.test_client()
        login = client.get("/auth/login", follow_redirects=False)
        params = parse_qs(urlparse(login.headers["Location"]).query)
        env.current_nonce = params["nonce"][0]
        client.get(
            f"/auth/callback?code=auth-code&state={params['state'][0]}",
            follow_redirects=False,
        )

        welcome = client.get("/")
        protected = client.get("/simulation_monitor")

        assert welcome.status_code == 200
        assert protected.status_code == 403
    finally:
        _restore_front_auth(previous)


class CountingProvider:
    def __init__(self, refreshed=None, refresh_error=None, revoke_error=None) -> None:
        self.refresh_calls = 0
        self.revoke_calls = 0
        self.refreshed = refreshed or AuthenticatedIdentity(
            "subject-1",
            frozenset({"job.read"}),
            "keycloak",
            provider_session_state=b"encrypted",
        )
        self.refresh_error = refresh_error
        self.revoke_error = revoke_error

    def begin_browser_login(
        self,
        *,
        callback_url: str,
        force_reauthentication: bool = False,
    ):
        raise NotImplementedError

    def complete_browser_login(self, *, authorization_code: str, state: str):
        raise NotImplementedError

    def refresh_provider_session(self, provider_session_state: bytes) -> AuthenticatedIdentity:
        self.refresh_calls += 1
        if self.refresh_error:
            raise self.refresh_error
        return self.refreshed

    def revoke_provider_session(self, provider_session_state: bytes) -> None:
        self.revoke_calls += 1
        if self.revoke_error:
            raise self.revoke_error


class FrontInnerUseCases:
    def __init__(self, identity_provider, sessions) -> None:
        self.identity_provider = identity_provider
        self.sessions = sessions

    def handle(self, message):
        if isinstance(message, BeginBrowserLogin):
            return self.identity_provider.begin_browser_login(callback_url=message.callback_url)
        if isinstance(message, CompleteBrowserLogin):
            identity = self.identity_provider.complete_browser_login(
                authorization_code=message.authorization_code,
                state=message.state,
            )
            raw, record = self.sessions.create_session(identity)
            return LoginCompleted(raw_session_credential=raw, expires_at=record.absolute_expires_at)
        if isinstance(message, RequireAuthenticatedSession):
            return None
        if isinstance(message, ListJobs):
            return [type("Job", (), {"job_id": "job-1"})()]
        if isinstance(message, ListMonitorEntries):
            return MonitorEntries(
                simulation_group_ids=["job-1"],
                evaluations=[],
            )
        if isinstance(message, GetJobSubJobs):
            return []
        raise AssertionError(f"Unexpected message: {message!r}")


class JWTKey:
    def __init__(self, kid: str) -> None:
        self.kid = kid
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_numbers = self.private_key.public_key().public_numbers()
        self.jwk = {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": kid,
            "n": _int_b64(public_numbers.n),
            "e": _int_b64(public_numbers.e),
        }


class Env:
    def __init__(self, key: JWTKey | None = None) -> None:
        self.issuer = "https://kc.example/realms/rtmf"
        self.key = key or _jwt_key("kid-1")
        self.clock = MutableClock()
        self.current_nonce = "unset"
        self.config = KeycloakIdentityConfig(
            issuer_url=self.issuer,
            client_id="rtmf-web",
            client_secret="client-secret",
            token_encryption_key=b"x" * 32,
            permissions_client_id="rtmf-use-case",
            expected_access_token_audience="rtmf-use-case",
            allow_insecure_http_for_local_development=False,
            pending_login_ttl_seconds=2,
        )


def _provider(
    env: Env,
    *,
    discovery_override: dict | None = None,
    token_status: int = 200,
    token_body: dict | None = None,
    claim_override: dict | None = None,
    roles: list[str] | None = None,
    omit_resource_access: bool = False,
    jwks_sequence: list[dict] | None = None,
):
    calls = {"discovery": 0, "jwks": 0, "token_requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            calls["discovery"] += 1
            document = _discovery(env.issuer)
            if discovery_override:
                document.update(discovery_override)
            return httpx.Response(200, json=document)
        if request.url.path.endswith("/certs"):
            calls["jwks"] += 1
            keys = jwks_sequence[calls["jwks"] - 1 : calls["jwks"]] if jwks_sequence else [env.key.jwk]
            return httpx.Response(200, json={"keys": keys})
        if request.url.path.endswith("/token"):
            data = dict(parse_qs(request.content.decode("utf-8")))
            flat = {key: values[0] for key, values in data.items()}
            auth = request.headers.get("authorization", "")
            calls["token_requests"].append(
                {"data": flat, "auth": _basic_auth_tuple(auth)}
            )
            if token_status != 200:
                return httpx.Response(token_status, json=token_body or {"error": "invalid_grant"})
            state = _tokens(env, flat, claim_override=claim_override, roles=roles, omit_resource_access=omit_resource_access)
            if token_body:
                state.update(token_body)
            return httpx.Response(200, json=state)
        if request.url.path.endswith("/revoke"):
            return httpx.Response(200, json={})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    discovery = OIDCDiscovery(config=env.config, clock=env.clock, http_client=client)
    token_client = KeycloakTokenClient(config=env.config, discovery=discovery, clock=env.clock, http_client=client)
    jwks = JWKSCache(discovery=discovery, config=env.config, clock=env.clock, http_client=client)
    validator = TokenValidator(config=env.config, jwks=jwks)
    provider = KeycloakBrowserIdentityProvider(
        discovery=discovery,
        pending_logins=InMemoryPendingLoginStore(),
        token_client=token_client,
        token_validator=validator,
        token_cipher=KeycloakTokenCipher(env.config.token_encryption_key),
        clock=env.clock,
        pending_login_ttl_seconds=env.config.pending_login_ttl_seconds,
        client_id=env.config.client_id,
    )
    return provider, calls


def _env(key: JWTKey | None = None) -> Env:
    return Env(key=key)


def _minimal_use_case_auth_config() -> dict:
    return {
        "authentication": {
            "identity_provider": "keycloak",
            "session": {
                "cookie_name": "__Host-rtmf_session",
                "idle_timeout_seconds": 1800,
                "absolute_timeout_seconds": 28800,
                "refresh_skew_seconds": 300,
                "token_pepper": "test-session-pepper",
            },
            "keycloak": {
                "issuer_url": "https://kc.example/realms/rtmf",
                "client_id": "rtmf-web",
                "client_secret": "secret",
                "token_encryption_key": base64.urlsafe_b64encode(b"x" * 32).rstrip(b"=").decode("ascii"),
                "permissions_client_id": "rtmf-use-case",
                "expected_access_token_audience": "rtmf-use-case",
                "allow_insecure_http_for_local_development": False,
                "discovery_cache_seconds": 300,
                "jwks_cache_seconds": 300,
                "pending_login_ttl_seconds": 300,
                "token_request_timeout_seconds": 10,
                "clock_skew_seconds": 60,
            },
        }
    }


def _install_front_auth(request_provider):
    previous = {
        "usecases": app.extensions.get("usecases"),
        "cookie_name": app.config.get("AUTH_SESSION_COOKIE_NAME"),
        "secure": app.config.get("AUTH_SESSION_COOKIE_SECURE"),
        "max_age": app.config.get("AUTH_SESSION_COOKIE_MAX_AGE"),
        "callback": app.config.get("AUTH_CALLBACK_URL"),
        "enforced": app.config.get("AUTH_ENFORCED"),
    }
    app.config["AUTH_SESSION_COOKIE_NAME"] = "__Host-rtmf_session"
    app.config["AUTH_SESSION_COOKIE_SECURE"] = False
    app.config["AUTH_SESSION_COOKIE_MAX_AGE"] = 3600
    app.config["AUTH_CALLBACK_URL"] = "https://front.example/auth/callback"
    app.config["AUTH_ENFORCED"] = True
    app.extensions["usecases"] = RequestBoundUseCases(
        provider=request_provider,
        request=__import__("flask").request,
        cookie_name="__Host-rtmf_session",
    )
    return previous


def _restore_front_auth(previous) -> None:
    if previous["usecases"] is None:
        app.extensions.pop("usecases", None)
    else:
        app.extensions["usecases"] = previous["usecases"]
    app.config["AUTH_SESSION_COOKIE_NAME"] = previous["cookie_name"]
    app.config["AUTH_SESSION_COOKIE_SECURE"] = previous["secure"]
    app.config["AUTH_SESSION_COOKIE_MAX_AGE"] = previous["max_age"]
    app.config["AUTH_CALLBACK_URL"] = previous["callback"]
    app.config["AUTH_ENFORCED"] = previous["enforced"]


def _jwt_key(kid: str) -> JWTKey:
    return JWTKey(kid)


def _tokens(env: Env, data: dict, *, claim_override=None, roles=None, omit_resource_access=False) -> dict:
    claim_override = claim_override or {}
    now = env.clock.now()
    exp = now - timedelta(seconds=120) if claim_override.get("expired") else now + timedelta(minutes=5)
    id_claims = {
        "iss": claim_override.get("issuer", env.issuer),
        "sub": "subject-1",
        "aud": claim_override.get("id_aud", "rtmf-web"),
        "azp": "rtmf-web",
        "nonce": claim_override.get("nonce", env.current_nonce),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    access_claims = {
        "iss": claim_override.get("issuer", env.issuer),
        "sub": claim_override.get("access_sub", "subject-1"),
        "azp": claim_override.get("access_azp", "rtmf-web"),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    access_aud = claim_override.get("access_aud", "rtmf-use-case")
    if access_aud is not None:
        access_claims["aud"] = access_aud
    if not omit_resource_access:
        access_claims["resource_access"] = {
            "rtmf-use-case": {"roles": ["job.read"] if roles is None else roles}
        }
    return {
        "access_token": _encode(access_claims, env.key),
        "id_token": _encode(id_claims, env.key),
        "refresh_token": "refresh-token",
        "expires_in": 300,
        "refresh_expires_in": 3600,
    }

def _authorization_params(env: Env, challenge) -> dict[str, list[str]]:
    params = parse_qs(urlparse(challenge.authorization_url).query)
    env.current_nonce = params["nonce"][0]
    return params


def _encode(claims: dict, key: JWTKey) -> str:
    return jwt.encode(claims, key.private_key, algorithm="RS256", headers={"kid": key.kid})


def _discovery(issuer: str) -> dict:
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/protocol/openid-connect/auth",
        "token_endpoint": f"{issuer}/protocol/openid-connect/token",
        "jwks_uri": f"{issuer}/protocol/openid-connect/certs",
        "revocation_endpoint": f"{issuer}/protocol/openid-connect/revoke",
    }


def _int_b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _basic_auth_tuple(header: str) -> tuple[str, str] | None:
    if not header.startswith("Basic "):
        return None
    decoded = base64.b64decode(header.removeprefix("Basic ")).decode("utf-8")
    client_id, secret = decoded.split(":", 1)
    return client_id, secret
