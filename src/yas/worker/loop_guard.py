"""Keep one failed iteration of a background loop from ending the loop, but not
a persistent fault.

Every worker loop runs in `run_worker`'s TaskGroup, and in `all` mode that
TaskGroup is a sibling of uvicorn's, so an exception escaping any loop cancels
the API and exits the process. A loop wraps each unit of work in
`LoopGuard.iteration()` instead: a failure is logged and the loop carries on to
its next unit.

A fault that doesn't clear (a wedged pool, a read-only or full disk) would then
fail every tick forever behind a healthy-looking API. So after
`MAX_CONSECUTIVE_FAILURES` failures in a row the guard re-raises, the TaskGroup
exits the process, and `restart: unless-stopped` restarts the container, which
is the recovery the process model relies on. A success resets the count.

GlitchTip hears about the first failure of a streak (and, via the process's
uncaught-exception hook, about giving up), never one event per tick. Cancellation is a BaseException, so it is not caught and
shutdown still works.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import sentry_sdk

from yas.logging import get_logger, traceback_tail

log = get_logger("yas.worker")

# Consecutive failed iterations of one loop before it re-raises and exits the
# process. At a 60s tick this is ~5 minutes of failing before a restart.
MAX_CONSECUTIVE_FAILURES = 5


class LoopGuard:
    """Per-loop failure tracking; create one per loop, outside its `while`."""

    def __init__(self, loop: str, *, max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES):
        self.loop = loop
        self.max_consecutive_failures = max_consecutive_failures
        self.consecutive_failures = 0

    @contextmanager
    def iteration(self, **tags: str | int) -> Iterator[None]:
        """Run one unit of work, absorbing an Exception unless it ends the streak.

        `tags` (e.g. kid_id) go on the log line and the GlitchTip event. Ids
        only, never names or addresses."""
        try:
            yield
        except Exception as exc:
            self.consecutive_failures += 1
            giving_up = self.consecutive_failures >= self.max_consecutive_failures
            log.error(
                "worker.loop_iteration_failed",
                loop=self.loop,
                consecutive_failures=self.consecutive_failures,
                giving_up=giving_up,
                error_type=type(exc).__name__,
                error=str(exc),
                traceback=traceback_tail(exc),
                **tags,
            )
            # structlog never reaches stdlib logging, so the log line alone doesn't
            # page. Only a streak's first failure is reported, not one event per
            # tick; giving up exits the process, which the uncaught-exception hook
            # reports. So a persistent fault costs two events per process lifetime.
            if self.consecutive_failures == 1:
                sentry_sdk.capture_exception(
                    exc, tags={"loop": self.loop, **{k: str(v) for k, v in tags.items()}}
                )
            if giving_up:
                raise
        else:
            if self.consecutive_failures:
                log.info(
                    "worker.loop_recovered",
                    loop=self.loop,
                    after_failures=self.consecutive_failures,
                )
            self.consecutive_failures = 0
