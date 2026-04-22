"""Structured logging via structlog → stderr JSON."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog to emit JSON to stderr at the given level."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Reset any prior handlers (idempotent for tests).
    for existing in list(logging.root.handlers):
        logging.root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(numeric_level)
    logging.root.addHandler(handler)
    logging.root.setLevel(numeric_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        # Caching bound loggers pins the first-seen filter level, so a later
        # reconfigure_logging() call (notably between tests) would silently
        # keep the old level. Overhead of disabling the cache is negligible.
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
