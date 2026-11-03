#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from run_service_local import main as run_service_local_main  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if any(arg in {"-h", "--help"} for arg in args):
        print(
            "Run the frontend directly from repository source.\n\n"
            "Usage:\n"
            "  scripts/run_front.py [run_service_local options] [-- SERVICE_ARGS...]\n\n"
            "Equivalent to:\n"
            "  scripts/run_service_local.py front\n\n"
            "Docker deployment remains available through:\n"
            "  scripts/deploy_service.sh front\n"
        )
        return 0
    if "--" in args:
        delimiter = args.index("--")
        runner_args = args[:delimiter]
        service_args = args[delimiter + 1 :]
        return run_service_local_main([*runner_args, "front", "--", *service_args])
    return run_service_local_main([*args, "front"])


if __name__ == "__main__":
    raise SystemExit(main())
