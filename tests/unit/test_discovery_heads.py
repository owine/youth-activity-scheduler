import asyncio

import httpx
import pytest
import respx

from yas.discovery.heads import HeadInfo, scrape_head, scrape_heads_concurrently  # noqa: F401

_HTML = """<!doctype html>
<html><head>
  <title>Summer Camps 2026 — Example Org</title>
  <meta name="description" content="Summer camp programs for ages 5-12.">
</head><body><p>ignored</p></body></html>"""


@pytest.mark.asyncio
@respx.mock
async def test_scrape_head_parses_title_and_meta():
    respx.get("https://ex.com/summer").mock(return_value=httpx.Response(200, text=_HTML))
    async with httpx.AsyncClient() as http:
        info = await scrape_head("https://ex.com/summer", http_client=http, timeout_s=5)
    assert info is not None
    assert info.url == "https://ex.com/summer"
    assert info.title == "Summer Camps 2026 — Example Org"
    assert info.meta_description == "Summer camp programs for ages 5-12."
    assert info.kind == "html"
    assert info.anchor_text is None


@pytest.mark.asyncio
@respx.mock
async def test_scrape_head_preserves_anchor_text_when_provided():
    respx.get("https://ex.com/summer").mock(return_value=httpx.Response(200, text=_HTML))
    async with httpx.AsyncClient() as http:
        info = await scrape_head(
            "https://ex.com/summer",
            http_client=http,
            timeout_s=5,
            anchor_text="Our Summer Camps",
        )
    assert info is not None
    assert info.anchor_text == "Our Summer Camps"


@pytest.mark.asyncio
@respx.mock
async def test_scrape_head_4xx_returns_none():
    respx.get("https://ex.com/missing").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as http:
        info = await scrape_head("https://ex.com/missing", http_client=http, timeout_s=5)
    assert info is None


@pytest.mark.asyncio
@respx.mock
async def test_scrape_head_5xx_returns_none():
    respx.get("https://ex.com/oops").mock(return_value=httpx.Response(502))
    async with httpx.AsyncClient() as http:
        info = await scrape_head("https://ex.com/oops", http_client=http, timeout_s=5)
    assert info is None


@pytest.mark.asyncio
@respx.mock
async def test_scrape_head_transport_error_returns_none():
    respx.get("https://ex.com/boom").mock(side_effect=httpx.ConnectError("nope"))
    async with httpx.AsyncClient() as http:
        info = await scrape_head("https://ex.com/boom", http_client=http, timeout_s=5)
    assert info is None


@pytest.mark.asyncio
async def test_scrape_head_pdf_short_circuits():
    # No network call expected for PDFs.
    async with httpx.AsyncClient() as http:
        info = await scrape_head(
            "https://ex.com/brochures/spring-2026.pdf",
            http_client=http,
            timeout_s=5,
        )
    assert info is not None
    assert info.kind == "pdf"
    assert info.title == "spring-2026.pdf"
    assert info.meta_description is None


@pytest.mark.asyncio
@respx.mock
async def test_missing_title_defaults_to_empty_string():
    html = "<html><head></head><body>body</body></html>"
    respx.get("https://ex.com/").mock(return_value=httpx.Response(200, text=html))
    async with httpx.AsyncClient() as http:
        info = await scrape_head("https://ex.com/", http_client=http, timeout_s=5)
    assert info is not None
    assert info.title == ""
    assert info.meta_description is None


@pytest.mark.asyncio
@respx.mock
async def test_scrape_heads_concurrently_respects_semaphore():
    """Fire 30 overlapping fetches through a semaphore of 3; assert peak
    concurrency never exceeds 3."""
    peak = {"count": 0, "max": 0}

    async def slow_handler(request):
        peak["count"] += 1
        peak["max"] = max(peak["max"], peak["count"])
        await asyncio.sleep(0.05)
        peak["count"] -= 1
        return httpx.Response(200, text=_HTML)

    urls = [f"https://ex.com/p{i}" for i in range(30)]
    for u in urls:
        respx.get(u).mock(side_effect=slow_handler)

    async with httpx.AsyncClient() as http:
        results = await scrape_heads_concurrently(
            [(u, None) for u in urls],
            http_client=http,
            timeout_s=5,
            concurrency=3,
        )
    assert len(results) == 30
    assert all(r is not None for r in results)
    assert peak["max"] <= 3
