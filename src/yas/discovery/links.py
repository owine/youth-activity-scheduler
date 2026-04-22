"""Extract internal (same-host) <a href> links from an HTML page.

Returns (absolute_url, anchor_text) pairs; dedupes by URL preserving the
longest anchor text seen. Drops #hash-only, mailto:, tel:, and off-host links."""

from __future__ import annotations

import re
from urllib.parse import urldefrag, urljoin, urlparse

from selectolax.parser import HTMLParser

_WS_RE = re.compile(r"\s+")


def extract_internal_links(html: str, seed_url: str) -> list[tuple[str, str]]:
    """Return [(absolute_url, anchor_text)] for internal links on the page.

    Internal = same scheme+host as seed_url. Fragments are stripped. Empty or
    scheme-only hrefs (mailto:, tel:, javascript:) are dropped."""
    seed_parsed = urlparse(seed_url)
    seed_origin = (seed_parsed.scheme, seed_parsed.netloc)

    tree = HTMLParser(html)
    seen: dict[str, str] = {}   # url -> longest anchor text so far

    for a in tree.css("a"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute, _ = urldefrag(urljoin(seed_url, href))
        parsed = urlparse(absolute)
        if (parsed.scheme, parsed.netloc) != seed_origin:
            continue
        anchor = _WS_RE.sub(" ", (a.text() or "").strip())
        prior = seen.get(absolute)
        if prior is None or len(anchor) > len(prior):
            seen[absolute] = anchor

    return list(seen.items())
