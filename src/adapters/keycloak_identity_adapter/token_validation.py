from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import jwt

try:
    from jwt.exceptions import PyJWTError
except ImportError:
    PyJWTError = None

from adapters.keycloak_identity_adapter.claim_mapping import map_permissions
from adapters.keycloak_identity_adapter.config import KeycloakIdentityConfig
from adapters.keycloak_identity_adapter.oidc_discovery import OIDCDiscovery
from services.use_case.utils import SystemClock
from use_case_contracts.errors import BrowserLoginFailedError, IdentityProviderUnavailableError


def _assert_pyjwt_available() -> None:
    missing = [
        name
        for name in ("decode", "get_unverified_header", "PyJWK")
        if not hasattr(jwt, name)
    ]
    if missing or PyJWTError is None:
        raise RuntimeError(
            "PyJWT[crypto] is required for Keycloak token validation. "
            "The active Python environment imported a different 'jwt' package. "
            "Install the project dependencies into the interpreter used to run RTMF "
            "and remove the incompatible 'jwt' package."
        )


_assert_pyjwt_available()


class JWKSCache:
    def __init__(
        self,
        *,
        discovery: OIDCDiscovery,
        config: KeycloakIdentityConfig,
        clock: SystemClock,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._discovery = discovery
        self._config = config
        self._clock = clock
        self._http = http_client or httpx.Client(timeout=config.token_request_timeout_seconds)
        self._jwks: dict[str, Any] | None = None
        self._cached_until = None

    def key_for(self, kid: str):
        jwks = self._get_jwks()
        key = self._find_key(jwks, kid)
        if key is None:
            jwks = self._get_jwks(force=True)
            key = self._find_key(jwks, kid)
        if key is None:
            raise BrowserLoginFailedError("Login failed.")
        return jwt.PyJWK.from_dict(key).key

    def _get_jwks(self, *, force: bool = False) -> dict[str, Any]:
        now = self._clock.now()
        if (
            not force
            and self._jwks is not None
            and self._cached_until is not None
            and now < self._cached_until
        ):
            return self._jwks
        try:
            response = self._http.get(self._discovery.metadata().jwks_uri, follow_redirects=False)
            response.raise_for_status()
            jwks = response.json()
        except httpx.HTTPStatusError as exc:
            raise IdentityProviderUnavailableError("Identity provider unavailable.") from exc
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailableError("Identity provider unavailable.") from exc
        except ValueError as exc:
            raise BrowserLoginFailedError("Login failed.") from exc
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            raise BrowserLoginFailedError("Login failed.")
        self._jwks = jwks
        self._cached_until = now + timedelta(seconds=self._config.jwks_cache_seconds)
        return jwks

    @staticmethod
    def _find_key(jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
        for key in jwks["keys"]:
            if isinstance(key, dict) and key.get("kid") == kid:
                return key
        return None


class TokenValidator:
    def __init__(
        self,
        *,
        config: KeycloakIdentityConfig,
        jwks: JWKSCache,
    ) -> None:
        self._config = config
        self._jwks = jwks

    def validate_id_token(self, token: str, *, nonce: str) -> dict[str, Any]:
        claims = self._decode(token, audience=self._config.client_id)
        if claims.get("nonce") != nonce:
            raise BrowserLoginFailedError("Login failed.")
        azp = claims.get("azp")
        aud = claims.get("aud")
        if isinstance(aud, list) and len(aud) > 1 and azp != self._config.client_id:
            raise BrowserLoginFailedError("Login failed.")
        if not claims.get("sub"):
            raise BrowserLoginFailedError("Login failed.")
        return claims

    def validate_access_token(self, token: str) -> tuple[dict[str, Any], frozenset[str]]:
        claims = self._decode(token, audience=None)
        if claims.get("azp") != self._config.client_id:
            raise BrowserLoginFailedError("Login failed.")
        if not claims.get("sub"):
            raise BrowserLoginFailedError("Login failed.")
        permissions = map_permissions(
            claims,
            permissions_client_id=self._config.permissions_client_id,
        )
        if permissions and not _audience_contains(
            claims.get("aud"),
            self._config.expected_access_token_audience,
        ):
            raise BrowserLoginFailedError("Login failed.")
        return claims, permissions

    def authenticated_identity_parts(
        self,
        *,
        id_token: str | None,
        access_token: str,
        nonce: str | None,
    ) -> tuple[str, frozenset[str], dict[str, Any], dict[str, Any] | None]:
        access_claims, permissions = self.validate_access_token(access_token)
        id_claims = self.validate_id_token(id_token, nonce=nonce) if id_token and nonce else None
        if id_claims is not None and id_claims["sub"] != access_claims["sub"]:
            raise BrowserLoginFailedError("Login failed.")
        return access_claims["sub"], permissions, access_claims, id_claims

    def _decode(self, token: str, *, audience: str | None) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            alg = header.get("alg")
            if not kid or alg != "RS256":
                raise BrowserLoginFailedError("Login failed.")
            key = self._jwks.key_for(kid)
            options = {"require": ["exp", "iat", "sub"]}
            if audience is None:
                options["verify_aud"] = False
            return jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=audience,
                issuer=self._config.issuer_url,
                leeway=self._config.clock_skew_seconds,
                options=options,
            )
        except BrowserLoginFailedError:
            raise
        except IdentityProviderUnavailableError:
            raise
        except PyJWTError as exc:
            raise BrowserLoginFailedError("Login failed.") from exc


def _audience_contains(audience: Any, expected: str) -> bool:
    if isinstance(audience, str):
        return audience == expected
    if isinstance(audience, list):
        return expected in audience
    return False
