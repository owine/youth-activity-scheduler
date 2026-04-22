"""CRUD for /api/enrollments.

Every mutation applies the enrollment block materializer then rematches the
affected kid: status=enrolled creates a linked unavailability block, any
other status removes it."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from yas.db.models import Enrollment, Kid, Offering
from yas.db.session import session_scope
from yas.matching.matcher import rematch_kid
from yas.unavailability.enrollment_materializer import apply_enrollment_block
from yas.web.routes.enrollments_schemas import (
    EnrollmentCreate,
    EnrollmentOut,
    EnrollmentPatch,
)

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


@router.post("", response_model=EnrollmentOut, status_code=status.HTTP_201_CREATED)
async def create_enrollment(payload: EnrollmentCreate, request: Request) -> EnrollmentOut:
    async with session_scope(_engine(request)) as s:
        await _require_kid(s, payload.kid_id)
        await _require_offering(s, payload.offering_id)
        enrollment = Enrollment(
            kid_id=payload.kid_id,
            offering_id=payload.offering_id,
            status=payload.status,
            enrolled_at=payload.enrolled_at,
            notes=payload.notes,
        )
        s.add(enrollment)
        await s.flush()
        await apply_enrollment_block(s, enrollment.id)
        await rematch_kid(s, payload.kid_id)
        return EnrollmentOut.model_validate(enrollment)


@router.get("", response_model=list[EnrollmentOut])
async def list_enrollments(
    request: Request,
    kid_id: int | None = Query(default=None),
    offering_id: int | None = Query(default=None),
    enrollment_status: str | None = Query(default=None, alias="status"),
) -> list[EnrollmentOut]:
    async with session_scope(_engine(request)) as s:
        q = select(Enrollment)
        if kid_id is not None:
            q = q.where(Enrollment.kid_id == kid_id)
        if offering_id is not None:
            q = q.where(Enrollment.offering_id == offering_id)
        if enrollment_status is not None:
            q = q.where(Enrollment.status == enrollment_status)
        q = q.order_by(Enrollment.id)
        rows = (await s.execute(q)).scalars().all()
        return [EnrollmentOut.model_validate(r) for r in rows]


@router.get("/{enrollment_id}", response_model=EnrollmentOut)
async def get_enrollment(enrollment_id: int, request: Request) -> EnrollmentOut:
    async with session_scope(_engine(request)) as s:
        enrollment = (
            await s.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
        ).scalar_one_or_none()
        if enrollment is None:
            raise HTTPException(status_code=404, detail=f"enrollment {enrollment_id} not found")
        return EnrollmentOut.model_validate(enrollment)


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
            setattr(enrollment, key, value)
        await s.flush()
        await apply_enrollment_block(s, enrollment.id)
        await rematch_kid(s, enrollment.kid_id)
        return EnrollmentOut.model_validate(enrollment)


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
