from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse
import base64


@dataclass(frozen=True)
class KeycloakIdentityConfig:
    issuer_url: str
    client_id: str
    client_secret: str
    token_encryption_key: bytes
    permissions_client_id: str
    expected_access_token_audience: str
    allow_insecure_http_for_local_development: bool
    discovery_cache_seconds: int = 300
    jwks_cache_seconds: int = 300
    pending_login_ttl_seconds: int = 300
    token_request_timeout_seconds: float = 10.0
    clock_skew_seconds: int = 60

    def validate(self) -> None:
        _require_text(self.issuer_url, "Keycloak issuer URL")
        _require_text(self.client_id, "Keycloak client ID")
        _require_text(self.client_secret, "Keycloak client secret")
        _require_text(self.permissions_client_id, "Keycloak permissions client ID")
        _require_text(self.expected_access_token_audience, "Keycloak access-token audience")
        if len(self.token_encryption_key) != 32:
            raise RuntimeError("Keycloak token encryption key must decode to exactly 32 bytes.")
        issuer = urlparse(self.issuer_url)
        if issuer.scheme != "https" and not self.allow_insecure_http_for_local_development:
            raise RuntimeError("Keycloak issuer URL must use HTTPS.")


def read_keycloak_config(
    *,
    issuer_url: str,
    client_id: str,
    client_secret: str,
    token_encryption_key: str,
    permissions_client_id: str,
    expected_access_token_audience: str,
    allow_insecure_http_for_local_development: bool,
    discovery_cache_seconds: int = 300,
    jwks_cache_seconds: int = 300,
    pending_login_ttl_seconds: int = 300,
    token_request_timeout_seconds: float = 10.0,
    clock_skew_seconds: int = 60,
) -> KeycloakIdentityConfig:
    config = KeycloakIdentityConfig(
        issuer_url=issuer_url,
        client_id=client_id,
        client_secret=client_secret,
        token_encryption_key=_decode_key(token_encryption_key),
        permissions_client_id=permissions_client_id,
        expected_access_token_audience=expected_access_token_audience,
        allow_insecure_http_for_local_development=allow_insecure_http_for_local_development,
        discovery_cache_seconds=discovery_cache_seconds,
        jwks_cache_seconds=jwks_cache_seconds,
        pending_login_ttl_seconds=pending_login_ttl_seconds,
        token_request_timeout_seconds=token_request_timeout_seconds,
        clock_skew_seconds=clock_skew_seconds,
    )
    config.validate()
    return config


def _decode_key(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:
        raise RuntimeError("Keycloak token encryption key is not valid URL-safe base64.") from exc


def _require_text(value: str, label: str) -> None:
    if not value or not value.strip():
        raise RuntimeError(f"{label} is required.")
