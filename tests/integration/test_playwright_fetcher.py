"""Playwright fetcher integration test.

Production drives a remote Browserless Chromium over CDP. This stands in a
local Chromium listening on a CDP port, so the real connect_over_cdp path runs
without the cloud (and file:// URLs still resolve). Skipped if Chromium
binaries aren't installed locally."""

from __future__ import annotations

import pathlib
import socket
import sys

import pytest


def _has_chromium() -> bool:
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        return False
    # Presence of the browser binary is checked at launch; skip if missing.
    # Linux/CI default: ~/.cache/ms-playwright. macOS default: ~/Library/Caches/ms-playwright.
    candidates = [pathlib.Path.home() / ".cache" / "ms-playwright"]
    if sys.platform == "darwin":
        candidates.append(pathlib.Path.home() / "Library" / "Caches" / "ms-playwright")
    for cache in candidates:
        if not cache.exists():
            continue
        # Accept both chromium-* (full) and chromium_headless_shell-* (headless shell variant).
        if any(cache.glob("chromium-*")) or any(cache.glob("chromium_headless_shell-*")):
            return True
    return False


pytestmark = pytest.mark.skipif(not _has_chromium(), reason="Chromium not installed")


class _Page:
    def __init__(self, url):
        self.url = url


class _Site:
    def __init__(self, id, needs_browser=True, crawl_hints=None):
        self.id = id
        self.needs_browser = needs_browser
        self.crawl_hints = crawl_hints or {}


JS_PAGE = """<!doctype html>
<html><body>
<div id="greet">waiting</div>
<script>
  setTimeout(() => {
    document.getElementById('greet').textContent = 'hello-from-js';
  }, 10);
</script>
</body></html>
"""


@pytest.mark.asyncio
async def test_playwright_fetches_post_script_dom(tmp_path):
    from yas.crawl.fetcher import DefaultFetcher

    html_path = tmp_path / "js.html"
    html_path.write_text(JS_PAGE, encoding="utf-8")
    url = html_path.as_uri()

    from playwright.async_api import async_playwright

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    async with async_playwright() as pw:
        cdp_server = await pw.chromium.launch(
            headless=True, args=[f"--remote-debugging-port={port}"]
        )
        fetcher = DefaultFetcher(browser_ws_url=f"http://127.0.0.1:{port}")
        try:
            result = await fetcher.fetch(_Page(url), _Site(id=1, needs_browser=True))
            assert result.used_browser is True
            assert "hello-from-js" in result.html
        finally:
            await fetcher.aclose()
            await cdp_server.close()
