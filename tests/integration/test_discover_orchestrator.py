from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import respx

from yas.config import Settings
from yas.discovery.discover import DiscoveryError, discover_site

_FLAT_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://ysi.test/programs/summer/</loc></url>
  <url><loc>https://ysi.test/programs/fall/</loc></url>
  <url><loc>https://ysi.test/about/</loc></url>
</urlset>"""


_SEED_HTML = """<html><body>
  <a href="/programs/winter/">Winter Camp</a>
  <a href="/login">Login</a>
  <a href="/brochures/spring-2026.pdf">Spring Brochure</a>
</body></html>"""


_PAGE_HTML = """<html><head><title>{title}</title>
<meta name="description" content="{meta}"></head></html>"""


@dataclass
class _FakeSite:
    id: int = 1
    name: str = "YSI"
    base_url: str = "https://ysi.test/"


class _FakeLLM:
    def __init__(self, scored: list[dict[str, Any]]):
        self.scored = scored
        self.call_count = 0

    async def call_tool(self, *, system, user, tool_name, tool_description, input_schema, max_tokens=4096):
        self.call_count += 1
        return {"candidates": self.scored}, "fake-haiku", 0.005


async def _base_settings(monkeypatch) -> Settings:
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.asyncio
@respx.mock
async def test_happy_path_with_pdf_and_link_union(monkeypatch):
    respx.get("https://ysi.test/").mock(return_value=httpx.Response(200, text=_SEED_HTML))
    respx.get("https://ysi.test/sitemap.xml").mock(return_value=httpx.Response(200, content=_FLAT_SITEMAP))
    # Head fetches (PDFs short-circuit without HTTP).
    for url, title, meta in [
        ("https://ysi.test/programs/summer/", "Summer Camps 2026", "Ages 5-12"),
        ("https://ysi.test/programs/fall/", "Fall Clinics 2026", "Weekend clinics"),
        ("https://ysi.test/about/", "About YSI", "Our mission"),
        ("https://ysi.test/programs/winter/", "Winter Camp 2026", "December"),
    ]:
        respx.get(url).mock(return_value=httpx.Response(200, text=_PAGE_HTML.format(title=title, meta=meta)))

    scored = [
        {"url": "https://ysi.test/programs/summer/", "score": 0.95, "reason": "Clear program detail"},
        {"url": "https://ysi.test/programs/fall/", "score": 0.80, "reason": "Program details with ages"},
        {"url": "https://ysi.test/programs/winter/", "score": 0.70, "reason": "Camp with dates"},
        {"url": "https://ysi.test/about/", "score": 0.10, "reason": "About page, not program"},
        {"url": "https://ysi.test/brochures/spring-2026.pdf", "score": 0.65, "reason": "PDF brochure"},
    ]
    llm = _FakeLLM(scored)
    settings = await _base_settings(monkeypatch)
    async with httpx.AsyncClient() as http:
        result = await discover_site(
            site=_FakeSite(), http_client=http, llm_client=llm, settings=settings,
        )
    urls = {c.url for c in result.candidates}
    assert "https://ysi.test/programs/summer/" in urls
    assert "https://ysi.test/programs/fall/" in urls
    # about/ filtered by min_score
    assert "https://ysi.test/about/" not in urls
    # pdf surfaces with kind
    pdf = next(c for c in result.candidates if c.kind == "pdf")
    assert pdf.title == "spring-2026.pdf"
    # stats populated
    assert result.stats.sitemap_urls == 3
    assert result.stats.link_urls >= 2
    assert result.stats.returned == len(result.candidates)


@pytest.mark.asyncio
@respx.mock
async def test_seed_fetch_failure_raises(monkeypatch):
    respx.get("https://ysi.test/").mock(return_value=httpx.Response(502))
    llm = _FakeLLM([])
    settings = await _base_settings(monkeypatch)
    async with httpx.AsyncClient() as http:
        with pytest.raises(DiscoveryError):
            await discover_site(
                site=_FakeSite(), http_client=http, llm_client=llm, settings=settings,
            )


@pytest.mark.asyncio
@respx.mock
async def test_sitemap_missing_still_works_from_links(monkeypatch):
    respx.get("https://ysi.test/").mock(return_value=httpx.Response(200, text=_SEED_HTML))
    respx.get("https://ysi.test/sitemap.xml").mock(return_value=httpx.Response(404))
    respx.get("https://ysi.test/sitemap_index.xml").mock(return_value=httpx.Response(404))
    respx.get("https://ysi.test/programs/winter/").mock(
        return_value=httpx.Response(200, text=_PAGE_HTML.format(title="Winter", meta="cold"))
    )
    llm = _FakeLLM([
        {"url": "https://ysi.test/programs/winter/", "score": 0.9, "reason": "program"}
    ])
    settings = await _base_settings(monkeypatch)
    async with httpx.AsyncClient() as http:
        result = await discover_site(
            site=_FakeSite(), http_client=http, llm_client=llm, settings=settings,
        )
    assert len(result.candidates) == 1
    assert result.candidates[0].url == "https://ysi.test/programs/winter/"


@pytest.mark.asyncio
@respx.mock
async def test_empty_after_threshold_still_200(monkeypatch):
    respx.get("https://ysi.test/").mock(return_value=httpx.Response(200, text="<html><body></body></html>"))
    respx.get("https://ysi.test/sitemap.xml").mock(return_value=httpx.Response(404))
    respx.get("https://ysi.test/sitemap_index.xml").mock(return_value=httpx.Response(404))
    llm = _FakeLLM([])
    settings = await _base_settings(monkeypatch)
    async with httpx.AsyncClient() as http:
        result = await discover_site(
            site=_FakeSite(), http_client=http, llm_client=llm, settings=settings,
        )
    assert result.candidates == []
    assert result.stats.returned == 0
