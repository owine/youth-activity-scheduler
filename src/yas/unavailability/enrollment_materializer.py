"""Create, update, or remove a source=enrollment block for an enrollment."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Enrollment, Offering, UnavailabilityBlock
from yas.db.models._types import EnrollmentStatus, UnavailabilitySource


def attended_days(enrollment: Enrollment, offering: Offering) -> list[str]:
    """The weekdays a kid actually attends an enrolled offering.

    The enrollment's chosen days when it has any (a pick-one-day program,
    #636), limited to days the offering still lists; otherwise every day the
    offering lists. A crawl can move a slot off the chosen day, and blocking a
    day with no class would be wrong, so a choice the offering no longer
    offers falls back to the offering's days.
    """
    listed = list(offering.days_of_week or [])
    chosen = list(enrollment.days_of_week or [])
    if not chosen:
        return listed
    if not listed:
        return chosen
    kept = [d for d in chosen if d in listed]
    return kept or listed


async def apply_enrollment_block(session: AsyncSession, enrollment_id: int) -> None:
    enrollment = (
        await session.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
    ).scalar_one()

    existing = (
        await session.execute(
            select(UnavailabilityBlock).where(
                UnavailabilityBlock.source_enrollment_id == enrollment_id
            )
        )
    ).scalar_one_or_none()

    status = getattr(enrollment.status, "value", enrollment.status)
    if status != EnrollmentStatus.enrolled.value:
        if existing is not None:
            await session.delete(existing)
        return

    offering = (
        await session.execute(select(Offering).where(Offering.id == enrollment.offering_id))
    ).scalar_one()

    if existing is None:
        session.add(
            UnavailabilityBlock(
                kid_id=enrollment.kid_id,
                source=UnavailabilitySource.enrollment.value,
                source_enrollment_id=enrollment.id,
                label=f"Enrolled: {offering.name}",
                days_of_week=attended_days(enrollment, offering),
                time_start=offering.time_start,
                time_end=offering.time_end,
                date_start=offering.start_date,
                date_end=offering.end_date,
                active=True,
            )
        )
    else:
        existing.kid_id = enrollment.kid_id
        existing.label = f"Enrolled: {offering.name}"
        existing.days_of_week = attended_days(enrollment, offering)
        existing.time_start = offering.time_start
        existing.time_end = offering.time_end
        existing.date_start = offering.start_date
        existing.date_end = offering.end_date
        existing.active = True
