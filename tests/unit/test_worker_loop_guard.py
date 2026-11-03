"""`loop_iteration` keeps one failed iteration of a worker loop from killing the
process. In `all` mode the worker shares a TaskGroup with uvicorn, so any
exception escaping a loop cancels the API too."""

from __future__ import annotations

import asyncio

import pytest
import structlog.testing

from yas.worker.loop_guard import loop_iteration


def _boom() -> None:
    raise RuntimeError("iteration exploded")


def test_failed_iteration_is_logged_and_swallowed() -> None:
    with structlog.testing.capture_logs() as logs, loop_iteration("sweep"):
        _boom()
    [entry] = [e for e in logs if e["event"] == "worker.loop_iteration_failed"]
    assert entry["loop"] == "sweep"
    assert entry["log_level"] == "error"
    assert entry["error_type"] == "RuntimeError"
    assert entry["error"] == "iteration exploded"
    assert "_boom" in entry["traceback"]


def test_failed_iteration_reports_to_sentry(sentry_events) -> None:  # type: ignore[no-untyped-def]
    with loop_iteration("delivery"):
        _boom()
    [event] = sentry_events
    [exc] = event["exception"]["values"]
    assert exc["type"] == "RuntimeError"
    assert event["tags"]["loop"] == "delivery"


def test_successful_iteration_is_silent(sentry_events) -> None:  # type: ignore[no-untyped-def]
    with structlog.testing.capture_logs() as logs, loop_iteration("sweep"):
        pass
    assert logs == []
    assert sentry_events == []


def test_cancellation_propagates(sentry_events) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(asyncio.CancelledError), loop_iteration("sweep"):
        raise asyncio.CancelledError
    assert sentry_events == []
