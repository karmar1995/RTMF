from __future__ import annotations

import sys
from typing import Sequence

from services.job_executor.composition.container import Container
from services.job_executor.composition.root import create_container, describe_executor_identity
from services.job_executor.front import cli


def main(argv: Sequence[str] | None = None, container: Container | None = None) -> int:
    try:
        request = cli.parse_request(argv)
        container = container or create_container()
        print(describe_executor_identity(container), file=sys.stderr)
        executor = container.executor()
        result = executor(request)
        print(result.job_id)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(cli.render_error(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
