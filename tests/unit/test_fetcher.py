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

    # With a per-site lock, we never see start-start-end-end. Asserting the
    # full list also catches a fetch that never reached the handler.
    assert order == ["start", "end", "start", "end"]


# --- remote browser (Browserless) -------------------------------------------

_TOKEN = "kept"
_ENDPOINT = f"wss://browser.example?token={_TOKEN}&timeout=90000"


def test_browserless_endpoint_none_without_token():
    from yas.config import Settings
    from yas.crawl.fetcher import browserless_endpoint

    assert browserless_endpoint(Settings(anthropic_api_key="x", browserless_token=None)) is None
    assert browserless_endpoint(Settings(anthropic_api_key="x", browserless_token="")) is None


def test_browserless_endpoint_carries_token_and_session_timeout():
    from yas.config import Settings
    from yas.crawl.fetcher import browserless_endpoint

    url = browserless_endpoint(
        Settings(
            anthropic_api_key="x",
            browserless_url="wss://browser.example/",
            browserless_token=_TOKEN,
        )
    )
    assert url == f"wss://browser.example?token={_TOKEN}&timeout=90000"


async def test_browser_fetch_without_endpoint_fails_cleanly():
    fetcher = DefaultFetcher()
    try:
        with pytest.raises(FetchError) as ei:
            await fetcher.fetch(_Page("https://example.com/p"), _Site(id=1, needs_browser=True))
        assert "YAS_BROWSERLESS_TOKEN" in ei.value.cause
    finally:
        await fetcher.aclose()


class _RefusingChromium:
    async def connect_over_cdp(self, endpoint, **_kwargs):
        # Mirrors Playwright's handshake error, which quotes the endpoint.
        raise RuntimeError(f"WebSocket error: {endpoint} 401 Unauthorized")


class _FakePlaywright:
    chromium = _RefusingChromium()

    async def stop(self):
        pass


async def test_browser_connect_error_redacts_token():
    fetcher = DefaultFetcher(browser_ws_url=_ENDPOINT)
    fetcher._playwright = _FakePlaywright()
    try:
        with pytest.raises(FetchError) as ei:
            await fetcher.fetch(_Page("https://example.com/p"), _Site(id=1, needs_browser=True))
        assert _TOKEN not in str(ei.value)
        assert "401 Unauthorized" in ei.value.cause
        assert "token=***" in ei.value.cause
        # The chained cause would carry the raw URL into tracebacks and GlitchTip.
        assert ei.value.__cause__ is None
        assert ei.value.__suppress_context__ is True
    finally:
        await fetcher.aclose()


def test_browserless_endpoint_keeps_existing_query_params():
    from yas.config import Settings
    from yas.crawl.fetcher import browserless_endpoint

    url = browserless_endpoint(
        Settings(
            anthropic_api_key="x",
            browserless_url="wss://browser.example/chromium?stealth=true&token=stale",
            browserless_token=_TOKEN,
        )
    )
    assert url == f"wss://browser.example/chromium?stealth=true&token={_TOKEN}&timeout=90000"


class _FakeResponse:
    status = 200


class _FakeBrowserPage:
    def __init__(self, browser):
        self._browser = browser
        self.url = "https://example.com/p"

    async def goto(self, url, **_kwargs):
        if self._browser.goto_error is not None:
            raise self._browser.goto_error
        await asyncio.sleep(0.01)  # hold the session long enough to overlap
        return _FakeResponse()

    async def wait_for_load_state(self, _state):
        pass

    async def content(self):
        return "<html>ok</html>"


class _FakeContext:
    def __init__(self, browser):
        self._browser = browser

    async def new_page(self):
        return _FakeBrowserPage(self._browser)


class _FakeBrowser:
    def __init__(self, chromium, goto_error):
        self._chromium = chromium
        self.goto_error = goto_error
        chromium.active += 1
        chromium.peak = max(chromium.peak, chromium.active)

    async def new_context(self, **_kwargs):
        return _FakeContext(self)

    async def close(self):
        self._chromium.active -= 1
        self._chromium.closed += 1


class _ScriptedChromium:
    """connect_over_cdp raises each queued error in turn, then connects."""

    def __init__(self, connect_errors=(), goto_error=None):
        self.connect_errors = list(connect_errors)
        self.goto_error = goto_error
        self.calls = self.active = self.peak = self.closed = 0

    async def connect_over_cdp(self, endpoint, **_kwargs):
        self.calls += 1
        if self.connect_errors:
            raise self.connect_errors.pop(0)
        return _FakeBrowser(self, self.goto_error)


def _scripted_fetcher(chromium, **kwargs):
    fetcher = DefaultFetcher(browser_ws_url=_ENDPOINT, **kwargs)
    fake = _FakePlaywright()
    fake.chromium = chromium
    fetcher._playwright = fake
    return fetcher


async def test_browser_sessions_capped_across_sites():
    chromium = _ScriptedChromium()
    fetcher = _scripted_fetcher(chromium, browser_max_concurrency=1)
    try:
        # Different sites, so the per-site locks don't serialize them.
        await asyncio.gather(
            *(
                fetcher.fetch(_Page("https://example.com/p"), _Site(id=i, needs_browser=True))
                for i in range(3)
            )
        )
        assert chromium.peak == 1
        assert chromium.closed == 3
    finally:
        await fetcher.aclose()


async def test_browser_connect_retries_transient_refusal(_fast_backoffs):
    chromium = _ScriptedChromium(connect_errors=[RuntimeError("WebSocket error: 429 Too Many")] * 2)
    fetcher = _scripted_fetcher(chromium)
    try:
        result = await fetcher.fetch(
            _Page("https://example.com/p"), _Site(id=1, needs_browser=True)
        )
        assert result.used_browser is True
        assert chromium.calls == 3
    finally:
        await fetcher.aclose()


async def test_browser_connect_does_not_retry_rejected_token(_fast_backoffs):
    chromium = _ScriptedChromium(
        connect_errors=[RuntimeError(f"WebSocket error: {_ENDPOINT} 401 Unauthorized")] * 4
    )
    fetcher = _scripted_fetcher(chromium)
    try:
        with pytest.raises(FetchError):
            await fetcher.fetch(_Page("https://example.com/p"), _Site(id=1, needs_browser=True))
        assert chromium.calls == 1
    finally:
        await fetcher.aclose()


async def test_browser_session_error_becomes_redacted_fetch_error():
    from playwright.async_api import Error as PlaywrightError

    chromium = _ScriptedChromium(
        goto_error=PlaywrightError(f"Target closed: session {_ENDPOINT} ended")
    )
    fetcher = _scripted_fetcher(chromium)
    try:
        with pytest.raises(FetchError) as ei:
            await fetcher.fetch(_Page("https://example.com/p"), _Site(id=1, needs_browser=True))
        assert ei.value.cause.startswith("browser: Target closed")
        assert _TOKEN not in str(ei.value)
        assert ei.value.__cause__ is None
        assert chromium.closed == 1  # session still released
    finally:
        await fetcher.aclose()
