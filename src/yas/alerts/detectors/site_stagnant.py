"""Detector: sites whose most-recent offering has not changed in N days."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Offering, Site


async def detect_stagnant_sites(
    session: AsyncSession,
    threshold_days: int = 30,
    *,
    now: datetime | None = None,
) -> list[int]:
    now_val = now if now is not None else datetime.now(UTC)
    threshold = now_val - timedelta(days=threshold_days)

    stmt = (
        select(Site.id)
        .join(Offering, Offering.site_id == Site.id)
        .where(Site.active.is_(True))
        .where((Site.muted_until.is_(None)) | (Site.muted_until < now_val))
        .group_by(Site.id)
        .having(func.max(Offering.first_seen) < threshold)
        .order_by(Site.id)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)
