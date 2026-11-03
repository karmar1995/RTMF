from __future__ import annotations

import argparse
import signal
import threading
from typing import Sequence

from services.use_case import setup_logging
from services.use_case.composition.build_usecases import build_usecases


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the in-process use-case composition root. This service does "
            "not expose a standalone transport yet; front currently composes it "
            "in-process."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate use-case composition and exit.",
    )
    args = parser.parse_args(argv)

    setup_logging()
    build_usecases()
    if args.check:
        return 0

    stop_event = threading.Event()

    def stop(_signum, _frame) -> None:
        stop_event.set()

    previous_int = signal.getsignal(signal.SIGINT)
    previous_term = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        print(
            "Use-case composition is running without a standalone transport. "
            "Press Ctrl+C to stop.",
            flush=True,
        )
        stop_event.wait()
        return 0
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    raise SystemExit(main())
