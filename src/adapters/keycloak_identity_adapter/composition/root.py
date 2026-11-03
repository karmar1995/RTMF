from __future__ import annotations

from dependency_injector import containers, providers

from adapters.keycloak_identity_adapter.browser_login import KeycloakBrowserIdentityProvider
from adapters.keycloak_identity_adapter.config import read_keycloak_config
from adapters.keycloak_identity_adapter.oidc_discovery import OIDCDiscovery
from adapters.keycloak_identity_adapter.pending_login_store import InMemoryPendingLoginStore
from adapters.keycloak_identity_adapter.token_cipher import KeycloakTokenCipher
from adapters.keycloak_identity_adapter.token_exchange import KeycloakTokenClient
from adapters.keycloak_identity_adapter.token_validation import JWKSCache, TokenValidator


class KeycloakIdentityAdapterContainer(containers.DeclarativeContainer):
    config = providers.Configuration()
    clock = providers.Dependency()

    keycloak_config = providers.Singleton(
        read_keycloak_config,
        issuer_url=config.issuer_url,
        client_id=config.client_id,
        client_secret=config.client_secret,
        token_encryption_key=config.token_encryption_key,
        permissions_client_id=config.permissions_client_id,
        expected_access_token_audience=config.expected_access_token_audience,
        allow_insecure_http_for_local_development=config.allow_insecure_http_for_local_development.as_(bool),
        discovery_cache_seconds=config.discovery_cache_seconds.as_int(),
        jwks_cache_seconds=config.jwks_cache_seconds.as_int(),
        pending_login_ttl_seconds=config.pending_login_ttl_seconds.as_int(),
        token_request_timeout_seconds=config.token_request_timeout_seconds.as_(float),
        clock_skew_seconds=config.clock_skew_seconds.as_int(),
    )

    discovery = providers.Singleton(
        OIDCDiscovery,
        config=keycloak_config,
        clock=clock,
    )
    pending_login_store = providers.Singleton(InMemoryPendingLoginStore)
    token_cipher = providers.Singleton(
        KeycloakTokenCipher,
        key=keycloak_config.provided.token_encryption_key,
    )
    token_client = providers.Singleton(
        KeycloakTokenClient,
        config=keycloak_config,
        discovery=discovery,
        clock=clock,
    )
    jwks_cache = providers.Singleton(
        JWKSCache,
        discovery=discovery,
        config=keycloak_config,
        clock=clock,
    )
    token_validator = providers.Singleton(
        TokenValidator,
        config=keycloak_config,
        jwks=jwks_cache,
    )
    identity_provider = providers.Singleton(
        KeycloakBrowserIdentityProvider,
        discovery=discovery,
        pending_logins=pending_login_store,
        token_client=token_client,
        token_validator=token_validator,
        token_cipher=token_cipher,
        clock=clock,
        pending_login_ttl_seconds=keycloak_config.provided.pending_login_ttl_seconds,
        client_id=keycloak_config.provided.client_id,
    )
