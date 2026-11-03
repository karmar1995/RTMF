class EvaluatorError(Exception):
    """Base error for evaluator service failures."""


class EvaluationNotFound(EvaluatorError):
    """Raised when an evaluation ID is not found."""


class EvaluationNotComplete(EvaluatorError):
    """Raised when evaluation results are requested but not yet complete."""


class EvaluationFailed(EvaluatorError):
    """Raised when the evaluation pipeline fails."""
