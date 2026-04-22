from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import Kid, Site, WatchlistEntry
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/w.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1), interests=["soccer"]))
        s.add(Site(id=1, name="Test Site", base_url="https://x/"))
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_watchlist_entries_empty(client):
    c, _ = client
    r = await c.get("/api/kids/1/watchlist")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_watchlist_entry_triggers_rematch(client, monkeypatch):
    c, _ = client
    calls: list[int] = []

    async def spy(session, kid_id):
        calls.append(kid_id)
        from yas.matching.matcher import MatchResult
        return MatchResult(kid_id=kid_id)

    monkeypatch.setattr("yas.web.routes.watchlist.rematch_kid", spy)
    r = await c.post(
        "/api/kids/1/watchlist",
        json={"pattern": "little kickers*", "priority": "high"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["pattern"] == "little kickers*"
    assert body["priority"] == "high"
    assert calls == [1]


@pytest.mark.asyncio
async def test_create_with_nonexistent_site_returns_404(client):
    c, _ = client
    r = await c.post("/api/kids/1/watchlist", json={"pattern": "x", "site_id": 999})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_with_nonexistent_kid_returns_404(client):
    c, _ = client
    r = await c.post("/api/kids/999/watchlist", json={"pattern": "x"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_pattern_triggers_rematch(client, monkeypatch):
    c, _ = client
    create = await c.post("/api/kids/1/watchlist", json={"pattern": "a"})
    assert create.status_code == 201
    entry_id = create.json()["id"]

    calls: list[int] = []

    async def spy(session, kid_id):
        calls.append(kid_id)
        from yas.matching.matcher import MatchResult
        return MatchResult(kid_id=kid_id)

    monkeypatch.setattr("yas.web.routes.watchlist.rematch_kid", spy)
    r = await c.patch(f"/api/kids/1/watchlist/{entry_id}", json={"pattern": "b"})
    assert r.status_code == 200
    assert r.json()["pattern"] == "b"
    assert calls == [1]


@pytest.mark.asyncio
async def test_delete_entry_triggers_rematch(client, engine=None, monkeypatch=None):
    c, engine = client
    create = await c.post("/api/kids/1/watchlist", json={"pattern": "x"})
    entry_id = create.json()["id"]
    r = await c.delete(f"/api/kids/1/watchlist/{entry_id}")
    assert r.status_code == 204
    async with session_scope(engine) as s:
        rows = (await s.execute(select(WatchlistEntry))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_rejects_unknown_fields(client):
    c, _ = client
    r = await c.post(
        "/api/kids/1/watchlist", json={"pattern": "x", "garbage_field": 1}
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_entry_preserves_other_fields(client):
    c, _ = client
    create = await c.post(
        "/api/kids/1/watchlist",
        json={"pattern": "kickers", "priority": "high", "notes": "Sam's favorite"},
    )
    entry_id = create.json()["id"]
    r = await c.patch(f"/api/kids/1/watchlist/{entry_id}", json={"pattern": "newpattern"})
    assert r.status_code == 200
    body = r.json()
    assert body["pattern"] == "newpattern"
    assert body["priority"] == "high"        # unchanged
    assert body["notes"] == "Sam's favorite"  # unchanged
