"""GET /api/kids/{kid_id}/calendar — aggregated per-kid event view."""

from __future__ import annotations

from datetime import date, time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.calendar.occurrences import expand_recurring
from yas.db.models import Enrollment, Kid, Match, Offering, UnavailabilityBlock
from yas.db.models._types import EnrollmentStatus
from yas.db.session import session_scope
from yas.web.routes.kid_calendar_schemas import CalendarEventOut, KidCalendarOut

router = APIRouter(prefix="/api/kids", tags=["kids"])

_MAX_RANGE_DAYS = 90
_MATCH_THRESHOLD: float = 0.6


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


@router.get("/{kid_id}/calendar", response_model=KidCalendarOut, response_model_by_alias=True)
async def get_kid_calendar(
    request: Request,
    kid_id: int,
    from_: Annotated[date, Query(alias="from")],
    to: Annotated[date, Query()],
    include_matches: Annotated[bool, Query()] = False,
) -> KidCalendarOut:
    if from_ >= to:
        raise HTTPException(status_code=422, detail="from must be before to")
    if (to - from_).days > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"range exceeds {_MAX_RANGE_DAYS}-day cap",
        )

    async with session_scope(_engine(request)) as s:
        kid = (await s.execute(select(Kid).where(Kid.id == kid_id))).scalar_one_or_none()
        if kid is None:
            raise HTTPException(status_code=404, detail=f"kid {kid_id} not found")

        events: list[CalendarEventOut] = []

        enrollment_rows = (
            await s.execute(
                select(Enrollment, Offering)
                .join(Offering, Offering.id == Enrollment.offering_id)
                .where(Enrollment.kid_id == kid_id)
                .where(Enrollment.status == EnrollmentStatus.enrolled.value)
            )
        ).all()
        for enrollment, offering in enrollment_rows:
            for occ in expand_recurring(
                days_of_week=list(offering.days_of_week or []),
                time_start=offering.time_start,
                time_end=offering.time_end,
                date_start=offering.start_date,
                date_end=offering.end_date,
                range_from=from_,
                range_to=to,
            ):
                events.append(
                    CalendarEventOut(
                        id=f"enrollment:{enrollment.id}:{occ.date.isoformat()}",
                        kind="enrollment",
                        date=occ.date,
                        time_start=occ.time_start,
                        time_end=occ.time_end,
                        all_day=occ.all_day,
                        title=offering.name,
                        enrollment_id=enrollment.id,
                        offering_id=offering.id,
                        location_id=offering.location_id,
                        status=enrollment.status,
                    )
                )

        block_rows = (
            (
                await s.execute(
                    select(UnavailabilityBlock)
                    .where(UnavailabilityBlock.kid_id == kid_id)
                    .where(UnavailabilityBlock.active.is_(True))
                )
            )
            .scalars()
            .all()
        )
        for block in block_rows:
            for occ in expand_recurring(
                days_of_week=list(block.days_of_week or []),
                time_start=block.time_start,
                time_end=block.time_end,
                date_start=block.date_start,
                date_end=block.date_end,
                range_from=from_,
                range_to=to,
            ):
                events.append(
                    CalendarEventOut(
                        id=f"unavailability:{block.id}:{occ.date.isoformat()}",
                        kind="unavailability",
                        date=occ.date,
                        time_start=occ.time_start,
                        time_end=occ.time_end,
                        all_day=occ.all_day,
                        title=block.label or block.source,
                        block_id=block.id,
                        source=block.source,
                        from_enrollment_id=block.source_enrollment_id,
                    )
                )

        # 3. Match overlay (opt-in).
        if include_matches:
            committed_offering_ids = (
                select(Enrollment.offering_id)
                .where(Enrollment.kid_id == kid_id)
                .where(Enrollment.status != EnrollmentStatus.cancelled.value)
            )
            match_rows = (
                await s.execute(
                    select(Match, Offering)
                    .join(Offering, Offering.id == Match.offering_id)
                    .where(Match.kid_id == kid_id)
                    .where(Match.score >= _MATCH_THRESHOLD)
                    .where(~Match.offering_id.in_(committed_offering_ids))
                )
            ).all()
            for match, offering in match_rows:
                for occ in expand_recurring(
                    days_of_week=list(offering.days_of_week or []),
                    time_start=offering.time_start,
                    time_end=offering.time_end,
                    date_start=offering.start_date,
                    date_end=offering.end_date,
                    range_from=from_,
                    range_to=to,
                ):
                    events.append(
                        CalendarEventOut(
                            id=f"match:{offering.id}:{occ.date.isoformat()}",
                            kind="match",
                            date=occ.date,
                            time_start=occ.time_start,
                            time_end=occ.time_end,
                            all_day=occ.all_day,
                            title=offering.name,
                            offering_id=offering.id,
                            location_id=offering.location_id,
                            score=match.score,
                            registration_url=offering.registration_url,
                        )
                    )

        # Sort by (date, time_start). time_start is `time | None`; coerce
        # all-day events to `time.min` so we always compare time-to-time.
        # Mixing `time` and `str` in the sort key crashes at runtime when
        # both an all-day and a timed event fall on the same date.
        events.sort(key=lambda e: (e.date, e.time_start or time.min))
        return KidCalendarOut(kid_id=kid_id, from_=from_, to=to, events=events)
