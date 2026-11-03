from __future__ import annotations

from dataclasses import dataclass

from use_case_contracts.errors import ExternalServiceError, NotFoundError, ValidationError


@dataclass(frozen=True)
class SystemDiscoveryServiceUnavailableError(ExternalServiceError):
    message: str


@dataclass(frozen=True)
class SystemDiscoveryRequestRejectedError(ValidationError):
    message: str


@dataclass(frozen=True)
class SystemDiscoveryResourceNotFoundError(NotFoundError):
    message: str


@dataclass(frozen=True)
class SystemDiscoveryProtocolError(ExternalServiceError):
    message: str
