from __future__ import annotations

from fastapi import FastAPI

from services.matrix_generation.core.ports import MatrixGenerationPort
from services.matrix_generation.rest_api.routes import create_router


def create_app(matrix_generation: MatrixGenerationPort) -> FastAPI:
    app = FastAPI(title="RTMF Matrix Generation Service")
    app.include_router(create_router(matrix_generation=matrix_generation))
    return app
