from __future__ import annotations

from typing import Any

from services.use_case.security.authorization import MessagePermissionAuthorizer
from services.use_case.security.sessions import SessionService
from use_case_contracts.dtos import CurrentSessionContext
from use_case_contracts.messages import GetCurrentSessionContext
from use_case_contracts.ports import RequestUseCaseAPIProvider, UseCaseAPI


class SessionBoundUseCaseAPI(UseCaseAPI):
    def __init__(
        self,
        *,
        inner: UseCaseAPI,
        raw_session_credential: str | None,
        sessions: SessionService,
        authorizer: MessagePermissionAuthorizer,
    ) -> None:
        self._inner = inner
        self._raw_session_credential = raw_session_credential
        self._sessions = sessions
        self._authorizer = authorizer

    def handle(self, message: Any) -> Any:
        if self._authorizer.is_public(message):
            return self._inner.handle(message)
        principal = self._sessions.resolve(self._raw_session_credential)
        self._authorizer.assert_allowed(principal, message)
        if isinstance(message, GetCurrentSessionContext):
            return CurrentSessionContext(
                subject_id=principal.subject_id,
                permissions=frozenset(principal.permissions),
            )
        result = self._inner.handle(message)
        self._sessions.complete_authenticated_message(
            self._raw_session_credential,
            message,
        )
        return result


class DefaultRequestUseCaseAPIProvider(RequestUseCaseAPIProvider):
    def __init__(
        self,
        *,
        inner: UseCaseAPI,
        sessions: SessionService,
        authorizer: MessagePermissionAuthorizer,
    ) -> None:
        self._inner = inner
        self._sessions = sessions
        self._authorizer = authorizer

    def bind_session(self, raw_session_credential: str | None) -> UseCaseAPI:
        return SessionBoundUseCaseAPI(
            inner=self._inner,
            raw_session_credential=raw_session_credential,
            sessions=self._sessions,
            authorizer=self._authorizer,
        )
