from __future__ import annotations

from typing import Any

from flask import Request

from use_case_contracts.ports import RequestUseCaseAPIProvider, UseCaseAPI


class RequestBoundUseCases(UseCaseAPI):
    def __init__(
        self,
        *,
        provider: RequestUseCaseAPIProvider,
        request: Request,
        cookie_name: str,
    ) -> None:
        self._provider = provider
        self._request = request
        self._cookie_name = cookie_name

    def handle(self, message: Any) -> Any:
        raw_session_credential = self._request.cookies.get(self._cookie_name)
        return self._provider.bind_session(raw_session_credential).handle(message)
