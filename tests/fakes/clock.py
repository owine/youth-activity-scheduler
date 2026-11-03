"""A scripted clock and sleep for driving a daily worker loop tick by tick."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, tzinfo
from types import ModuleType

import pytest


class StopLoop(Exception):
    """Raised by a scripted sleep to end the loop after its last tick."""


def scripted_clock(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, readings: list[datetime]
) -> Callable[[float], Awaitable[None]]:
    """Drive ``module``'s loop through ``readings``, one clock reading per tick.

    The loop reads ``datetime.now`` from its own module, so that name is
    swapped for a subclass whose ``now`` returns the current reading. The
    returned sleep advances to the next reading, then raises ``StopLoop`` once
    they run out, so one loop invocation runs ``len(readings)`` ticks and keeps
    its in-memory ``last_run`` across them.
    """
    remaining = list(readings)
    current = [remaining.pop(0)]

    class _Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
            return current[0]

    monkeypatch.setattr(module, "datetime", _Clock)

    async def _sleep(_seconds: float) -> None:
        if not remaining:
            raise StopLoop
        current[0] = remaining.pop(0)

    return _sleep
