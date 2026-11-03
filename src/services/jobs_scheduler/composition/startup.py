from __future__ import annotations

import uvicorn

from services.jobs_scheduler.composition.root import create_container
from services.use_case.infra.logging import setup_logging


def create_app_for_uvicorn():
    return create_container().app()


def main() -> None:
    setup_logging()
    container = create_container()
    settings = container.settings()
    if settings.rest.reload:
        uvicorn.run(
            "services.jobs_scheduler.composition.startup:create_app_for_uvicorn",
            host=settings.rest.host,
            port=settings.rest.port,
            reload=True,
            factory=True,
        )
        return
    uvicorn.run(container.app(), host=settings.rest.host, port=settings.rest.port)


if __name__ == "__main__":
    main()
