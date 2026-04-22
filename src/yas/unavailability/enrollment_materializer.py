"""Create, update, or remove a source=enrollment block for an enrollment."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Enrollment, Offering, UnavailabilityBlock
from yas.db.models._types import EnrollmentStatus, UnavailabilitySource


async def apply_enrollment_block(session: AsyncSession, enrollment_id: int) -> None:
    enrollment = (
        await session.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
    ).scalar_one()

    existing = (
        await session.execute(
            select(UnavailabilityBlock).where(UnavailabilityBlock.source_enrollment_id == enrollment_id)
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
        session.add(UnavailabilityBlock(
            kid_id=enrollment.kid_id,
            source=UnavailabilitySource.enrollment.value,
            source_enrollment_id=enrollment.id,
            label=f"Enrolled: {offering.name}",
            days_of_week=list(offering.days_of_week or []),
            time_start=offering.time_start,
            time_end=offering.time_end,
            date_start=offering.start_date,
            date_end=offering.end_date,
            active=True,
        ))
    else:
        existing.kid_id = enrollment.kid_id
        existing.label = f"Enrolled: {offering.name}"
        existing.days_of_week = list(offering.days_of_week or [])
        existing.time_start = offering.time_start
        existing.time_end = offering.time_end
        existing.date_start = offering.start_date
        existing.date_end = offering.end_date
        existing.active = True
