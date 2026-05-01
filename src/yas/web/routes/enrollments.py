"""CRUD for /api/enrollments.

Every mutation applies the enrollment block materializer then rematches the
affected kid: status=enrolled creates a linked unavailability block, any
other status removes it."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from yas.db.models import Enrollment, Kid, Location, Offering, Site
from yas.db.models._types import EnrollmentStatus
from yas.db.session import session_scope
from yas.matching.matcher import rematch_kid
from yas.unavailability.enrollment_materializer import apply_enrollment_block
from yas.web.routes.enrollments_schemas import (
    EnrollmentCreate,
    EnrollmentOut,
    EnrollmentPatch,
)
from yas.web.routes.matches_schemas import OfferingSummary

router = APIRouter(prefix="/api/enrollments", tags=["enrollments"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


async def _require_kid(session: AsyncSession, kid_id: int) -> Kid:
    kid = (await session.execute(select(Kid).where(Kid.id == kid_id))).scalar_one_or_none()
    if kid is None:
        raise HTTPException(status_code=404, detail=f"kid {kid_id} not found")
    return kid


async def _require_offering(session: AsyncSession, offering_id: int) -> Offering:
    offering = (
        await session.execute(select(Offering).where(Offering.id == offering_id))
    ).scalar_one_or_none()
    if offering is None:
        raise HTTPException(status_code=404, detail=f"offering {offering_id} not found")
    return offering


def _build_offering_summary(
    offering: Offering, site_name: str, loc_lat: float | None, loc_lon: float | None
) -> OfferingSummary:
    """Build OfferingSummary from joined Offering + Site + Location rows."""
    data = {
        k: getattr(offering, k)
        for k in OfferingSummary.model_fields
        if k not in ("site_name", "registration_opens_at", "location_lat", "location_lon")
    }
    data["site_name"] = site_name
    data["registration_opens_at"] = offering.registration_opens_at
    data["location_lat"] = loc_lat
    data["location_lon"] = loc_lon
    return OfferingSummary.model_validate(data)


@router.post("", response_model=EnrollmentOut, status_code=status.HTTP_201_CREATED)
async def create_enrollment(payload: EnrollmentCreate, request: Request) -> EnrollmentOut:
    async with session_scope(_engine(request)) as s:
        await _require_kid(s, payload.kid_id)
        await _require_offering(s, payload.offering_id)
        enrollment = Enrollment(
            kid_id=payload.kid_id,
            offering_id=payload.offering_id,
            status=payload.status.value,
            enrolled_at=payload.enrolled_at,
            notes=payload.notes,
        )
        s.add(enrollment)
        await s.flush()
        await apply_enrollment_block(s, enrollment.id)
        await rematch_kid(s, payload.kid_id)
        # Fetch offering for the response
        row = (
            await s.execute(
                select(Offering, Site.name, Location.lat, Location.lon)
                .join(Site, Site.id == Offering.site_id)
                .outerjoin(Location, Location.id == Offering.location_id)
                .where(Offering.id == enrollment.offering_id)
            )
        ).first()
        assert row is not None
        offering, site_name, loc_lat, loc_lon = row
        return EnrollmentOut(
            id=enrollment.id,
            kid_id=enrollment.kid_id,
            offering_id=enrollment.offering_id,
            status=EnrollmentStatus(enrollment.status),
            enrolled_at=enrollment.enrolled_at,
            notes=enrollment.notes,
            created_at=enrollment.created_at,
            offering=_build_offering_summary(offering, site_name, loc_lat, loc_lon),
        )


@router.get("", response_model=list[EnrollmentOut])
async def list_enrollments(
    request: Request,
    kid_id: int | None = Query(default=None),
    offering_id: int | None = Query(default=None),
    enrollment_status: EnrollmentStatus | None = Query(default=None, alias="status"),  # noqa: B008
) -> list[EnrollmentOut]:
    async with session_scope(_engine(request)) as s:
        q = (
            select(Enrollment, Offering, Site.name, Location.lat, Location.lon)
            .join(Offering, Enrollment.offering_id == Offering.id)
            .join(Site, Site.id == Offering.site_id)
            .outerjoin(Location, Location.id == Offering.location_id)
        )
        if kid_id is not None:
            q = q.where(Enrollment.kid_id == kid_id)
        if offering_id is not None:
            q = q.where(Enrollment.offering_id == offering_id)
        if enrollment_status is not None:
            q = q.where(Enrollment.status == enrollment_status.value)
        q = q.order_by(Enrollment.id)
        rows = (await s.execute(q)).all()
        return [
            EnrollmentOut(
                id=e.id,
                kid_id=e.kid_id,
                offering_id=e.offering_id,
                status=EnrollmentStatus(e.status),
                enrolled_at=e.enrolled_at,
                notes=e.notes,
                created_at=e.created_at,
                offering=_build_offering_summary(o, site_name, loc_lat, loc_lon),
            )
            for e, o, site_name, loc_lat, loc_lon in rows
        ]


@router.get("/{enrollment_id}", response_model=EnrollmentOut)
async def get_enrollment(enrollment_id: int, request: Request) -> EnrollmentOut:
    async with session_scope(_engine(request)) as s:
        enrollment = (
            await s.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
        ).scalar_one_or_none()
        if enrollment is None:
            raise HTTPException(status_code=404, detail=f"enrollment {enrollment_id} not found")
        # Fetch offering for the response
        row = (
            await s.execute(
                select(Offering, Site.name, Location.lat, Location.lon)
                .join(Site, Site.id == Offering.site_id)
                .outerjoin(Location, Location.id == Offering.location_id)
                .where(Offering.id == enrollment.offering_id)
            )
        ).first()
        assert row is not None
        offering, site_name, loc_lat, loc_lon = row
        return EnrollmentOut(
            id=enrollment.id,
            kid_id=enrollment.kid_id,
            offering_id=enrollment.offering_id,
            status=EnrollmentStatus(enrollment.status),
            enrolled_at=enrollment.enrolled_at,
            notes=enrollment.notes,
            created_at=enrollment.created_at,
            offering=_build_offering_summary(offering, site_name, loc_lat, loc_lon),
        )


@router.patch("/{enrollment_id}", response_model=EnrollmentOut)
async def patch_enrollment(
    enrollment_id: int, payload: EnrollmentPatch, request: Request
) -> EnrollmentOut:
    async with session_scope(_engine(request)) as s:
        enrollment = (
            await s.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
        ).scalar_one_or_none()
        if enrollment is None:
            raise HTTPException(status_code=404, detail=f"enrollment {enrollment_id} not found")
        for key, value in payload.model_dump(exclude_unset=True).items():
            if key == "status" and value is not None:
                setattr(enrollment, key, value.value)
            else:
                setattr(enrollment, key, value)
        await s.flush()
        await apply_enrollment_block(s, enrollment.id)
        await rematch_kid(s, enrollment.kid_id)
        # Fetch offering for the response
        row = (
            await s.execute(
                select(Offering, Site.name, Location.lat, Location.lon)
                .join(Site, Site.id == Offering.site_id)
                .outerjoin(Location, Location.id == Offering.location_id)
                .where(Offering.id == enrollment.offering_id)
            )
        ).first()
        assert row is not None
        offering, site_name, loc_lat, loc_lon = row
        return EnrollmentOut(
            id=enrollment.id,
            kid_id=enrollment.kid_id,
            offering_id=enrollment.offering_id,
            status=EnrollmentStatus(enrollment.status),
            enrolled_at=enrollment.enrolled_at,
            notes=enrollment.notes,
            created_at=enrollment.created_at,
            offering=_build_offering_summary(offering, site_name, loc_lat, loc_lon),
        )


@router.delete("/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_enrollment(enrollment_id: int, request: Request) -> None:
    async with session_scope(_engine(request)) as s:
        enrollment = (
            await s.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
        ).scalar_one_or_none()
        if enrollment is None:
            raise HTTPException(status_code=404, detail=f"enrollment {enrollment_id} not found")
        kid_id = enrollment.kid_id
        await s.delete(enrollment)
        await s.flush()
        await rematch_kid(s, kid_id)
