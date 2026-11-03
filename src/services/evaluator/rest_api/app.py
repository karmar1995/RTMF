from __future__ import annotations

from fastapi import FastAPI

from services.evaluator.core.ports import EvaluatorPort
from services.evaluator.rest_api.routes import create_router


def create_app(port: EvaluatorPort) -> FastAPI:
    app = FastAPI(title="RTMF Evaluator Service")
    app.include_router(create_router(port))
    return app
