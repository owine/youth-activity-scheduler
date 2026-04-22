"""Delete-and-rewrite the source=school unavailability blocks for one kid."""

from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Kid, UnavailabilityBlock
from yas.db.models._types import UnavailabilitySource


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


async def materialize_school_blocks(session: AsyncSession, kid_id: int) -> None:
    """Idempotent rewrite of all source=school blocks for this kid."""
    kid = (await session.execute(select(Kid).where(Kid.id == kid_id))).scalar_one()

    await session.execute(
        delete(UnavailabilityBlock).where(
            UnavailabilityBlock.kid_id == kid_id,
            UnavailabilityBlock.source == UnavailabilitySource.school.value,
        )
    )

    if kid.school_time_start is None or kid.school_time_end is None:
        return
    if not kid.school_year_ranges:
        return

    weekdays = kid.school_weekdays or ["mon", "tue", "wed", "thu", "fri"]
    for entry in kid.school_year_ranges:
        start = _parse_date(entry["start"])
        end = _parse_date(entry["end"])
        session.add(
            UnavailabilityBlock(
                kid_id=kid_id,
                source=UnavailabilitySource.school.value,
                label=f"School {start.isoformat()}..{end.isoformat()}",
                days_of_week=weekdays,
                time_start=kid.school_time_start,
                time_end=kid.school_time_end,
                date_start=start,
                date_end=end,
                active=True,
            )
        )
