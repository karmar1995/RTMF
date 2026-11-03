from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


class UseCaseError(Exception):
    """Base error for boundary failures."""


@dataclass(frozen=True)
class ValidationError(UseCaseError):
    message: str


@dataclass(frozen=True)
class NotFoundError(UseCaseError):
    message: str


@dataclass(frozen=True)
class ConflictError(UseCaseError):
    message: str


@dataclass(frozen=True)
class AuthenticationError(UseCaseError):
    message: str


@dataclass
class UnauthenticatedError(UseCaseError):
    message: str


@dataclass
class AuthorizationDeniedError(UseCaseError):
    message: str


@dataclass
class BrowserLoginFailedError(UseCaseError):
    message: str


@dataclass
class IdentityProviderUnavailableError(UseCaseError):
    message: str


@dataclass(frozen=True)
class ExternalServiceError(UseCaseError):
    message: str


@dataclass(frozen=True)
class UnregisteredMessageError(UseCaseError):
    message: str


@dataclass(frozen=True)
class TimeSeriesNotAlignedError(UseCaseError):
    message: str


@dataclass(frozen=True)
class UnsupportedVisualizationError(UseCaseError):
    message: str


class JobsRepositoryError(Exception):
    """Base class for all JobsRepository errors."""


class JobsRepositoryInvalidUrlError(JobsRepositoryError):
    """Raised when a requested URL is invalid for the repository (e.g., wrong scheme)."""

    def __init__(self, url: str) -> None:
        super().__init__(f"JobsRepository invalid url: {url}")


class JobsRepositoryInvalidStoreError(JobsRepositoryError):
    """Raised when the requested s3:// URL points to a different store than the repository store."""

    def __init__(self, expected_store: str, actual_store: str, url: str) -> None:
        super().__init__(
            f"JobsRepository invalid store in url (expected={expected_store}, actual={actual_store}): {url}"
        )


class JobsRepositoryMalformedUrlError(JobsRepositoryError):
    """Raised when an s3:// URL is syntactically parseable but missing required parts (store/key)."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"JobsRepository malformed url ({reason}): {url}")
        self.url = url
        self.reason = reason


class JobsRepositoryStoreMissingError(JobsRepositoryError):
    """Raised when the configured repository store does not exist."""

    def __init__(self, endpoint: str, store: str) -> None:
        super().__init__(f"JobsRepository store missing (endpoint={endpoint}, store={store})")
        self.endpoint = endpoint
        self.store = store


class JobsRepositoryStoreCheckFailedError(JobsRepositoryError):
    """Raised when checking store existence fails due to an underlying client error."""

    def __init__(self, endpoint: str, store: str, details: str) -> None:
        super().__init__(f"JobsRepository store check failed (endpoint={endpoint}, store={store}): {details}")
        self.endpoint = endpoint
        self.store = store


class JobsRepositoryObjectNotFoundError(JobsRepositoryError):
    """Raised when the requested object key does not exist in the configured store."""

    def __init__(self, endpoint: str, store: str, key: str) -> None:
        super().__init__(f"JobsRepository object not found (endpoint={endpoint}, store={store}, key={key})")
        self.endpoint = endpoint
        self.store = store
        self.key = key


class JobsRepositoryObjectDownloadFailedError(JobsRepositoryError):
    """Raised when downloading an object fails for reasons other than not-found (e.g., network/permission)."""

    def __init__(self, endpoint: str, store: str, key: str, details: str) -> None:
        super().__init__(
            f"JobsRepository download failed (endpoint={endpoint}, store={store}, key={key}): {details}"
        )
        self.endpoint = endpoint
        self.store = store
        self.key = key


class JobsRepositoryInvalidZipError(JobsRepositoryError):
    """Raised when a .zip object is not a valid zip archive."""

    def __init__(self, endpoint: str, store: str, key: str) -> None:
        super().__init__(f"JobsRepository invalid zip (endpoint={endpoint}, store={store}, key={key})")
        self.endpoint = endpoint
        self.store = store
        self.key = key


class JobsRepositoryZipHasNoFilesError(JobsRepositoryError):
    """Raised when a zip archive contains no regular files (only directories or empty)."""

    def __init__(self, endpoint: str, store: str, key: str) -> None:
        super().__init__(f"JobsRepository zip has no files (endpoint={endpoint}, store={store}, key={key})")
        self.endpoint = endpoint
        self.store = store
        self.key = key


class JobsRepositoryZipHasMultipleFilesError(JobsRepositoryError):
    """Raised when a zip archive contains multiple regular files (expected exactly one)."""

    def __init__(self, endpoint: str, store: str, key: str) -> None:
        super().__init__(f"JobsRepository zip has multiple files (endpoint={endpoint}, store={store}, key={key})")
        self.endpoint = endpoint
        self.store = store
        self.key = key


class JobsRepositoryResponseCleanupFailedError(JobsRepositoryError):
    """Raised when closing/releasing the storage response fails."""

    def __init__(self, endpoint: str, store: str, key: str, details: str) -> None:
        super().__init__(
            f"JobsRepository response cleanup failed (endpoint={endpoint}, store={store}, key={key}): {details}"
        )
        self.endpoint = endpoint
        self.store = store
        self.key = key


class JobsRepositoryResponseReadFailedError(JobsRepositoryError):
    """Raised when reading the object response fails (after get_object succeeded)."""

    def __init__(self, endpoint: str, store: str, key: str, details: str) -> None:
        super().__init__(
            f"JobsRepository response read failed (endpoint={endpoint}, store={store}, key={key}): {details}"
        )
        self.endpoint = endpoint
        self.store = store
        self.key = key


def error_to_dict(error: UseCaseError) -> Dict[str, str]:
    return {"type": error.__class__.__name__, "message": str(error)}
