import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import Site
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app

_SEED = """<html><body>
  <a href="/programs/">Programs</a>
  <a href="/feed/">RSS</a>
  <a href="/brochure.pdf">Brochure</a>
</body></html>"""

_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://ysi.test/programs/summer/</loc></url>
</urlset>"""

_PAGE = "<html><head><title>T</title></head></html>"


class _FakeLLM:
    """Exposes only call_tool; used in place of AnthropicClient for discovery tests."""

    def __init__(self, scored: list[dict]):
        self.scored = scored
        self.call_count = 0

    async def call_tool(
        self, *, system, user, tool_name, tool_description, input_schema, max_tokens=4096
    ):
        self.call_count += 1
        return {"candidates": self.scored}, "fake-haiku", 0.003


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/d.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Site(id=1, name="YSI", base_url="https://ysi.test/"))

    llm = _FakeLLM(
        [
            {"url": "https://ysi.test/programs/summer/", "score": 0.9, "reason": "program detail"},
            {"url": "https://ysi.test/programs/", "score": 0.4, "reason": "router"},
            {"url": "https://ysi.test/brochure.pdf", "score": 0.7, "reason": "pdf brochure"},
        ]
    )
    app = create_app(engine=engine, llm=llm)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine, llm
    await engine.dispose()


@pytest.mark.asyncio
@respx.mock
async def test_discover_returns_candidates(client):
    c, _, _llm = client
    respx.get("https://ysi.test/").mock(return_value=httpx.Response(200, text=_SEED))
    respx.get("https://ysi.test/sitemap.xml").mock(
        return_value=httpx.Response(200, content=_SITEMAP)
    )
    respx.get("https://ysi.test/programs/summer/").mock(
        return_value=httpx.Response(200, text=_PAGE)
    )
    respx.get("https://ysi.test/programs/").mock(return_value=httpx.Response(200, text=_PAGE))

    r = await c.post("/api/sites/1/discover")
    assert r.status_code == 200
    body = r.json()
    assert body["site_id"] == 1
    urls = {ch["url"] for ch in body["candidates"]}
    # PDF surfaced; /feed/ and /programs/ (score 0.4) filtered.
    assert "https://ysi.test/programs/summer/" in urls
    assert "https://ysi.test/brochure.pdf" in urls
    pdf = next(ch for ch in body["candidates"] if ch["kind"] == "pdf")
    assert pdf["title"] == "brochure.pdf"


@pytest.mark.asyncio
@respx.mock
async def test_discover_404_when_site_missing(client):
    c, _, _ = client
    r = await c.post("/api/sites/999/discover")
    assert r.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_discover_502_when_seed_fails(client):
    c, _, _ = client
    respx.get("https://ysi.test/").mock(return_value=httpx.Response(502))
    r = await c.post("/api/sites/1/discover")
    assert r.status_code == 502
    assert "seed_fetch_failed" in r.json()["detail"]


@pytest.mark.asyncio
@respx.mock
async def test_discover_accepts_min_score_override(client):
    c, _, _ = client
    respx.get("https://ysi.test/").mock(return_value=httpx.Response(200, text=_SEED))
    respx.get("https://ysi.test/sitemap.xml").mock(
        return_value=httpx.Response(200, content=_SITEMAP)
    )
    respx.get("https://ysi.test/programs/summer/").mock(
        return_value=httpx.Response(200, text=_PAGE)
    )
    respx.get("https://ysi.test/programs/").mock(return_value=httpx.Response(200, text=_PAGE))
    r = await c.post("/api/sites/1/discover", json={"min_score": 0.85})
    assert r.status_code == 200
    body = r.json()
    # Only summer/ scores >= 0.85; pdf 0.7 filtered
    urls = {ch["url"] for ch in body["candidates"]}
    assert urls == {"https://ysi.test/programs/summer/"}


@pytest.mark.asyncio
async def test_discover_rejects_invalid_min_score(client):
    c, _, _ = client
    r = await c.post("/api/sites/1/discover", json={"min_score": 1.5})
    assert r.status_code == 422
