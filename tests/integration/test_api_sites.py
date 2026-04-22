from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import Page, Site
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/api.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_list_site(client):
    c, _ = client
    r = await c.post(
        "/api/sites",
        json={
            "name": "Lil Sluggers",
            "base_url": "https://example.com/",
            "needs_browser": True,
            "default_cadence_s": 3600,
            "pages": [{"url": "https://example.com/p", "kind": "schedule"}],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] > 0
    assert body["name"] == "Lil Sluggers"
    assert len(body["pages"]) == 1
    r = await c.get("/api/sites")
    assert r.status_code == 200
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_get_site_returns_pages(client):
    c, _ = client
    created = await c.post(
        "/api/sites",
        json={
            "name": "X",
            "base_url": "https://x/",
            "pages": [{"url": "https://x/a"}, {"url": "https://x/b"}],
        },
    )
    site_id = created.json()["id"]
    r = await c.get(f"/api/sites/{site_id}")
    assert r.status_code == 200
    assert {p["url"] for p in r.json()["pages"]} == {"https://x/a", "https://x/b"}


@pytest.mark.asyncio
async def test_patch_site(client):
    c, _ = client
    created = await c.post("/api/sites", json={"name": "X", "base_url": "https://x/"})
    sid = created.json()["id"]
    r = await c.patch(f"/api/sites/{sid}", json={"active": False, "default_cadence_s": 60})
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is False
    assert body["default_cadence_s"] == 60


@pytest.mark.asyncio
async def test_delete_site_cascades(client):
    c, engine = client
    created = await c.post(
        "/api/sites",
        json={
            "name": "X",
            "base_url": "https://x/",
            "pages": [{"url": "https://x/a"}],
        },
    )
    sid = created.json()["id"]
    r = await c.delete(f"/api/sites/{sid}")
    assert r.status_code == 204
    async with session_scope(engine) as s:
        assert (await s.execute(select(Site))).scalars().all() == []
        assert (await s.execute(select(Page))).scalars().all() == []


@pytest.mark.asyncio
async def test_add_and_remove_page(client):
    c, _ = client
    created = await c.post("/api/sites", json={"name": "X", "base_url": "https://x/"})
    sid = created.json()["id"]
    r = await c.post(f"/api/sites/{sid}/pages", json={"url": "https://x/added"})
    assert r.status_code == 201
    pid = r.json()["id"]
    r = await c.delete(f"/api/sites/{sid}/pages/{pid}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_crawl_now_resets_next_check_at(client):
    c, engine = client
    created = await c.post(
        "/api/sites",
        json={
            "name": "X",
            "base_url": "https://x/",
            "pages": [{"url": "https://x/a"}],
        },
    )
    sid = created.json()["id"]
    # Simulate a future-scheduled page.
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page))).scalars().one()
        from datetime import UTC, datetime, timedelta

        page.next_check_at = datetime.now(UTC) + timedelta(days=1)
    r = await c.post(f"/api/sites/{sid}/crawl-now")
    assert r.status_code == 202
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page))).scalars().one()
        from datetime import UTC, datetime

        # tz-aware comparison
        next_check = (
            page.next_check_at.replace(tzinfo=UTC)
            if page.next_check_at.tzinfo is None
            else page.next_check_at
        )
        assert next_check <= datetime.now(UTC) + __import__("datetime").timedelta(seconds=1)


@pytest.mark.asyncio
async def test_get_nonexistent_site_returns_404(client):
    c, _ = client
    r = await c.get("/api/sites/999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_add_page_rejects_pdf_kind(client):
    """Phase 3.5: PageIn.kind is a Literal that excludes 'pdf'. PDF pages are
    discoverable via /api/sites/{id}/discover but not yet trackable."""
    c, _ = client
    created = await c.post("/api/sites", json={"name": "X", "base_url": "https://x/"})
    sid = created.json()["id"]
    r = await c.post(
        f"/api/sites/{sid}/pages",
        json={"url": "https://x/schedule.pdf", "kind": "pdf"},
    )
    assert r.status_code == 422
