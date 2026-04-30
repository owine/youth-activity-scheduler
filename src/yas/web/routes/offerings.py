"""CRUD for /api/offerings — initial scope: mute toggle."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.db.models import Offering
from yas.db.session import session_scope

router = APIRouter(prefix="/api/offerings", tags=["offerings"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


class OfferingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    muted_until: datetime | None = None


class OfferingMuteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    site_id: int
    muted_until: datetime | None


@router.patch("/{offering_id}", response_model=OfferingMuteOut)
async def update_offering(
    request: Request,
    offering_id: int,
    payload: OfferingPatch,
) -> OfferingMuteOut:
    async with session_scope(_engine(request)) as s:
        offering = (
            await s.execute(select(Offering).where(Offering.id == offering_id))
        ).scalar_one_or_none()
        if offering is None:
            raise HTTPException(status_code=404, detail=f"offering {offering_id} not found")
        if "muted_until" in payload.model_fields_set:
            offering.muted_until = payload.muted_until
        await s.flush()
        await s.refresh(offering)
        return OfferingMuteOut.model_validate(offering)
