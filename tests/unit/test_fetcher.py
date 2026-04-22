import asyncio

import pytest
import respx
from httpx import Response

from yas.config import get_settings
from yas.crawl.fetcher import DefaultFetcher, FetchError


async def _mk_fetcher():
    _ = get_settings  # typecheck — settings import exercised
    return DefaultFetcher()


class _Page:
    def __init__(self, url):
        self.url = url


class _Site:
    def __init__(self, id, needs_browser=False, crawl_hints=None):
        self.id = id
        self.needs_browser = needs_browser
        self.crawl_hints = crawl_hints or {}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_happy_path():
    respx.get("https://example.com/p").mock(
        return_value=Response(200, html="<html><body>ok</body></html>")
    )
    fetcher = await _mk_fetcher()
    try:
        result = await fetcher.fetch(_Page("https://example.com/p"), _Site(id=1))
        assert result.status_code == 200
        assert "ok" in result.html
        assert result.used_browser is False
    finally:
        await fetcher.aclose()


@pytest.fixture
def _fast_backoffs(monkeypatch):
    """Shrink fetcher backoffs so the retry tests don't burn ~15s of real sleep."""
    from yas.crawl import fetcher as fetcher_mod

    monkeypatch.setattr(fetcher_mod, "_BACKOFFS_S", (0.0, 0.0, 0.0))


@pytest.mark.asyncio
@respx.mock
async def test_fetch_retries_on_429_then_succeeds(_fast_backoffs):
    route = respx.get("https://example.com/p").mock(
        side_effect=[
            Response(429),
            Response(200, html="<html>ok</html>"),
        ]
    )
    fetcher = await _mk_fetcher()
    try:
        result = await fetcher.fetch(_Page("https://example.com/p"), _Site(id=1))
        assert result.status_code == 200
        assert route.call_count == 2
    finally:
        await fetcher.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_gives_up_after_exhausting_retries(_fast_backoffs):
    respx.get("https://example.com/p").mock(return_value=Response(503))
    fetcher = await _mk_fetcher()
    try:
        with pytest.raises(FetchError):
            await fetcher.fetch(_Page("https://example.com/p"), _Site(id=1))
    finally:
        await fetcher.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_does_not_retry_on_4xx_other_than_429():
    route = respx.get("https://example.com/p").mock(return_value=Response(404))
    fetcher = await _mk_fetcher()
    try:
        with pytest.raises(FetchError):
            await fetcher.fetch(_Page("https://example.com/p"), _Site(id=1))
        assert route.call_count == 1
    finally:
        await fetcher.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_enforces_per_site_concurrency_of_1():
    """Two concurrent fetches against the same site_id must execute serially."""
    order: list[str] = []

    async def handler(request):
        order.append("start")
        await asyncio.sleep(0.05)
        order.append("end")
        return Response(200, html="<p/>")

    respx.get("https://example.com/a").mock(side_effect=handler)
    respx.get("https://example.com/b").mock(side_effect=handler)
    fetcher = await _mk_fetcher()
    try:
        await asyncio.gather(
            fetcher.fetch(_Page("https://example.com/a"), _Site(id=1)),
            fetcher.fetch(_Page("https://example.com/b"), _Site(id=1)),
        )
    finally:
        await fetcher.aclose()

    # With a per-site lock, we never see start-start-end-end.
    for i in range(len(order) - 1):
        if order[i] == "start":
            assert order[i + 1] == "end"
