class ValidationError(Exception):
    """Raised when an input is invalid."""


class NotFoundError(Exception):
    """Raised when the requested resource does not exist."""


class ExternalServiceError(Exception):
    """Raised when an external dependency fails."""


class AuthenticationError(Exception):
    """Raised when authentication with an external dependency fails."""


class SlurmUnavailableError(ExternalServiceError):
    """Raised when Slurm is temporarily unavailable."""

    def __init__(self, message: str, *, diagnostic_context: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.diagnostic_context = diagnostic_context or {}


class SlurmConfigurationError(Exception):
    """Raised when local Slurm runtime configuration is invalid."""

    def __init__(self, message: str, *, diagnostic_context: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.diagnostic_context = diagnostic_context or {}


class SlurmTokenUnavailableError(SlurmUnavailableError):
    """Raised when Slurm token generation is temporarily unavailable."""


class SlurmAuthenticationError(AuthenticationError):
    """Raised when Slurm rejects scheduler authentication."""

    def __init__(self, message: str, *, diagnostic_context: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.diagnostic_context = diagnostic_context or {}


class SlurmProtocolError(ExternalServiceError):
    """Raised when Slurm returns malformed or unsupported data."""

    def __init__(self, message: str, *, diagnostic_context: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.diagnostic_context = diagnostic_context or {}
