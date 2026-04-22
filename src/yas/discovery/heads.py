"""Per-candidate <head> scrape.

For PDFs, short-circuit without fetching (use the last path segment as title).
For HTML, httpx GET → selectolax parse → title + first <meta name="description">.
All failures (4xx/5xx/parse/transport/timeout) yield None."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser


@dataclass(frozen=True)
class HeadInfo:
    url: str
    title: str
    meta_description: str | None
    kind: Literal["html", "pdf"]
    anchor_text: str | None = None


def _is_pdf(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".pdf")


async def scrape_head(
    url: str,
    *,
    http_client: httpx.AsyncClient,
    timeout_s: int,
    anchor_text: str | None = None,
) -> HeadInfo | None:
    if _is_pdf(url):
        filename = urlparse(url).path.rsplit("/", 1)[-1] or "document.pdf"
        return HeadInfo(
            url=url,
            title=filename,
            meta_description=None,
            kind="pdf",
            anchor_text=anchor_text,
        )

    try:
        r = await http_client.get(url, timeout=timeout_s)
    except httpx.TransportError:
        return None
    if r.status_code >= 400:
        return None

    title = ""
    meta_description: str | None = None
    try:
        tree = HTMLParser(r.text)
        title_el = tree.css_first("title")
        if title_el is not None and title_el.text():
            title = title_el.text().strip()
        meta_el = tree.css_first('meta[name="description"]')
        if meta_el is not None:
            content = meta_el.attributes.get("content")
            if content:
                meta_description = content.strip()
    except Exception:
        return None

    return HeadInfo(
        url=url,
        title=title,
        meta_description=meta_description,
        kind="html",
        anchor_text=anchor_text,
    )


async def scrape_heads_concurrently(
    url_anchor_pairs: list[tuple[str, str | None]],
    *,
    http_client: httpx.AsyncClient,
    timeout_s: int,
    concurrency: int,
) -> list[HeadInfo | None]:
    """Scrape many candidates under a semaphore. Preserves input order."""
    sem = asyncio.Semaphore(concurrency)

    async def _one(url: str, anchor: str | None) -> HeadInfo | None:
        async with sem:
            return await scrape_head(
                url,
                http_client=http_client,
                timeout_s=timeout_s,
                anchor_text=anchor,
            )

    return list(
        await asyncio.gather(*(_one(u, a) for u, a in url_anchor_pairs), return_exceptions=False)
    )
