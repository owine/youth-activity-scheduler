"""Detector: kids who have been active long enough but have zero matches ever."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Kid, Match


async def detect_kids_without_matches(
    session: AsyncSession,
    threshold_days: int = 7,
    *,
    now: datetime | None = None,
) -> list[int]:
    now_val = now if now is not None else datetime.now(UTC)
    threshold = now_val - timedelta(days=threshold_days)

    match_exists = select(Match.kid_id).where(Match.kid_id == Kid.id).exists()

    stmt = (
        select(Kid.id)
        .where(Kid.active.is_(True))
        .where(Kid.created_at <= threshold)
        .where(~match_exists)
        .order_by(Kid.id)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)
