from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import CrawlRun, Site
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/c.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_crawls_empty(client):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(Site(name="Test", base_url="https://t.example", needs_browser=False))
    r = await c.get("/api/sites/1/crawls")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_crawls_returns_recent_first(client):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(Site(name="Test", base_url="https://t.example", needs_browser=False))
        await s.flush()
        for i in range(3):
            s.add(
                CrawlRun(
                    site_id=1,
                    started_at=datetime(2026, 4, 24 - i, 12, 0, tzinfo=UTC),
                    finished_at=datetime(2026, 4, 24 - i, 12, 5, tzinfo=UTC),
                    status="ok",
                    pages_fetched=i + 1,
                    changes_detected=i,
                    llm_calls=0,
                    llm_cost_usd=0.0,
                )
            )
    r = await c.get("/api/sites/1/crawls")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    # Most recent first
    assert body[0]["pages_fetched"] == 1  # i=0 → most recent
    assert body[2]["pages_fetched"] == 3


@pytest.mark.asyncio
async def test_list_crawls_404_for_unknown_site(client):
    c, _ = client
    r = await c.get("/api/sites/999/crawls")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_crawls_respects_limit(client):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(Site(name="Test", base_url="https://t.example", needs_browser=False))
        await s.flush()
        for i in range(20):
            s.add(
                CrawlRun(
                    site_id=1,
                    started_at=datetime(2026, 4, 1 + i, 12, 0, tzinfo=UTC),
                    status="ok",
                    pages_fetched=0,
                    changes_detected=0,
                    llm_calls=0,
                    llm_cost_usd=0.0,
                )
            )
    r = await c.get("/api/sites/1/crawls?limit=5")
    assert r.status_code == 200
    assert len(r.json()) == 5


@pytest.mark.asyncio
async def test_list_crawls_limit_validation(client):
    c, _ = client
    r1 = await c.get("/api/sites/1/crawls?limit=0")
    assert r1.status_code == 422
    r2 = await c.get("/api/sites/1/crawls?limit=101")
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_list_crawls_includes_error_text_for_failed_crawls(client):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(Site(name="Test", base_url="https://t.example", needs_browser=False))
        await s.flush()
        s.add(
            CrawlRun(
                site_id=1,
                started_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
                status="failed",
                pages_fetched=0,
                changes_detected=0,
                llm_calls=0,
                llm_cost_usd=0.0,
                error_text="connection refused",
            )
        )
    r = await c.get("/api/sites/1/crawls")
    body = r.json()
    assert body[0]["status"] == "failed"
    assert body[0]["error_text"] == "connection refused"
