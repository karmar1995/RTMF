from __future__ import annotations

from dataclasses import dataclass

from use_case_contracts.errors import ExternalServiceError, NotFoundError, ValidationError


@dataclass(frozen=True)
class SystemDiscoveryAIStorConfigurationError(ExternalServiceError):
    message: str


@dataclass(frozen=True)
class SystemDiscoveryAIStorInvalidObjectKeyError(ValidationError):
    message: str


@dataclass(frozen=True)
class SystemDiscoveryAIStorBucketUnavailableError(ExternalServiceError):
    message: str


@dataclass(frozen=True)
class SystemDiscoveryAIStorObjectNotFoundError(NotFoundError):
    message: str


@dataclass(frozen=True)
class SystemDiscoveryAIStorTransferError(ExternalServiceError):
    message: str
