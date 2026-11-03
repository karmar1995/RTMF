from __future__ import annotations

import uvicorn

from services.matrix_generation.composition.build_app import create_container


def main() -> None:
    container = create_container()
    uvicorn.run(
        container.app(),
        host=container.config.rest.host(),
        port=container.config.rest.port.as_int()(),
    )


if __name__ == "__main__":
    main()
