from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from adapters.keycloak_identity_adapter.config import KeycloakIdentityConfig
from adapters.keycloak_identity_adapter.oidc_discovery import OIDCDiscovery
from services.use_case.utils import SystemClock
from use_case_contracts.errors import BrowserLoginFailedError, IdentityProviderUnavailableError


class KeycloakTokenClient:
    def __init__(
        self,
        *,
        config: KeycloakIdentityConfig,
        discovery: OIDCDiscovery,
        clock: SystemClock,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._discovery = discovery
        self._clock = clock
        self._http = http_client or httpx.Client(timeout=config.token_request_timeout_seconds)

    def exchange_authorization_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict[str, Any]:
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        )

    def refresh(self, *, refresh_token: str) -> dict[str, Any]:
        return self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            invalid_grant_reauth=True,
        )

    def revoke(self, *, refresh_token: str) -> None:
        try:
            response = self._http.post(
                self._discovery.metadata().revocation_endpoint,
                data={"token": refresh_token, "token_type_hint": "refresh_token"},
                auth=(self._config.client_id, self._config.client_secret),
                follow_redirects=False,
            )
            response.raise_for_status()
        except Exception:
            return

    def token_expiry(self, response: dict[str, Any]) -> tuple[datetime, datetime | None]:
        now = self._clock.now()
        expires_in = response.get("expires_in")
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise BrowserLoginFailedError("Login failed.")
        refresh_expires_in = response.get("refresh_expires_in")
        refresh_expires_at = (
            now + timedelta(seconds=refresh_expires_in)
            if isinstance(refresh_expires_in, int) and refresh_expires_in > 0
            else None
        )
        return now + timedelta(seconds=expires_in), refresh_expires_at

    def _token_request(
        self,
        data: dict[str, str],
        *,
        invalid_grant_reauth: bool = False,
    ) -> dict[str, Any]:
        try:
            response = self._http.post(
                self._discovery.metadata().token_endpoint,
                data=data,
                auth=(self._config.client_id, self._config.client_secret),
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailableError("Identity provider unavailable.") from exc
        if response.status_code >= 500:
            raise IdentityProviderUnavailableError("Identity provider unavailable.")
        if response.status_code >= 400:
            if invalid_grant_reauth:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if body.get("error") == "invalid_grant":
                    raise BrowserLoginFailedError("Login failed.")
            raise BrowserLoginFailedError("Login failed.")
        try:
            token_response = response.json()
        except ValueError as exc:
            raise BrowserLoginFailedError("Login failed.") from exc
        self._require_token_response(token_response, refresh_required=not invalid_grant_reauth)
        return token_response

    @staticmethod
    def _require_token_response(response: dict[str, Any], *, refresh_required: bool) -> None:
        required = ("access_token", "expires_in")
        if refresh_required:
            required = required + ("refresh_token", "id_token")
        if not isinstance(response, dict) or any(not response.get(key) for key in required):
            raise BrowserLoginFailedError("Login failed.")
        if not isinstance(response.get("access_token"), str):
            raise BrowserLoginFailedError("Login failed.")
        if "refresh_token" in response and not isinstance(response["refresh_token"], str):
            raise BrowserLoginFailedError("Login failed.")
        if "id_token" in response and not isinstance(response["id_token"], str):
            raise BrowserLoginFailedError("Login failed.")
