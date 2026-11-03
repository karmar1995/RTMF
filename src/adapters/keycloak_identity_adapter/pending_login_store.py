from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import threading

from use_case_contracts.errors import BrowserLoginFailedError


@dataclass(frozen=True)
class PendingLogin:
    state: str
    nonce: str
    code_verifier: str
    callback_url: str
    created_at: datetime
    expires_at: datetime
    consumed: bool = False


class InMemoryPendingLoginStore:
    """Process-local pending-login store; pending logins are lost on restart."""

    def __init__(self) -> None:
        self._pending_by_state: dict[str, PendingLogin] = {}
        self._lock = threading.Lock()

    def save(self, pending: PendingLogin) -> None:
        with self._lock:
            self._pending_by_state[pending.state] = pending

    def consume(self, state: str, *, now: datetime) -> PendingLogin:
        with self._lock:
            pending = self._pending_by_state.get(state)
            if pending is None or pending.consumed or now >= pending.expires_at:
                self._pending_by_state.pop(state, None)
                raise BrowserLoginFailedError("Login failed.")
            consumed = PendingLogin(
                state=pending.state,
                nonce=pending.nonce,
                code_verifier=pending.code_verifier,
                callback_url=pending.callback_url,
                created_at=pending.created_at,
                expires_at=pending.expires_at,
                consumed=True,
            )
            self._pending_by_state[state] = consumed
            return consumed
