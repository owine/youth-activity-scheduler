"""HTTP endpoints for managing sites and their tracked pages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.db.models import Page, Site
from yas.db.session import session_scope
from yas.web.routes.sites_schemas import (
    PageIn,
    PageOut,
    SiteCreate,
    SiteOut,
    SiteUpdate,
)

router = APIRouter(prefix="/api/sites", tags=["sites"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


def _site_attrs(site: Site) -> dict[str, Any]:
    return {
        "id": site.id,
        "name": site.name,
        "base_url": site.base_url,
        "adapter": site.adapter,
        "needs_browser": site.needs_browser,
        "active": site.active,
        "default_cadence_s": site.default_cadence_s,
        "muted_until": site.muted_until,
    }


@router.post("", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
async def create_site(payload: SiteCreate, request: Request) -> SiteOut:
    now = datetime.now(UTC)
    async with session_scope(_engine(request)) as s:
        site = Site(
            name=payload.name,
            base_url=str(payload.base_url),
            needs_browser=payload.needs_browser,
            default_cadence_s=payload.default_cadence_s,
            crawl_hints=payload.crawl_hints,
        )
        s.add(site)
        await s.flush()
        for p in payload.pages:
            s.add(Page(site_id=site.id, url=str(p.url), kind=p.kind, next_check_at=now))
        await s.flush()
        pages = (
            (await s.execute(select(Page).where(Page.site_id == site.id).order_by(Page.id)))
            .scalars()
            .all()
        )
        return SiteOut.model_validate(
            {
                **_site_attrs(site),
                "pages": [PageOut.model_validate(p) for p in pages],
            }
        )


@router.get("", response_model=list[SiteOut])
async def list_sites(request: Request) -> list[SiteOut]:
    async with session_scope(_engine(request)) as s:
        sites = (await s.execute(select(Site).order_by(Site.id))).scalars().all()
        out: list[SiteOut] = []
        for site in sites:
            pages = (
                (await s.execute(select(Page).where(Page.site_id == site.id).order_by(Page.id)))
                .scalars()
                .all()
            )
            out.append(
                SiteOut.model_validate(
                    {
                        **_site_attrs(site),
                        "pages": [PageOut.model_validate(p) for p in pages],
                    }
                )
            )
        return out


@router.get("/{site_id}", response_model=SiteOut)
async def get_site(site_id: int, request: Request) -> SiteOut:
    async with session_scope(_engine(request)) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        pages = (
            (await s.execute(select(Page).where(Page.site_id == site_id).order_by(Page.id)))
            .scalars()
            .all()
        )
        return SiteOut.model_validate(
            {
                **_site_attrs(site),
                "pages": [PageOut.model_validate(p) for p in pages],
            }
        )


@router.patch("/{site_id}", response_model=SiteOut)
async def update_site(site_id: int, patch: SiteUpdate, request: Request) -> SiteOut:
    async with session_scope(_engine(request)) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        for field, value in patch.model_dump(exclude_unset=True).items():
            setattr(site, field, value)
        await s.flush()
        pages = (
            (await s.execute(select(Page).where(Page.site_id == site_id).order_by(Page.id)))
            .scalars()
            .all()
        )
        return SiteOut.model_validate(
            {
                **_site_attrs(site),
                "pages": [PageOut.model_validate(p) for p in pages],
            }
        )


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(site_id: int, request: Request) -> None:
    async with session_scope(_engine(request)) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        await s.delete(site)


@router.post("/{site_id}/pages", response_model=PageOut, status_code=status.HTTP_201_CREATED)
async def add_page(site_id: int, payload: PageIn, request: Request) -> PageOut:
    now = datetime.now(UTC)
    async with session_scope(_engine(request)) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        page = Page(site_id=site_id, url=str(payload.url), kind=payload.kind, next_check_at=now)
        s.add(page)
        await s.flush()
        return PageOut.model_validate(page)


@router.delete("/{site_id}/pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_page(site_id: int, page_id: int, request: Request) -> None:
    async with session_scope(_engine(request)) as s:
        page = (
            await s.execute(select(Page).where(Page.id == page_id, Page.site_id == site_id))
        ).scalar_one_or_none()
        if page is None:
            raise HTTPException(status_code=404, detail=f"page {page_id} not found")
        await s.delete(page)


@router.post("/{site_id}/crawl-now", status_code=status.HTTP_202_ACCEPTED)
async def crawl_now(site_id: int, request: Request) -> dict[str, int]:
    now = datetime.now(UTC)
    async with session_scope(_engine(request)) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        pages = (await s.execute(select(Page).where(Page.site_id == site_id))).scalars().all()
        for p in pages:
            p.next_check_at = now
        return {"scheduled": len(pages)}
