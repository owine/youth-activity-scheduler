"""Daily sweep: re-match all active kids at a configured UTC time.

Catches date-based shifts (birthdays crossing today for offerings with no
start_date, school-year-range boundaries, freshness-signal decay) that
aren't covered by event-driven rematch hooks."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings
from yas.db.models import Kid
from yas.db.session import session_scope
from yas.logging import get_logger
from yas.matching.matcher import rematch_kid
from yas.worker.loop_guard import loop_iteration

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
                # Marked before the run, so a failed sweep is reported once and
                # retried tomorrow rather than every 60s. It only catches date
                # drift the event-driven rematches miss, so a day's delay costs
                # little, while a deterministic failure re-run every minute would
                # flood GlitchTip. A restart still re-runs it (last_run is in memory).
                last_run = today
                with loop_iteration("sweep"):
                    kids = await _sweep(engine)
                    log.info("sweep.ran", kids=kids)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        log.info("sweep.stop")
        raise


async def _sweep(engine: AsyncEngine) -> int:
    """Re-match every active kid, one transaction per kid; returns the kid count."""
    async with session_scope(engine) as s:
        kid_ids = list((await s.execute(select(Kid.id).where(Kid.active.is_(True)))).scalars())
    for kid_id in kid_ids:
        # A kid's pass writes a match row per offering, and flushed writes hold
        # SQLite's only write lock until commit. One transaction for every kid
        # held it for the whole sweep, so the heartbeat and API writes timed out.
        async with session_scope(engine) as s:
            await rematch_kid(s, kid_id)
    return len(kid_ids)
