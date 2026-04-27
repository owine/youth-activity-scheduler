"""SPA fallback route ordering invariants."""

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.session import create_engine_for
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    # Point STATIC_DIR at a fixture dir that contains an index.html
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>SPA</body></html>")
    (static / "assets").mkdir()
    (static / "assets" / "app-abc.js").write_text("console.log('hi')")
    monkeypatch.setenv("YAS_STATIC_DIR", str(static))

    url = f"sqlite+aiosqlite:///{tmp_path}/s.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_api_path_returns_json_not_spa(client):
    r = await client.get("/api/kids")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_unknown_api_path_returns_404_json_not_spa(client):
    r = await client.get("/api/nonexistent")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_root_returns_spa_html(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "SPA" in r.text


@pytest.mark.asyncio
async def test_deep_link_returns_spa_html(client):
    r = await client.get("/kids/1/matches")
    assert r.status_code == 200
    assert "SPA" in r.text
    # Cache-Control prevents stale HTML
    assert r.headers.get("cache-control", "").lower().startswith("no-cache")


@pytest.mark.asyncio
async def test_assets_path_serves_static_file(client):
    r = await client.get("/assets/app-abc.js")
    assert r.status_code == 200
    assert "console.log" in r.text


@pytest.mark.asyncio
async def test_unknown_asset_returns_404_not_spa(client):
    r = await client.get("/assets/missing.js")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_healthz_unaffected(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
