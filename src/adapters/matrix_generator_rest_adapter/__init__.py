"""Client-side REST adapter for the external Matrix Generation Service.

Example:
    from adapters.matrix_generator_rest_adapter import MatrixGeneratorRestAdapter

    matrix_generator = MatrixGeneratorRestAdapter(
        base_url="http://localhost:8000",
        timeout_seconds=30,
    )

    result = matrix_generator.generate_linear_combinations(
        matrix_id="abc123",
        repetitions=100,
        parameter_definitions=[],
        fixed_params={},
        sweep_params={},
    )

    print(result.matrix_url)
"""

from adapters.matrix_generator_rest_adapter.matrix_generator_rest_adapter import (
    MatrixGeneratorAdapterError,
    MatrixGeneratorInvalidResponse,
    MatrixGeneratorRestAdapter,
    MatrixGeneratorServiceUnavailable,
)
from adapters.matrix_generator_rest_adapter.config import MatrixGeneratorAdapterConfig

__all__ = [
    "MatrixGeneratorAdapterConfig",
    "MatrixGeneratorAdapterError",
    "MatrixGeneratorInvalidResponse",
    "MatrixGeneratorRestAdapter",
    "MatrixGeneratorServiceUnavailable",
]
