from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

from adapters.keycloak_identity_adapter.oidc_discovery import OIDCDiscovery
from adapters.keycloak_identity_adapter.pending_login_store import (
    InMemoryPendingLoginStore,
    PendingLogin,
)
from adapters.keycloak_identity_adapter.token_cipher import KeycloakTokenCipher
from adapters.keycloak_identity_adapter.token_exchange import KeycloakTokenClient
from adapters.keycloak_identity_adapter.token_validation import TokenValidator
from services.use_case.utils import SystemClock
from use_case_contracts.dtos import AuthenticatedIdentity, BrowserLoginChallenge
from use_case_contracts.errors import BrowserLoginFailedError


class KeycloakBrowserIdentityProvider:
    def __init__(
        self,
        *,
        discovery: OIDCDiscovery,
        pending_logins: InMemoryPendingLoginStore,
        token_client: KeycloakTokenClient,
        token_validator: TokenValidator,
        token_cipher: KeycloakTokenCipher,
        clock: SystemClock,
        pending_login_ttl_seconds: int,
        client_id: str,
    ) -> None:
        self._discovery = discovery
        self._pending_logins = pending_logins
        self._token_client = token_client
        self._token_validator = token_validator
        self._token_cipher = token_cipher
        self._clock = clock
        self._ttl = timedelta(seconds=pending_login_ttl_seconds)
        self._client_id = client_id

    def begin_browser_login(
        self,
        *,
        callback_url: str,
        force_reauthentication: bool = False,
    ) -> BrowserLoginChallenge:
        now = self._clock.now()
        state = _token256()
        nonce = _token256()
        code_verifier = secrets.token_urlsafe(64)
        pending = PendingLogin(
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            callback_url=callback_url,
            created_at=now,
            expires_at=now + self._ttl,
        )
        self._pending_logins.save(pending)
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": callback_url,
            "scope": "openid profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": _pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        if force_reauthentication:
            params["prompt"] = "login"
        query = urlencode(params)
        return BrowserLoginChallenge(
            authorization_url=f"{self._discovery.metadata().authorization_endpoint}?{query}",
            state=state,
        )

    def complete_browser_login(
        self,
        *,
        authorization_code: str,
        state: str,
    ) -> AuthenticatedIdentity:
        pending = self._pending_logins.consume(state, now=self._clock.now())
        response = self._token_client.exchange_authorization_code(
            code=authorization_code,
            redirect_uri=pending.callback_url,
            code_verifier=pending.code_verifier,
        )
        return self._identity_from_response(response, nonce=pending.nonce)

    def refresh_provider_session(
        self,
        provider_session_state: bytes,
    ) -> AuthenticatedIdentity:
        state = self._token_cipher.decrypt(provider_session_state)
        refresh_token = state.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise BrowserLoginFailedError("Login failed.")
        response = self._token_client.refresh(refresh_token=refresh_token)
        if "refresh_token" not in response:
            response["refresh_token"] = refresh_token
        return self._identity_from_response(response, nonce=None)

    def revoke_provider_session(self, provider_session_state: bytes) -> None:
        try:
            state = self._token_cipher.decrypt(provider_session_state)
            refresh_token = state.get("refresh_token")
        except BrowserLoginFailedError:
            return
        if isinstance(refresh_token, str) and refresh_token:
            self._token_client.revoke(refresh_token=refresh_token)

    def _identity_from_response(
        self,
        response: dict[str, Any],
        *,
        nonce: str | None,
    ) -> AuthenticatedIdentity:
        access_token = response.get("access_token")
        id_token = response.get("id_token")
        refresh_token = response.get("refresh_token")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            raise BrowserLoginFailedError("Login failed.")
        if nonce is not None and not isinstance(id_token, str):
            raise BrowserLoginFailedError("Login failed.")
        subject_id, permissions, _access_claims, _id_claims = (
            self._token_validator.authenticated_identity_parts(
                id_token=id_token if isinstance(id_token, str) else None,
                access_token=access_token,
                nonce=nonce,
            )
        )
        access_expires_at, refresh_expires_at = self._token_client.token_expiry(response)
        encrypted_state = self._token_cipher.encrypt(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "id_token": id_token if isinstance(id_token, str) else "",
                "access_token_expires_at": access_expires_at.isoformat(),
                "refresh_token_expires_at": refresh_expires_at.isoformat()
                if refresh_expires_at
                else None,
            }
        )
        return AuthenticatedIdentity(
            subject_id=subject_id,
            permissions=permissions,
            authentication_provider="keycloak",
            provider_session_state=encrypted_state,
            access_token_expires_at=access_expires_at,
            refresh_token_expires_at=refresh_expires_at,
        )


def _token256() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
