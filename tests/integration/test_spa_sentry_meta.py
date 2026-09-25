"""The browser DSN is handed to the SPA at request time, not inlined at build.

One published image serves any deployment: the backend renders
SENTRY_BROWSER_DSN (and the release) into index.html as <meta> tags, which
frontend/src/lib/sentry.ts reads at startup.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.session import create_engine_for
from yas.web.app import create_app

INDEX = "<!doctype html><html><head><title>YAS</title></head><body>SPA</body></html>"
BROWSER_DSN = "https://browserkey@glitchtip.example/2"

ClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]


@pytest.fixture
def make_client(tmp_path, monkeypatch) -> ClientFactory:
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("SENTRY_BROWSER_DSN", raising=False)
    monkeypatch.delenv("YAS_GIT_SHA", raising=False)
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text(INDEX)
    monkeypatch.setenv("YAS_STATIC_DIR", str(static))
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)

    @asynccontextmanager
    async def _make(**env: str) -> AsyncIterator[AsyncClient]:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        engine = create_engine_for(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        app = create_app(engine=engine)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
        await engine.dispose()

    return _make


async def test_without_a_browser_dsn_index_is_served_unchanged(make_client):
    async with make_client() as c:
        r = await c.get("/")
    assert r.text == INDEX


async def test_browser_dsn_and_release_render_into_head(make_client):
    async with make_client(SENTRY_BROWSER_DSN=BROWSER_DSN, YAS_GIT_SHA="abc123") as c:
        r = await c.get("/kids/1")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"].lower().startswith("no-cache")
    head = r.text.split("</head>")[0]
    assert f'<meta name="sentry-browser-dsn" content="{BROWSER_DSN}">' in head
    assert '<meta name="sentry-release" content="abc123">' in head


async def test_unknown_release_is_omitted(make_client):
    async with make_client(SENTRY_BROWSER_DSN=BROWSER_DSN) as c:
        r = await c.get("/")
    assert "sentry-browser-dsn" in r.text
    assert "sentry-release" not in r.text


@pytest.mark.parametrize(
    "dsn",
    [
        "",
        "not a url",
        "javascript:alert(1)",
        # A DSN's userinfo is only ever the public key. A password means the
        # wrong URL was pasted, and this one goes to every visitor's browser.
        "https://key:secret@glitchtip.example/2",
    ],
)
async def test_invalid_browser_dsn_is_not_rendered(make_client, dsn):
    async with make_client(SENTRY_BROWSER_DSN=dsn) as c:
        r = await c.get("/")
    assert r.text == INDEX


async def test_rendered_values_are_attribute_escaped(make_client):
    async with make_client(
        SENTRY_BROWSER_DSN='https://k@glitchtip.example/2?"><script>x</script>'
    ) as c:
        r = await c.get("/")
    assert "<script>x</script>" not in r.text
