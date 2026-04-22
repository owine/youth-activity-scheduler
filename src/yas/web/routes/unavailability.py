"""CRUD for /api/kids/{kid_id}/unavailability.

Manual/custom blocks can be created, edited, and deleted here. School and
enrollment blocks appear in GET for visibility but refuse mutation — they're
derived from kid school fields and enrollment status, respectively, and must
be edited via those sources of truth."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from yas.db.models import Kid, UnavailabilityBlock
from yas.db.models._types import UnavailabilitySource
from yas.db.session import session_scope
from yas.matching.matcher import rematch_kid
from yas.web.routes.unavailability_schemas import (
    _ALLOWED_SOURCES,
    UnavailabilityCreate,
    UnavailabilityOut,
    UnavailabilityPatch,
)

router = APIRouter(prefix="/api/kids/{kid_id}/unavailability", tags=["unavailability"])

_MANAGED_SOURCES = {UnavailabilitySource.school.value, UnavailabilitySource.enrollment.value}


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


async def _require_kid(session: AsyncSession, kid_id: int) -> Kid:
    kid = (await session.execute(select(Kid).where(Kid.id == kid_id))).scalar_one_or_none()
    if kid is None:
        raise HTTPException(status_code=404, detail=f"kid {kid_id} not found")
    return kid


def _source_val(block: UnavailabilityBlock) -> str:
    return str(getattr(block.source, "value", block.source))


@router.get("", response_model=list[UnavailabilityOut])
async def list_blocks(kid_id: int, request: Request) -> list[UnavailabilityOut]:
    """List ALL blocks for a kid, including school/enrollment rows (read-only)."""
    async with session_scope(_engine(request)) as s:
        await _require_kid(s, kid_id)
        rows = (
            (
                await s.execute(
                    select(UnavailabilityBlock)
                    .where(UnavailabilityBlock.kid_id == kid_id)
                    .order_by(UnavailabilityBlock.id)
                )
            )
            .scalars()
            .all()
        )
        return [UnavailabilityOut.model_validate(r) for r in rows]


@router.post("", response_model=UnavailabilityOut, status_code=status.HTTP_201_CREATED)
async def create_block(
    kid_id: int, payload: UnavailabilityCreate, request: Request
) -> UnavailabilityOut:
    if payload.source not in _ALLOWED_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"source must be one of {sorted(_ALLOWED_SOURCES)}",
        )
    async with session_scope(_engine(request)) as s:
        await _require_kid(s, kid_id)
        block = UnavailabilityBlock(
            kid_id=kid_id,
            source=payload.source,
            label=payload.label,
            days_of_week=payload.days_of_week,
            time_start=payload.time_start,
            time_end=payload.time_end,
            date_start=payload.date_start,
            date_end=payload.date_end,
            active=payload.active,
        )
        s.add(block)
        await s.flush()
        await rematch_kid(s, kid_id)
        return UnavailabilityOut.model_validate(block)


@router.patch("/{block_id}", response_model=UnavailabilityOut)
async def patch_block(
    kid_id: int, block_id: int, payload: UnavailabilityPatch, request: Request
) -> UnavailabilityOut:
    async with session_scope(_engine(request)) as s:
        await _require_kid(s, kid_id)
        block = (
            await s.execute(
                select(UnavailabilityBlock).where(
                    UnavailabilityBlock.id == block_id,
                    UnavailabilityBlock.kid_id == kid_id,
                )
            )
        ).scalar_one_or_none()
        if block is None:
            raise HTTPException(status_code=404, detail=f"block {block_id} not found")
        if _source_val(block) in _MANAGED_SOURCES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"block {block_id} has source={_source_val(block)} — "
                    "edit it via its source of truth "
                    "(/api/kids/{id} for school, /api/enrollments/{id} for enrollment)"
                ),
            )
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(block, key, value)
        await s.flush()
        await rematch_kid(s, kid_id)
        return UnavailabilityOut.model_validate(block)


@router.delete("/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_block(kid_id: int, block_id: int, request: Request) -> None:
    async with session_scope(_engine(request)) as s:
        await _require_kid(s, kid_id)
        block = (
            await s.execute(
                select(UnavailabilityBlock).where(
                    UnavailabilityBlock.id == block_id,
                    UnavailabilityBlock.kid_id == kid_id,
                )
            )
        ).scalar_one_or_none()
        if block is None:
            raise HTTPException(status_code=404, detail=f"block {block_id} not found")
        if _source_val(block) in _MANAGED_SOURCES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"block {block_id} has source={_source_val(block)} — "
                    "delete it via its source of truth"
                ),
            )
        await s.delete(block)
        await s.flush()
        await rematch_kid(s, kid_id)
