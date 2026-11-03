from __future__ import annotations

import logging

from fastapi import HTTPException, status

from services.jobs_scheduler.core.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    SlurmAuthenticationError,
    SlurmConfigurationError,
    SlurmProtocolError,
    SlurmTokenUnavailableError,
    SlurmUnavailableError,
    ValidationError,
)

logger = logging.getLogger(__name__)


def to_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, ValidationError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        )
    if isinstance(error, NotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        )
    if isinstance(error, SlurmTokenUnavailableError):
        logger.warning(
            "Jobs scheduler Slurm token unavailable: %s context=%s",
            error,
            _diagnostic_context(error),
        )
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Slurm scheduler authentication is temporarily unavailable.",
        )
    if isinstance(error, SlurmUnavailableError):
        logger.warning(
            "Jobs scheduler dependency unavailable: %s context=%s",
            error,
            _diagnostic_context(error),
        )
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Slurm scheduler is temporarily unavailable.",
        )
    if isinstance(error, SlurmAuthenticationError):
        logger.warning(
            "Jobs scheduler Slurm authentication failure: %s context=%s",
            error,
            _diagnostic_context(error),
        )
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Slurm scheduler authentication is temporarily unavailable.",
        )
    if isinstance(error, SlurmConfigurationError):
        logger.exception(
            "Jobs scheduler Slurm configuration failure: %s context=%s",
            error,
            _diagnostic_context(error),
        )
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Jobs scheduler Slurm configuration is invalid.",
        )
    if isinstance(error, SlurmProtocolError):
        logger.warning(
            "Jobs scheduler Slurm protocol failure: %s context=%s",
            error,
            _diagnostic_context(error),
        )
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Slurm scheduler returned an invalid response.",
        )
    if isinstance(error, AuthenticationError):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        )
    if isinstance(error, ExternalServiceError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        )
    logger.exception("Unexpected jobs scheduler request failure")
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Internal server error.",
    )


def _diagnostic_context(error: Exception) -> dict[str, object]:
    context = getattr(error, "diagnostic_context", {})
    if isinstance(context, dict):
        return context
    return {}
