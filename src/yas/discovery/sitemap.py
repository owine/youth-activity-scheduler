"""Sitemap fetcher — tries /sitemap.xml first, /sitemap_index.xml as fallback.

Follows sitemap-index references one level. Network or parse failures return []
rather than raising; discovery never hard-fails on sitemap absence."""

from __future__ import annotations

import asyncio
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import httpx

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


async def fetch_sitemap_urls(base_url: str, *, http_client: httpx.AsyncClient) -> list[str]:
    """Fetch sitemap URLs from base_url.

    Tries /sitemap.xml first. If it's absent/invalid (non-200 OR unparseable),
    tries /sitemap_index.xml. On any success, does not try the other. Follows
    sitemap-index children one level. Returns bare URLs or []."""
    for path in ("sitemap.xml", "sitemap_index.xml"):
        sitemap_url = urljoin(base_url if base_url.endswith("/") else base_url + "/", path)
        xml_bytes = await _fetch(sitemap_url, http_client)
        if xml_bytes is None:
            continue
        root = _parse_root(xml_bytes)
        if root is None:
            continue
        # Either a <urlset> (flat) or a <sitemapindex> (index).
        tag = root.tag
        if tag == f"{_SITEMAP_NS}urlset":
            return _extract_urls_from_urlset(root)
        if tag == f"{_SITEMAP_NS}sitemapindex":
            return await _fetch_index_children(root, http_client)
        # Unknown root; try the next path.
    return []


async def _fetch(url: str, http_client: httpx.AsyncClient) -> bytes | None:
    try:
        r = await http_client.get(url, timeout=10.0)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    return r.content


def _parse_root(xml_bytes: bytes) -> ET.Element | None:
    try:
        return ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None


def _extract_urls_from_urlset(root: ET.Element) -> list[str]:
    urls: list[str] = []
    for url_el in root.findall(f"{_SITEMAP_NS}url"):
        loc = url_el.find(f"{_SITEMAP_NS}loc")
        if loc is not None and loc.text:
            urls.append(loc.text.strip())
    return urls


async def _fetch_index_children(
    index_root: ET.Element, http_client: httpx.AsyncClient
) -> list[str]:
    child_sitemap_urls: list[str] = []
    for sm in index_root.findall(f"{_SITEMAP_NS}sitemap"):
        loc = sm.find(f"{_SITEMAP_NS}loc")
        if loc is not None and loc.text:
            child_sitemap_urls.append(loc.text.strip())

    results = await asyncio.gather(
        *(_fetch(u, http_client) for u in child_sitemap_urls),
        return_exceptions=False,
    )
    urls: list[str] = []
    for xml_bytes in results:
        if xml_bytes is None:
            continue
        root = _parse_root(xml_bytes)
        if root is None or root.tag != f"{_SITEMAP_NS}urlset":
            continue
        urls.extend(_extract_urls_from_urlset(root))
    return urls
