"""Keep one failed iteration of a background loop from ending the loop.

Every worker loop runs in `run_worker`'s TaskGroup, and in `all` mode that
TaskGroup is a sibling of uvicorn's, so an exception escaping any loop cancels
the API and exits the process. A loop body wraps each iteration in
`loop_iteration` instead: the failure is logged, reported to GlitchTip, and the
loop carries on to its next sleep. Cancellation is a BaseException, so it is not
caught and shutdown still works.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import sentry_sdk

from yas.logging import get_logger, traceback_tail

log = get_logger("yas.worker")


@contextmanager
def loop_iteration(loop: str) -> Iterator[None]:
    """Run one iteration of the loop named `loop`, absorbing any Exception."""
    try:
        yield
    except Exception as exc:
        log.error(
            "worker.loop_iteration_failed",
            loop=loop,
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback_tail(exc),
        )
        # structlog never reaches stdlib logging, so the log line alone doesn't page.
        sentry_sdk.capture_exception(exc, tags={"loop": loop})
