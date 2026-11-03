from __future__ import annotations

from fastapi import FastAPI

from services.matrix_generation.core.ports import MatrixGenerationPort
from services.matrix_generation.rest_api.app import create_app


def build_rest_app(matrix_generation: MatrixGenerationPort) -> FastAPI:
    return create_app(matrix_generation=matrix_generation)
