from __future__ import annotations

import argparse
from typing import Sequence

from services.front.composition.build_front_app import build_front_app, load_front_config
from services.use_case import setup_logging


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the RTMF frontend service.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable Flask debug/reloader for this process.",
    )
    parser.add_argument("--host", help="Override services.front.rest.host.")
    parser.add_argument("--port", type=int, help="Override services.front.rest.port.")
    args = parser.parse_args(argv)

    setup_logging()
    config = load_front_config()
    app = build_front_app(front_config=config)
    app.run(
        host=args.host or config.rest.host(),
        port=args.port or config.rest.port.as_int()(),
        debug=args.debug or config.rest.debug.as_(_as_bool)(),
    )


if __name__ == "__main__":
    main()
