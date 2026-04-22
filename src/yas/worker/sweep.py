"""Daily sweep: re-match all active kids at a configured UTC time.

Catches date-based shifts (birthdays crossing today for offerings with no
start_date, school-year-range boundaries, freshness-signal decay) that
aren't covered by event-driven rematch hooks."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings
from yas.db.session import session_scope
from yas.logging import get_logger
from yas.matching.matcher import rematch_all_active_kids

log = get_logger("yas.worker.sweep")


def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


async def daily_sweep_loop(engine: AsyncEngine, settings: Settings) -> None:
    """Every 60s check whether it's past the configured sweep time for today,
    and if so, re-match all active kids. Idempotent across worker restarts:
    at most one double-run (harmless) or one skip (next day covers)."""
    target = _parse_hhmm(settings.sweep_time_utc)
    last_run: date | None = None
    log.info("sweep.start", time_utc=settings.sweep_time_utc)
    try:
        while True:
            now = datetime.now(UTC)
            today = now.date()
            if now.time() >= target and last_run != today:
                async with session_scope(engine) as s:
                    results = await rematch_all_active_kids(s)
                log.info("sweep.ran", kids=len(results))
                last_run = today
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        log.info("sweep.stop")
        raise
