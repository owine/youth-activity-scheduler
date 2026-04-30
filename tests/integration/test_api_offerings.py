"""Integration tests for PATCH /api/offerings/{id}."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import Offering, Page, Site
from yas.db.models._types import OfferingStatus
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/o.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        s.add(
            Offering(
                id=1,
                site_id=1,
                page_id=1,
                name="T-Ball",
                normalized_name="t-ball",
                days_of_week=["tue"],
                time_start=time(16, 0),
                time_end=time(17, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
            )
        )
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_patch_offering_404_for_unknown_id(client):
    c, _ = client
    r = await c.patch("/api/offerings/9999", json={"muted_until": None})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_offering_422_for_unknown_field(client):
    c, _ = client
    r = await c.patch("/api/offerings/1", json={"unknown_field": "value"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_offering_sets_muted_until(client):
    c, engine = client
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    r = await c.patch("/api/offerings/1", json={"muted_until": future})
    assert r.status_code == 200
    body = r.json()
    assert body["muted_until"] is not None
    async with session_scope(engine) as s:
        o = (await s.execute(select(Offering).where(Offering.id == 1))).scalar_one()
    assert o.muted_until is not None


@pytest.mark.asyncio
async def test_patch_offering_clears_muted_until(client):
    c, engine = client
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    await c.patch("/api/offerings/1", json={"muted_until": future})
    r = await c.patch("/api/offerings/1", json={"muted_until": None})
    assert r.status_code == 200
    body = r.json()
    assert body["muted_until"] is None
    async with session_scope(engine) as s:
        o = (await s.execute(select(Offering).where(Offering.id == 1))).scalar_one()
    assert o.muted_until is None


@pytest.mark.asyncio
async def test_patch_offering_empty_body_does_not_clear_muted_until(client):
    """An empty PATCH body must not null out the muted_until field."""
    c, engine = client
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    await c.patch("/api/offerings/1", json={"muted_until": future})
    r = await c.patch("/api/offerings/1", json={})
    assert r.status_code == 200
    async with session_scope(engine) as s:
        o = (await s.execute(select(Offering).where(Offering.id == 1))).scalar_one()
    assert o.muted_until is not None
