import httpx
import pytest
import respx

from yas.discovery.sitemap import fetch_sitemap_urls

_FLAT_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/programs/</loc></url>
  <url><loc>https://example.com/register/</loc></url>
</urlset>"""


_SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap-posts.xml</loc></sitemap>
</sitemapindex>"""


_CHILD_A = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/programs/summer/</loc></url>
</urlset>"""


_CHILD_B = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/news/2024/</loc></url>
</urlset>"""


@pytest.mark.asyncio
@respx.mock
async def test_flat_sitemap():
    respx.get("https://example.com/sitemap.xml").mock(
        return_value=httpx.Response(200, content=_FLAT_SITEMAP)
    )
    async with httpx.AsyncClient() as http:
        urls = await fetch_sitemap_urls("https://example.com/", http_client=http)
    assert urls == [
        "https://example.com/",
        "https://example.com/programs/",
        "https://example.com/register/",
    ]


@pytest.mark.asyncio
@respx.mock
async def test_sitemap_index_follows_one_level():
    # /sitemap.xml returns an index; children return flat sitemaps.
    respx.get("https://example.com/sitemap.xml").mock(
        return_value=httpx.Response(200, content=_SITEMAP_INDEX)
    )
    respx.get("https://example.com/sitemap-pages.xml").mock(
        return_value=httpx.Response(200, content=_CHILD_A)
    )
    respx.get("https://example.com/sitemap-posts.xml").mock(
        return_value=httpx.Response(200, content=_CHILD_B)
    )
    async with httpx.AsyncClient() as http:
        urls = await fetch_sitemap_urls("https://example.com/", http_client=http)
    assert set(urls) == {
        "https://example.com/programs/summer/",
        "https://example.com/news/2024/",
    }


@pytest.mark.asyncio
@respx.mock
async def test_sitemap_xml_missing_falls_back_to_index():
    respx.get("https://example.com/sitemap.xml").mock(return_value=httpx.Response(404))
    respx.get("https://example.com/sitemap_index.xml").mock(
        return_value=httpx.Response(200, content=_FLAT_SITEMAP)
    )
    async with httpx.AsyncClient() as http:
        urls = await fetch_sitemap_urls("https://example.com/", http_client=http)
    assert "https://example.com/programs/" in urls


@pytest.mark.asyncio
@respx.mock
async def test_both_missing_returns_empty():
    respx.get("https://example.com/sitemap.xml").mock(return_value=httpx.Response(404))
    respx.get("https://example.com/sitemap_index.xml").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as http:
        urls = await fetch_sitemap_urls("https://example.com/", http_client=http)
    assert urls == []


@pytest.mark.asyncio
@respx.mock
async def test_malformed_xml_returns_empty():
    respx.get("https://example.com/sitemap.xml").mock(
        return_value=httpx.Response(200, content="<garbage<<")
    )
    async with httpx.AsyncClient() as http:
        urls = await fetch_sitemap_urls("https://example.com/", http_client=http)
    assert urls == []


@pytest.mark.asyncio
@respx.mock
async def test_transport_error_returns_empty():
    respx.get("https://example.com/sitemap.xml").mock(side_effect=httpx.ConnectError("boom"))
    respx.get("https://example.com/sitemap_index.xml").mock(side_effect=httpx.ConnectError("boom"))
    async with httpx.AsyncClient() as http:
        urls = await fetch_sitemap_urls("https://example.com/", http_client=http)
    assert urls == []
