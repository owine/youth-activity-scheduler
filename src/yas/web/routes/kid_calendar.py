"""GET /api/kids/{kid_id}/calendar — aggregated per-kid event view."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.calendar.occurrences import expand_recurring
from yas.db.models import Enrollment, Kid, Match, Offering, Site, UnavailabilityBlock
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

    now = datetime.now(UTC)

    async with session_scope(_engine(request)) as s:
        kid = (await s.execute(select(Kid).where(Kid.id == kid_id))).scalar_one_or_none()
        if kid is None:
            raise HTTPException(status_code=404, detail=f"kid {kid_id} not found")

        events: list[CalendarEventOut] = []

        # School holidays: dates the matcher already skips for conflict checks.
        # Used here to (a) hide school recurring blocks on those dates, and
        # (b) emit explicit "Holiday" events for the same dates within the
        # school-year ranges so the calendar isn't silently empty.
        school_holiday_dates: set[date] = set()
        for s_iso in kid.school_holidays or []:
            try:
                school_holiday_dates.add(date.fromisoformat(s_iso))
            except ValueError:
                continue
        school_year_ranges_parsed: list[tuple[date, date]] = []
        for entry in kid.school_year_ranges or []:
            try:
                school_year_ranges_parsed.append(
                    (date.fromisoformat(entry["start"]), date.fromisoformat(entry["end"]))
                )
            except KeyError, ValueError:
                continue

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
                # School blocks: hide on holiday dates. Other blocks unchanged.
                if block.source == "school" and occ.date in school_holiday_dates:
                    continue
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

        # Emit explicit Holiday events for holiday dates that fall in range
        # AND inside at least one school_year_range (closed interval). A
        # holiday outside the school year would imply school is being
        # cancelled on a day that's already free, which is misleading.
        for h in sorted(school_holiday_dates):
            if h < from_ or h > to:
                continue
            in_school_year = any(start <= h <= end for start, end in school_year_ranges_parsed)
            if not in_school_year:
                continue
            events.append(
                CalendarEventOut(
                    id=f"holiday:{kid_id}:{h.isoformat()}",
                    kind="holiday",
                    date=h,
                    time_start=None,
                    time_end=None,
                    all_day=True,
                    title="Holiday",
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
                    .join(Site, Site.id == Offering.site_id)
                    .where(Match.kid_id == kid_id)
                    .where(Match.score >= _MATCH_THRESHOLD)
                    .where(~Match.offering_id.in_(committed_offering_ids))
                    .where(or_(Offering.muted_until.is_(None), Offering.muted_until <= now))
                    .where(or_(Site.muted_until.is_(None), Site.muted_until <= now))
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
