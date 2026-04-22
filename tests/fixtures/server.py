"""Local aiohttp server for hermetic crawl tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer

FIXTURES_DIR = Path(__file__).resolve().parent / "sites"


@dataclass
class FixtureSite:
    base_url: str
    _pages: dict[str, str] = field(default_factory=dict)
    _server: TestServer | None = None

    def set_page(self, path: str, html: str) -> None:
        """Swap the body served for `path` at runtime (for change-detection tests)."""
        if not path.startswith("/"):
            path = "/" + path
        self._pages[path] = html

    def url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url.rstrip('/')}{path}"


@asynccontextmanager
async def fixture_site(
    *,
    pages: dict[str, str] | None = None,
) -> AsyncIterator[FixtureSite]:
    """Start a local aiohttp app serving `pages` (path -> HTML). Yield a handle."""
    site = FixtureSite(base_url="")
    if pages:
        for k, v in pages.items():
            site.set_page(k, v)

    async def handler(request: web.Request) -> web.Response:
        path = request.path
        html = site._pages.get(path)
        if html is None:
            return web.Response(status=404, text=f"no page registered for {path}")
        return web.Response(body=html.encode("utf-8"), content_type="text/html")

    app = web.Application()
    app.router.add_get("/{tail:.*}", handler)
    server = TestServer(app, port=0)
    await server.start_server()
    try:
        site.base_url = str(server.make_url("/"))
        site._server = server
        yield site
    finally:
        await server.close()


def load_fixture(relative_path: str) -> str:
    """Read a captured HTML fixture under tests/fixtures/sites/."""
    return (FIXTURES_DIR / relative_path).read_text(encoding="utf-8")
