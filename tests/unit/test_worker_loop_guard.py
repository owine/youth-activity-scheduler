"""`LoopGuard` keeps one failed iteration of a worker loop from killing the
process, but re-raises once a loop keeps failing so the container restarts. In
`all` mode the worker shares a TaskGroup with uvicorn, so any exception escaping
a loop cancels the API too."""

from __future__ import annotations

import asyncio

import pytest
import structlog.testing

from yas.worker.loop_guard import MAX_CONSECUTIVE_FAILURES, LoopGuard


def _boom() -> None:
    raise RuntimeError("iteration exploded")


def _fail(guard: LoopGuard, n: int) -> None:
    for _ in range(n):
        with guard.iteration():
            _boom()


def test_failed_iteration_is_logged_and_swallowed() -> None:
    with structlog.testing.capture_logs() as logs, LoopGuard("sweep").iteration(kid_id=7):
        _boom()
    [entry] = [e for e in logs if e["event"] == "worker.loop_iteration_failed"]
    assert entry["loop"] == "sweep"
    assert entry["log_level"] == "error"
    assert entry["error_type"] == "RuntimeError"
    assert entry["error"] == "iteration exploded"
    assert entry["consecutive_failures"] == 1
    assert entry["kid_id"] == 7
    assert "_boom" in entry["traceback"]


def test_failed_iteration_reports_to_sentry(sentry_events) -> None:  # type: ignore[no-untyped-def]
    with LoopGuard("delivery").iteration(kid_id=3):
        _boom()
    [event] = sentry_events
    [exc] = event["exception"]["values"]
    assert exc["type"] == "RuntimeError"
    assert event["tags"]["loop"] == "delivery"
    assert event["tags"]["kid_id"] == "3"


def test_successful_iteration_is_silent(sentry_events) -> None:  # type: ignore[no-untyped-def]
    with structlog.testing.capture_logs() as logs, LoopGuard("sweep").iteration():
        pass
    assert logs == []
    assert sentry_events == []


def test_cancellation_propagates(sentry_events) -> None:  # type: ignore[no-untyped-def]
    guard = LoopGuard("sweep")
    with pytest.raises(asyncio.CancelledError), guard.iteration():
        raise asyncio.CancelledError
    assert sentry_events == []
    assert guard.consecutive_failures == 0


def test_reraises_after_consecutive_failure_limit() -> None:
    """A fault that doesn't clear must exit the process so the container restarts,
    rather than fail every tick forever behind a healthy-looking API."""
    guard = LoopGuard("crawl_scheduler")
    _fail(guard, MAX_CONSECUTIVE_FAILURES - 1)
    with pytest.raises(RuntimeError, match="iteration exploded"), guard.iteration():
        _boom()


def test_success_resets_the_failure_count() -> None:
    guard = LoopGuard("crawl_scheduler")
    _fail(guard, MAX_CONSECUTIVE_FAILURES - 1)
    with structlog.testing.capture_logs() as logs, guard.iteration():
        pass
    assert guard.consecutive_failures == 0
    assert [e["event"] for e in logs] == ["worker.loop_recovered"]
    # A fresh streak gets the full allowance again.
    _fail(guard, MAX_CONSECUTIVE_FAILURES - 1)
    with pytest.raises(RuntimeError), guard.iteration():
        _boom()


def test_streak_reports_only_its_first_failure(sentry_events) -> None:  # type: ignore[no-untyped-def]
    """A persistent fault must not page once per tick. Giving up is reported by
    the uncaught-exception hook when the process exits, not here."""
    guard = LoopGuard("alert_delivery")
    _fail(guard, MAX_CONSECUTIVE_FAILURES - 1)
    with pytest.raises(RuntimeError), guard.iteration():
        _boom()
    assert len(sentry_events) == 1


def test_new_streak_after_recovery_reports_again(sentry_events) -> None:  # type: ignore[no-untyped-def]
    guard = LoopGuard("alert_delivery")
    _fail(guard, 2)
    with guard.iteration():
        pass
    _fail(guard, 2)
    assert len(sentry_events) == 2


def test_loops_are_counted_separately() -> None:
    a, b = LoopGuard("a"), LoopGuard("b")
    _fail(a, MAX_CONSECUTIVE_FAILURES - 1)
    _fail(b, MAX_CONSECUTIVE_FAILURES - 1)
    assert a.consecutive_failures == b.consecutive_failures == MAX_CONSECUTIVE_FAILURES - 1
