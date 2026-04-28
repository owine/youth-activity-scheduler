"""Read-only /api/sites/{id}/crawls endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.db.models import CrawlRun, Site
from yas.db.session import session_scope
from yas.web.routes.site_crawls_schemas import CrawlRunOut

router = APIRouter(prefix="/api/sites", tags=["sites"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


@router.get("/{site_id}/crawls", response_model=list[CrawlRunOut])
async def list_crawls(
    site_id: int,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[CrawlRunOut]:
    async with session_scope(_engine(request)) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        rows = (
            (
                await s.execute(
                    select(CrawlRun)
                    .where(CrawlRun.site_id == site_id)
                    .order_by(CrawlRun.started_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [CrawlRunOut.model_validate(r) for r in rows]
