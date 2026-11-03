from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
from dataclasses import replace
from datetime import timedelta
from typing import Any

from services.use_case.security.types import Principal, SessionRecord
from services.use_case.utils import SystemClock
from use_case_contracts.dtos import AuthenticatedIdentity
from use_case_contracts.errors import (
    BrowserLoginFailedError,
    IdentityProviderUnavailableError,
    UnauthenticatedError,
)
from use_case_contracts.messages import Logout
from use_case_contracts.ports import BrowserIdentityProvider


class InMemorySessionStore:
    """Development adapter: sessions are process-local and lost on restart."""

    def __init__(self) -> None:
        self.records_by_digest: dict[str, SessionRecord] = {}
        self._locks_by_digest: dict[str, threading.Lock] = {}

    def save(self, record: SessionRecord) -> None:
        self.records_by_digest[record.token_digest] = record

    def get(self, token_digest: str) -> SessionRecord | None:
        return self.records_by_digest.get(token_digest)

    def replace(self, record: SessionRecord) -> None:
        self.records_by_digest[record.token_digest] = record

    def lock_for(self, token_digest: str) -> threading.Lock:
        lock = self._locks_by_digest.get(token_digest)
        if lock is None:
            lock = threading.Lock()
            self._locks_by_digest[token_digest] = lock
        return lock


class SessionCredentialCodec:
    def __init__(self, pepper: str) -> None:
        if not pepper:
            raise ValueError("Session token pepper must not be empty")
        self._pepper = pepper.encode("utf-8")

    def generate(self) -> str:
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")

    def digest(self, raw_session_credential: str) -> str:
        return hmac.new(
            self._pepper,
            raw_session_credential.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()


class SessionService:
    def __init__(
        self,
        *,
        store: InMemorySessionStore,
        codec: SessionCredentialCodec,
        clock: SystemClock,
        idle_timeout_seconds: int,
        absolute_timeout_seconds: int,
        refresh_skew_seconds: int = 300,
        identity_provider: BrowserIdentityProvider | None = None,
    ) -> None:
        self._store = store
        self._codec = codec
        self._clock = clock
        self._idle_timeout = timedelta(seconds=idle_timeout_seconds)
        self._absolute_timeout = timedelta(seconds=absolute_timeout_seconds)
        self._refresh_skew = timedelta(seconds=refresh_skew_seconds)
        self._identity_provider = identity_provider

    def create_session(self, identity: AuthenticatedIdentity) -> tuple[str, SessionRecord]:
        now = self._clock.now()
        raw = self._codec.generate()
        record = SessionRecord(
            token_digest=self._codec.digest(raw),
            subject_id=identity.subject_id,
            permissions=frozenset(identity.permissions),
            authentication_provider=identity.authentication_provider,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + self._idle_timeout,
            absolute_expires_at=now + self._absolute_timeout,
            provider_session_state=identity.provider_session_state,
            access_token_expires_at=identity.access_token_expires_at,
            refresh_token_expires_at=identity.refresh_token_expires_at,
            revoked_at=None,
        )
        self._store.save(record)
        return raw, record

    def resolve(self, raw_session_credential: str | None) -> Principal:
        if not raw_session_credential:
            raise UnauthenticatedError("Authentication is required.")
        try:
            token_digest = self._codec.digest(raw_session_credential)
        except UnicodeEncodeError as exc:
            raise UnauthenticatedError("Authentication is required.") from exc
        record = self._store.get(token_digest)
        if record is None:
            raise UnauthenticatedError("Authentication is required.")
        now = self._clock.now()
        if (
            not record.active
            or now >= record.idle_expires_at
            or now >= record.absolute_expires_at
        ):
            raise UnauthenticatedError("Authentication is required.")
        record = self._refresh_if_needed(record, now)
        next_idle_expiry = min(now + self._idle_timeout, record.absolute_expires_at)
        self._store.replace(
            replace(
                record,
                last_seen_at=now,
                idle_expires_at=next_idle_expiry,
                version=record.version + 1,
            )
        )
        return Principal(
            subject_id=record.subject_id,
            permissions=record.permissions,
            authentication_provider=record.authentication_provider,
        )

    def revoke(self, raw_session_credential: str | None) -> None:
        if not raw_session_credential:
            return
        try:
            token_digest = self._codec.digest(raw_session_credential)
        except UnicodeEncodeError:
            return
        record = self._store.get(token_digest)
        if record is None or record.revoked_at is not None:
            return
        self._store.replace(replace(record, revoked_at=self._clock.now()))

    def complete_authenticated_message(
        self,
        raw_session_credential: str | None,
        message: Any,
    ) -> None:
        if isinstance(message, Logout):
            self.logout(raw_session_credential)

    def logout(self, raw_session_credential: str | None) -> None:
        if not raw_session_credential:
            return
        try:
            token_digest = self._codec.digest(raw_session_credential)
        except UnicodeEncodeError:
            return
        provider_session_state = b""
        with self._store.lock_for(token_digest):
            record = self._store.get(token_digest)
            if record is None:
                return
            provider_session_state = record.provider_session_state
            if record.revoked_at is None:
                self._store.replace(
                    replace(
                        record,
                        revoked_at=self._clock.now(),
                        version=record.version + 1,
                    )
                )
        self._revoke_provider_session_best_effort(provider_session_state)

    def _revoke_provider_session_best_effort(self, provider_session_state: bytes) -> None:
        if not provider_session_state or self._identity_provider is None:
            return
        try:
            self._identity_provider.revoke_provider_session(provider_session_state)
        except Exception:
            return

    def _refresh_if_needed(self, record: SessionRecord, now) -> SessionRecord:
        if (
            self._identity_provider is None
            or not record.provider_session_state
            or record.access_token_expires_at is None
            or now + self._refresh_skew < record.access_token_expires_at
        ):
            return record
        with self._store.lock_for(record.token_digest):
            current = self._store.get(record.token_digest)
            if current is None:
                raise UnauthenticatedError("Authentication is required.")
            if (
                not current.active
                or now >= current.idle_expires_at
                or now >= current.absolute_expires_at
            ):
                raise UnauthenticatedError("Authentication is required.")
            if (
                current.access_token_expires_at is not None
                and now + self._refresh_skew < current.access_token_expires_at
            ):
                return current
            try:
                identity = self._identity_provider.refresh_provider_session(
                    current.provider_session_state
                )
            except IdentityProviderUnavailableError:
                raise
            except BrowserLoginFailedError as exc:
                self._store.replace(replace(current, revoked_at=now))
                raise UnauthenticatedError("Authentication is required.") from exc
            refreshed = replace(
                current,
                subject_id=identity.subject_id,
                permissions=frozenset(identity.permissions),
                authentication_provider=identity.authentication_provider,
                provider_session_state=identity.provider_session_state,
                access_token_expires_at=identity.access_token_expires_at,
                refresh_token_expires_at=identity.refresh_token_expires_at,
                version=current.version + 1,
            )
            self._store.replace(refreshed)
            return refreshed
