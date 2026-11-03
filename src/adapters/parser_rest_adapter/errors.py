from __future__ import annotations

from use_case_contracts.errors import ExternalServiceError


class ParserRestAdapterError(ExternalServiceError):
    pass


class ParserRestConnectionError(ParserRestAdapterError):
    pass


class ParserRestHttpError(ParserRestAdapterError):
    def __init__(self, message: str, *, status_code: int, response_body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class ParserRestInvalidResponseError(ParserRestAdapterError):
    pass
