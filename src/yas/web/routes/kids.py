"""HTTP endpoints for managing kids."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from yas.db.models import (
    Enrollment,
    Kid,
    Match,
    UnavailabilityBlock,
    WatchlistEntry,
)
from yas.db.session import session_scope
from yas.matching.matcher import rematch_kid
from yas.unavailability.school_materializer import materialize_school_blocks
from yas.web.routes.kids_schemas import (
    EnrollmentOut,
    KidCreate,
    KidDetailOut,
    KidOut,
    KidUpdate,
    MatchOut,
    UnavailabilityOut,
    WatchlistOut,
)

router = APIRouter(prefix="/api/kids", tags=["kids"])


_SCHOOL_FIELDS = {
    "school_time_start",
    "school_time_end",
    "school_year_ranges",
    "school_weekdays",
    "school_holidays",
    "availability",
    "interests",
    "max_distance_mi",
    "dob",
}


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


async def _build_detail(session: AsyncSession, kid: Kid) -> KidDetailOut:
    blocks = (
        (await session.execute(
            select(UnavailabilityBlock)
            .where(UnavailabilityBlock.kid_id == kid.id)
            .order_by(UnavailabilityBlock.id)
        )).scalars().all()
    )
    watchlist = (
        (await session.execute(
            select(WatchlistEntry)
            .where(WatchlistEntry.kid_id == kid.id)
            .order_by(WatchlistEntry.id)
        )).scalars().all()
    )
    enrollments = (
        (await session.execute(
            select(Enrollment)
            .where(Enrollment.kid_id == kid.id)
            .order_by(Enrollment.id)
        )).scalars().all()
    )
    matches = (
        (await session.execute(
            select(Match)
            .where(Match.kid_id == kid.id)
            .order_by(Match.score.desc())
            .limit(10)
        )).scalars().all()
    )
    data: dict[str, Any] = {
        "id": kid.id,
        "name": kid.name,
        "dob": kid.dob,
        "interests": kid.interests or [],
        "availability": kid.availability or {},
        "max_distance_mi": kid.max_distance_mi,
        "alert_score_threshold": kid.alert_score_threshold,
        "alert_on": kid.alert_on or {},
        "school_weekdays": kid.school_weekdays or [],
        "school_time_start": kid.school_time_start,
        "school_time_end": kid.school_time_end,
        "school_year_ranges": kid.school_year_ranges or [],
        "school_holidays": kid.school_holidays or [],
        "notes": kid.notes,
        "active": kid.active,
        "unavailability": [UnavailabilityOut.model_validate(b) for b in blocks],
        "watchlist": [WatchlistOut.model_validate(w) for w in watchlist],
        "enrollments": [EnrollmentOut.model_validate(e) for e in enrollments],
        "matches": [MatchOut.model_validate(m) for m in matches],
    }
    return KidDetailOut.model_validate(data)


@router.post("", response_model=KidDetailOut, status_code=status.HTTP_201_CREATED)
async def create_kid(payload: KidCreate, request: Request) -> KidDetailOut:
    async with session_scope(_engine(request)) as s:
        kid = Kid(
            name=payload.name,
            dob=payload.dob,
            interests=payload.interests,
            availability=payload.availability,
            max_distance_mi=payload.max_distance_mi,
            alert_score_threshold=payload.alert_score_threshold,
            alert_on=payload.alert_on,
            school_weekdays=payload.school_weekdays,
            school_time_start=payload.school_time_start,
            school_time_end=payload.school_time_end,
            school_year_ranges=payload.school_year_ranges,
            school_holidays=payload.school_holidays,
            notes=payload.notes,
            active=payload.active,
        )
        s.add(kid)
        await s.flush()

        for u in payload.unavailability:
            s.add(UnavailabilityBlock(
                kid_id=kid.id,
                source=u.source,
                label=u.label,
                days_of_week=u.days_of_week,
                time_start=u.time_start,
                time_end=u.time_end,
                date_start=u.date_start,
                date_end=u.date_end,
                active=u.active,
            ))
        for w in payload.watchlist:
            s.add(WatchlistEntry(
                kid_id=kid.id,
                site_id=w.site_id,
                pattern=w.pattern,
                priority=w.priority,
                notes=w.notes,
                active=w.active,
            ))
        await s.flush()

        await materialize_school_blocks(s, kid.id)
        await rematch_kid(s, kid.id)
        await s.flush()
        return await _build_detail(s, kid)


@router.get("", response_model=list[KidOut])
async def list_kids(request: Request) -> list[KidOut]:
    async with session_scope(_engine(request)) as s:
        kids = (await s.execute(select(Kid).order_by(Kid.id))).scalars().all()
        return [KidOut.model_validate(k) for k in kids]


@router.get("/{kid_id}", response_model=KidDetailOut)
async def get_kid(kid_id: int, request: Request) -> KidDetailOut:
    async with session_scope(_engine(request)) as s:
        kid = (await s.execute(select(Kid).where(Kid.id == kid_id))).scalar_one_or_none()
        if kid is None:
            raise HTTPException(status_code=404, detail=f"kid {kid_id} not found")
        return await _build_detail(s, kid)


@router.patch("/{kid_id}", response_model=KidDetailOut)
async def update_kid(kid_id: int, patch: KidUpdate, request: Request) -> KidDetailOut:
    async with session_scope(_engine(request)) as s:
        kid = (await s.execute(select(Kid).where(Kid.id == kid_id))).scalar_one_or_none()
        if kid is None:
            raise HTTPException(status_code=404, detail=f"kid {kid_id} not found")
        data = patch.model_dump(exclude_unset=True)
        changed_keys = set(data.keys())
        for key, value in data.items():
            setattr(kid, key, value)
        await s.flush()

        if changed_keys & _SCHOOL_FIELDS:
            await materialize_school_blocks(s, kid.id)
        await rematch_kid(s, kid.id)
        await s.flush()
        return await _build_detail(s, kid)


@router.delete("/{kid_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kid(kid_id: int, request: Request) -> None:
    async with session_scope(_engine(request)) as s:
        kid = (await s.execute(select(Kid).where(Kid.id == kid_id))).scalar_one_or_none()
        if kid is None:
            raise HTTPException(status_code=404, detail=f"kid {kid_id} not found")
        await s.delete(kid)
