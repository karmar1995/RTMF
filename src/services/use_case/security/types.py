from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Principal:
    subject_id: str
    permissions: frozenset[str]
    authentication_provider: str


@dataclass(frozen=True)
class SessionRecord:
    token_digest: str
    subject_id: str
    permissions: frozenset[str]
    authentication_provider: str
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    provider_session_state: bytes = b""
    access_token_expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    version: int = 0
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None
