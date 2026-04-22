"""Worker runner — async loop that drives heartbeat and (later) pipeline stages."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings
from yas.logging import get_logger
from yas.worker.heartbeat import beat_once

log = get_logger("yas.worker")


async def run_worker(engine: AsyncEngine, settings: Settings) -> None:
    """Main worker loop. Task 8 implements heartbeat only; later tasks add stages."""
    log.info("worker.start", interval_s=settings.worker_heartbeat_interval_s)
    try:
        while True:
            ts = await beat_once(engine)
            log.debug("worker.heartbeat", ts=ts.isoformat())
            await asyncio.sleep(settings.worker_heartbeat_interval_s)
    except asyncio.CancelledError:
        log.info("worker.stop")
        raise
