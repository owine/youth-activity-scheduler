"""Readiness checks shared by API and CLI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.db.models import WorkerHeartbeat


@dataclass(frozen=True)
class Readiness:
    db_reachable: bool
    heartbeat_fresh: bool
    heartbeat_age_s: float | None

    @property
    def ready(self) -> bool:
        return self.db_reachable and self.heartbeat_fresh


async def check_readiness(engine: AsyncEngine, staleness_s: int) -> Readiness:
    db_ok = False
    hb_fresh = False
    hb_age: float | None = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
            db_ok = True
            row = (
                await conn.execute(
                    select(WorkerHeartbeat.last_beat).order_by(WorkerHeartbeat.id).limit(1)
                )
            ).first()
            if row is not None and row[0] is not None:
                last = row[0]
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                hb_age = (datetime.now(UTC) - last).total_seconds()
                hb_fresh = hb_age <= staleness_s
    except Exception:
        db_ok = False
    return Readiness(db_reachable=db_ok, heartbeat_fresh=hb_fresh, heartbeat_age_s=hb_age)
