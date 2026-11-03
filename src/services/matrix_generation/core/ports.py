from __future__ import annotations

from typing import Protocol

from services.matrix_generation.core.dto import (
    GenerateLinearCombinationsRequest,
    GenerateSensitivityAnalysisRequest,
    GeneratedMatrixFile,
    UploadMatrixRequest,
    UploadResult
)


class MatrixGenerationPort(Protocol):
    def generate_linear_combinations(
        self,
        request: GenerateLinearCombinationsRequest,
    ) -> GeneratedMatrixFile:
        """Generate a matrix file from linear-combination parameters."""

    def generate_sensitivity_analysis(
        self,
        request: GenerateSensitivityAnalysisRequest,
    ) -> GeneratedMatrixFile:
        """Generate a matrix file from sensitivity-analysis parameters."""

    def generate_satelli_matrix_combinations(
        self,
        request: GenerateLinearCombinationsRequest,
    ) -> GeneratedMatrixFile:
        """Generate a Sobol/Satelli matrix from parameter combinations."""

    def upload_matrix(
        self,
        request: UploadMatrixRequest,
    ) -> GeneratedMatrixFile:
        """Upload a raw matrix text and return the stored matrix URL."""


class MatrixUploader(Protocol):
    def upload_text(
        self,
        *,
        bucket: str,
        key: str,
        content: str,
        content_type: str = "text/plain",
    ) -> UploadResult:
        ...
