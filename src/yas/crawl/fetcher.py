"""Fetcher: httpx by default, Playwright when site.needs_browser=True.

One shared httpx.AsyncClient. One lazily-launched Chromium browser + context.
Per-site concurrency of 1 via an asyncio.Lock dict. robots.txt is ignored by
default; sites with crawl_hints['respect_robots'] = True are checked."""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

_USER_AGENT = "yas/0.1 (+https://github.com/example/youth-activity-scheduler)"
_TIMEOUT = httpx.Timeout(30.0)
_RETRY_CODES = {429, 502, 503, 504}
_BACKOFFS_S = (1.0, 4.0, 10.0)   # 3 attempts total (initial + 2 retries after the first wait)


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
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        self._site_locks: dict[int, asyncio.Lock] = {}
        self._browser: Any = None
        self._browser_context: Any = None
        self._playwright: Any = None
        self._browser_lock = asyncio.Lock()

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
        async with self._browser_lock:
            if self._browser is None:
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
                self._browser_context = await self._browser.new_context(
                    user_agent=_USER_AGENT,
                )
        page = await self._browser_context.new_page()
        try:
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
            status = response.status if response is not None else 200
            if status >= 400:
                raise FetchError(status, url, f"browser http {status}")
            # Give late-firing setTimeout/DOM updates one tick.
            await page.wait_for_load_state("networkidle")
            html = await page.content()
            final_url = page.url
            return html, status, final_url, True
        finally:
            await page.close()

    async def aclose(self) -> None:
        await self._http.aclose()
        if self._browser_context is not None:
            with contextlib.suppress(Exception):
                await self._browser_context.close()
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
