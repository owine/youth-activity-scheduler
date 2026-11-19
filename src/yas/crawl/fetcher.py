"""Fetcher: httpx by default, a remote Browserless Chromium when site.needs_browser=True.

One shared httpx.AsyncClient. The image ships no browser: browser fetches drive
Browserless over CDP (`connect_over_cdp`, not `connect`, because the native
protocol only accepts the Playwright versions Browserless runs, and Renovate
bumps ours independently). Each fetch is its own remote session, connected and
closed around the one page, since Browserless ends a session at the plan's
maximum duration however it is used. Per-site concurrency of 1 via an
asyncio.Lock dict. robots.txt is ignored by default; sites with
crawl_hints['respect_robots'] = True are checked."""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

if TYPE_CHECKING:
    from yas.config import Settings

_USER_AGENT = "yas/0.1 (+https://github.com/example/youth-activity-scheduler)"
_TIMEOUT = httpx.Timeout(30.0)
_RETRY_CODES = {429, 502, 503, 504}
_BACKOFFS_S = (1.0, 4.0, 10.0)  # 3 attempts total (initial + 2 retries after the first wait)
# Browserless ends a session after this long whatever it is doing. It covers
# connect + goto (30s) + the second networkidle wait (30s), and stays under
# every plan's maximum session duration (the free tier's is 2 minutes); a value
# above the plan's maximum is rejected rather than clamped.
_BROWSER_SESSION_TIMEOUT_MS = 90_000
_BROWSER_CONNECT_TIMEOUT_MS = 30_000
_TOKEN_PARAM_RE = re.compile(r"(token=)[^&\s\"'<>]+")
# A rejected token fails the same way on every attempt; retrying only delays
# the FetchError that says so.
_NO_RETRY_CONNECT_RE = re.compile(r"\b(401|403)\b")


def browserless_endpoint(settings: Settings) -> str | None:
    """CDP endpoint for the configured Browserless account, or None without a token.

    The token has to ride in the query string: the shared cloud does not take an
    Authorization header. Callers must therefore treat the URL as a secret, and
    the fetcher redacts it from every error it raises."""
    if settings.browserless_token is None:
        return None
    token = settings.browserless_token.get_secret_value()
    if not token:
        return None
    parts = urlsplit(settings.browserless_url)
    # Keep any parameters already on the URL (a region or stealth flag, say);
    # ours replace same-named ones rather than duplicating them.
    params = [(k, v) for k, v in parse_qsl(parts.query) if k not in {"token", "timeout"}]
    params += [("token", token), ("timeout", str(_BROWSER_SESSION_TIMEOUT_MS))]
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(params), parts.fragment))


def _redact(text: str, endpoint: str) -> str:
    """Strip the Browserless token from an error message.

    A failed websocket handshake quotes the full endpoint URL, and FetchError
    text is stored as the page's last error and shown in the UI."""
    for token in parse_qs(urlsplit(endpoint).query).get("token", []):
        text = text.replace(token, "***")
    return _TOKEN_PARAM_RE.sub(r"\1***", text)


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    html: str
    used_browser: bool
    elapsed_ms: int


class FetchError(Exception):
    def __init__(self, status: int | None, url: str, cause: str):
        super().__init__(f"fetch {url} failed: status={status} cause={cause}")
        self.status = status
        self.url = url
        self.cause = cause


class Fetcher(Protocol):
    async def fetch(self, page: Any, site: Any) -> FetchResult: ...
    async def aclose(self) -> None: ...


class DefaultFetcher:
    def __init__(
        self, browser_ws_url: str | None = None, *, browser_max_concurrency: int = 1
    ) -> None:
        self._http = httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        self._site_locks: dict[int, asyncio.Lock] = {}
        self._browser_ws_url = browser_ws_url
        self._playwright: Any = None
        self._playwright_lock = asyncio.Lock()
        # The scheduler crawls a whole batch at once and per-site locks don't
        # bound sessions across sites, so cap them at the plan's concurrency:
        # a fetch past it would be refused (429) rather than queued.
        self._browser_slots = asyncio.Semaphore(browser_max_concurrency)

    def _lock_for(self, site_id: int) -> asyncio.Lock:
        lock = self._site_locks.get(site_id)
        if lock is None:
            lock = asyncio.Lock()
            self._site_locks[site_id] = lock
        return lock

    async def fetch(self, page: Any, site: Any) -> FetchResult:
        async with self._lock_for(getattr(site, "id", 0)):
            started = time.monotonic()
            if getattr(site, "needs_browser", False):
                html, status, final_url, used_browser = await self._fetch_browser(page.url)
            else:
                html, status, final_url = await self._fetch_http(page.url)
                used_browser = False
            return FetchResult(
                url=final_url,
                status_code=status,
                html=html,
                used_browser=used_browser,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

    async def _fetch_http(self, url: str) -> tuple[str, int, str]:
        last_err: Exception | None = None
        last_status: int | None = None
        for attempt in range(len(_BACKOFFS_S) + 1):
            try:
                r = await self._http.get(url)
                if r.status_code in _RETRY_CODES:
                    last_status = r.status_code
                    if attempt < len(_BACKOFFS_S):
                        await asyncio.sleep(_BACKOFFS_S[attempt])
                        continue
                    raise FetchError(r.status_code, url, f"exhausted retries on {r.status_code}")
                if r.status_code >= 400:
                    raise FetchError(r.status_code, url, f"http {r.status_code}")
                return r.text, r.status_code, str(r.url)
            except FetchError:
                raise
            except httpx.TransportError as exc:
                last_err = exc
                if attempt < len(_BACKOFFS_S):
                    await asyncio.sleep(_BACKOFFS_S[attempt])
                    continue
                raise FetchError(None, url, f"transport: {exc}") from exc
        # Should be unreachable.
        raise FetchError(last_status, url, f"unexpected fall-through: {last_err}")

    async def _fetch_browser(self, url: str) -> tuple[str, int, str, bool]:
        endpoint = self._browser_ws_url
        if endpoint is None:
            raise FetchError(None, url, "site needs a browser but YAS_BROWSERLESS_TOKEN is not set")
        async with self._playwright_lock:
            if self._playwright is None:
                from playwright.async_api import async_playwright

                # Starts Playwright's Node driver, which runs locally even though
                # the browser does not; this is why the image keeps libatomic1.
                self._playwright = await async_playwright().start()
        from playwright.async_api import Error as PlaywrightError

        async with self._browser_slots:
            browser = await self._connect(endpoint, url)
            try:
                context = await browser.new_context(user_agent=_USER_AGENT)
                page = await context.new_page()
                response = await page.goto(url, wait_until="networkidle", timeout=30000)
                status = response.status if response is not None else 200
                if status >= 400:
                    raise FetchError(status, url, f"browser http {status}")
                # Give late-firing setTimeout/DOM updates one tick.
                await page.wait_for_load_state("networkidle")
                html = await page.content()
                final_url = page.url
                return html, status, final_url, True
            except PlaywrightError as exc:
                # A navigation timeout or a dropped remote session is a per-site
                # network failure, like httpx's TransportError: back off, don't
                # page. Redacted and unchained in case it quotes the endpoint.
                raise FetchError(None, url, f"browser: {_redact(str(exc), endpoint)}") from None
            finally:
                # Ends the remote session, freeing the plan's concurrency slot now
                # rather than at the session timeout.
                with contextlib.suppress(Exception):
                    await browser.close()

    async def _connect(self, endpoint: str, url: str) -> Any:
        """connect_over_cdp, retrying transient refusals (429, 5xx, timeouts)."""
        for attempt in range(len(_BACKOFFS_S) + 1):
            try:
                return await self._playwright.chromium.connect_over_cdp(
                    endpoint, timeout=_BROWSER_CONNECT_TIMEOUT_MS
                )
            except Exception as exc:
                message = _redact(str(exc), endpoint)
                if attempt < len(_BACKOFFS_S) and not _NO_RETRY_CONNECT_RE.search(message):
                    await asyncio.sleep(_BACKOFFS_S[attempt])
                    continue
                # `from None`: the cause's message carries the token too.
                raise FetchError(None, url, f"browser connect: {message}") from None
        raise AssertionError("unreachable")  # pragma: no cover

    async def aclose(self) -> None:
        await self._http.aclose()
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
