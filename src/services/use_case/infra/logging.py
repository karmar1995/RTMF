from __future__ import annotations

import logging
from typing import Any


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def log_error(message: str, *args: Any, **kwargs: Any) -> None:
    logging.getLogger(__name__).error(message, *args, **kwargs)


def log_warning(message: str, *args: Any, **kwargs: Any) -> None:
    logging.getLogger(__name__).warning(message, *args, **kwargs)


def log_info(message: str, *args: Any, **kwargs: Any) -> None:
    logging.getLogger(__name__).info(message, *args, **kwargs)


def log_debug(message: str, *args: Any, **kwargs: Any) -> None:
    logging.getLogger(__name__).debug(message, *args, **kwargs)
