from __future__ import annotations

from fastapi import FastAPI

from services.jobs_scheduler.core.jobs_scheduler_service import JobsSchedulerService
from services.jobs_scheduler.rest_api.routes import create_router


def create_app(controller: JobsSchedulerService) -> FastAPI:
    app = FastAPI(title="RTMF Jobs Scheduler Service")
    app.include_router(create_router(controller))
    return app

