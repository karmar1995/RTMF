from __future__ import annotations


class VisualizationError(Exception):
    """Base error for visualization service failures."""


class FutureNotFoundError(VisualizationError):
    """Raised when a requested future/plot ID does not exist."""


class CorruptedZipFile(VisualizationError):
    """Raised when the uploaded ZIP file is corrupted."""


class NotAZipFile(VisualizationError):
    """Raised when the uploaded file is not a valid ZIP archive."""


class DecodeError(VisualizationError):
    """Raised when trait JSON cannot be decoded."""


class BadAggregation(VisualizationError):
    """Raised when an unsupported aggregation type is used."""


class UnknownPlotType(VisualizationError):
    """Raised when the requested plot type is not supported."""
