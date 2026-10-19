"""Structured logging via structlog → stderr JSON."""

from __future__ import annotations

import logging
import sys
import traceback
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


_TRACEBACK_LIMIT = 2000
_TRUNCATED_MARKER = "[truncated]\n"


def traceback_tail(exc: BaseException) -> str:
    """Format ``exc``'s traceback for a log field, in at most 2000 chars.

    Over the limit the *end* is kept: a traceback prints its innermost frame and
    the line naming the exception last, and in a chained traceback the exception
    being reported comes after all of its context. A head slice drops exactly
    those lines.

    The reported exception's own lines get at most half the budget, keeping
    their start, so a huge message can't crowd out the frame that raised it.
    SQLAlchemy errors embed statement parameters in ``str(exc)``, so this does
    happen. Every caller logs the full message separately as ``error``.
    """
    te = traceback.TracebackException.from_exception(exc, compact=True)
    tb = "".join(te.format())
    if len(tb) <= _TRACEBACK_LIMIT:
        return tb
    final = "".join(te.format_exception_only())
    if not tb.endswith(final):
        # An ExceptionGroup prints its members after its own lines.
        return _TRUNCATED_MARKER + tb[len(tb) - (_TRACEBACK_LIMIT - len(_TRUNCATED_MARKER)) :]
    frames = tb[: len(tb) - len(final)]
    budget = _TRACEBACK_LIMIT // 2
    if len(final) > budget:
        final = final[: budget - 2] + "…\n"
    keep = _TRACEBACK_LIMIT - len(_TRUNCATED_MARKER) - len(final)
    return _TRUNCATED_MARKER + frames[len(frames) - keep :] + final
