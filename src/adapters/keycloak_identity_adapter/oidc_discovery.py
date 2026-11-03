from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urljoin, urlparse

import httpx

from adapters.keycloak_identity_adapter.config import KeycloakIdentityConfig
from services.use_case.utils import SystemClock
from use_case_contracts.errors import BrowserLoginFailedError, IdentityProviderUnavailableError


@dataclass(frozen=True)
class OIDCMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    revocation_endpoint: str


class OIDCDiscovery:
    def __init__(
        self,
        *,
        config: KeycloakIdentityConfig,
        clock: SystemClock,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._http = http_client or httpx.Client(timeout=config.token_request_timeout_seconds)
        self._cached: OIDCMetadata | None = None
        self._cached_until = None

    def metadata(self) -> OIDCMetadata:
        now = self._clock.now()
        if self._cached is not None and self._cached_until is not None and now < self._cached_until:
            return self._cached
        well_known = urljoin(
            self._config.issuer_url.rstrip("/") + "/",
            ".well-known/openid-configuration",
        )
        try:
            response = self._http.get(well_known, follow_redirects=False)
            response.raise_for_status()
            document = response.json()
        except httpx.HTTPStatusError as exc:
            raise IdentityProviderUnavailableError("Identity provider unavailable.") from exc
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailableError("Identity provider unavailable.") from exc
        except ValueError as exc:
            raise BrowserLoginFailedError("Login failed.") from exc
        metadata = self._parse(document)
        self._cached = metadata
        self._cached_until = now + timedelta(seconds=self._config.discovery_cache_seconds)
        return metadata

    def _parse(self, document: dict) -> OIDCMetadata:
        if document.get("issuer") != self._config.issuer_url:
            raise BrowserLoginFailedError("Login failed.")
        required = (
            "authorization_endpoint",
            "token_endpoint",
            "jwks_uri",
            "revocation_endpoint",
        )
        missing = [key for key in required if not document.get(key)]
        if missing:
            raise BrowserLoginFailedError("Login failed.")
        metadata = OIDCMetadata(
            issuer=document["issuer"],
            authorization_endpoint=document["authorization_endpoint"],
            token_endpoint=document["token_endpoint"],
            jwks_uri=document["jwks_uri"],
            revocation_endpoint=document["revocation_endpoint"],
        )
        self._validate_endpoint(metadata.authorization_endpoint)
        self._validate_endpoint(metadata.token_endpoint)
        self._validate_endpoint(metadata.jwks_uri)
        self._validate_endpoint(metadata.revocation_endpoint)
        return metadata

    def _validate_endpoint(self, endpoint: str) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" and not self._config.allow_insecure_http_for_local_development:
            raise BrowserLoginFailedError("Login failed.")
        if parsed.netloc != urlparse(self._config.issuer_url).netloc:
            raise BrowserLoginFailedError("Login failed.")
