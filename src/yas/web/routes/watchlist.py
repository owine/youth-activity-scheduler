"""CRUD for /api/kids/{kid_id}/watchlist."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from yas.db.models import Kid, Site, WatchlistEntry
from yas.db.session import session_scope
from yas.matching.matcher import rematch_kid
from yas.web.routes.watchlist_schemas import WatchlistCreate, WatchlistOut, WatchlistPatch

router = APIRouter(prefix="/api/kids/{kid_id}/watchlist", tags=["watchlist"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


async def _require_kid(session: AsyncSession, kid_id: int) -> Kid:
    kid = (await session.execute(select(Kid).where(Kid.id == kid_id))).scalar_one_or_none()
    if kid is None:
        raise HTTPException(status_code=404, detail=f"kid {kid_id} not found")
    return kid


async def _require_site(session: AsyncSession, site_id: int) -> Site:
    site = (await session.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail=f"site {site_id} not found")
    return site


@router.get("", response_model=list[WatchlistOut])
async def list_watchlist(kid_id: int, request: Request) -> list[WatchlistOut]:
    async with session_scope(_engine(request)) as s:
        await _require_kid(s, kid_id)
        rows = (
            (
                await s.execute(
                    select(WatchlistEntry)
                    .where(WatchlistEntry.kid_id == kid_id)
                    .order_by(WatchlistEntry.id)
                )
            )
            .scalars()
            .all()
        )
        return [WatchlistOut.model_validate(r) for r in rows]


@router.post("", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
async def create_watchlist(kid_id: int, payload: WatchlistCreate, request: Request) -> WatchlistOut:
    async with session_scope(_engine(request)) as s:
        await _require_kid(s, kid_id)
        if payload.site_id is not None:
            await _require_site(s, payload.site_id)
        entry = WatchlistEntry(
            kid_id=kid_id,
            site_id=payload.site_id,
            pattern=payload.pattern,
            priority=payload.priority,
            notes=payload.notes,
            active=payload.active,
            ignore_hard_gates=payload.ignore_hard_gates,
        )
        s.add(entry)
        await s.flush()
        await rematch_kid(s, kid_id)
        return WatchlistOut.model_validate(entry)


@router.patch("/{entry_id}", response_model=WatchlistOut)
async def patch_watchlist(
    kid_id: int, entry_id: int, payload: WatchlistPatch, request: Request
) -> WatchlistOut:
    async with session_scope(_engine(request)) as s:
        await _require_kid(s, kid_id)
        entry = (
            await s.execute(
                select(WatchlistEntry).where(
                    WatchlistEntry.id == entry_id, WatchlistEntry.kid_id == kid_id
                )
            )
        ).scalar_one_or_none()
        if entry is None:
            raise HTTPException(status_code=404, detail=f"watchlist entry {entry_id} not found")
        data = payload.model_dump(exclude_unset=True)
        if "site_id" in data and data["site_id"] is not None:
            await _require_site(s, data["site_id"])
        for key, value in data.items():
            setattr(entry, key, value)
        await s.flush()
        await rematch_kid(s, kid_id)
        return WatchlistOut.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(kid_id: int, entry_id: int, request: Request) -> None:
    async with session_scope(_engine(request)) as s:
        await _require_kid(s, kid_id)
        entry = (
            await s.execute(
                select(WatchlistEntry).where(
                    WatchlistEntry.id == entry_id, WatchlistEntry.kid_id == kid_id
                )
            )
        ).scalar_one_or_none()
        if entry is None:
            raise HTTPException(status_code=404, detail=f"watchlist entry {entry_id} not found")
        await s.delete(entry)
        await s.flush()
        await rematch_kid(s, kid_id)
