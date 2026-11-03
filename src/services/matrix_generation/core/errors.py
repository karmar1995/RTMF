class MatrixGenerationError(Exception):
    """Base error for matrix generation service failures."""


class InvalidMatrixGenerationRequest(MatrixGenerationError):
    """Raised when an incoming matrix generation request is invalid."""


class MatrixUploadFailed(MatrixGenerationError):
    """Raised when a generated matrix file cannot be uploaded."""


class SensitivityAnalysisGenerationFailed(MatrixGenerationError):
    """Raised when sensitivity analysis matrix generation fails."""


class LinearCombinationsGenerationNotImplemented(MatrixGenerationError):
    """Raised when linear combinations generation is not implemented."""


class SensitivityAnalysisGenerationNotImplemented(MatrixGenerationError):
    """Raised when sensitivity analysis generation is not implemented."""


class SatelliCombinationsGenerationFailed(MatrixGenerationError):
    """Raised when Satelli matrix combination generation fails."""
