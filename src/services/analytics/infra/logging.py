"""Minimal logging configuration helpers."""

import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Configure basic logging for local execution."""
    logging.basicConfig(level=level)
    # TODO: Replace with structured logging configuration when runtime needs are clear.
