from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from services.visualization.core.service import VisualizationService
from services.visualization.rest_api.routes import create_router


def create_app(visualization: VisualizationService) -> FastAPI:
    app = FastAPI(title="RTMF Visualization Service")

    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    files_dir = frontend_dir / "files"
    if files_dir.is_dir():
        app.mount("/files", StaticFiles(directory=str(files_dir)), name="files")

    app.include_router(create_router(visualization=visualization))

    @app.get("/", include_in_schema=False, response_class=FileResponse)
    def read_root() -> FileResponse:
        index = frontend_dir / "index.html"
        if index.is_file():
            return FileResponse(str(index))
        return FileResponse(str(frontend_dir / "vs-frontend-testing.html"))

    @app.get("/api-testing-frontend", response_class=FileResponse)
    def frontend_test() -> FileResponse:
        testing = frontend_dir / "vs-frontend-testing.html"
        return FileResponse(str(testing))

    return app
