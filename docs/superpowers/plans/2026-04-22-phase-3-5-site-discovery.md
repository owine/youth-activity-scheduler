# Phase 3.5 — Site Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use @superpowers:subagent-driven-development (recommended) or @superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Follow @superpowers:test-driven-development throughout. Apply @superpowers:verification-before-completion before marking any task done.

**Goal:** Register a site with only a base URL; `POST /api/sites/{id}/discover` fans out to `/sitemap.xml` + internal links, scrapes titles/meta descriptions from candidates, and asks Claude Haiku to rank them as "program detail page" or not. Returns a ranked list (HTML + PDF) for the caller to add via the existing `POST /api/sites/{id}/pages`. PDFs are surfaced with a distinguishing `kind="pdf"` but not yet trackable — schema rejects them.

**Architecture:** New `src/yas/discovery/` package: pure filters + sitemap/link extractors + httpx head scraper + tool-use classifier + orchestrator. New read-only route on the existing sites router. No worker changes, no caching, sync endpoint.

**Tech Stack:** Python 3.12, httpx, selectolax (Phase 2), Anthropic Haiku (tool use, reused from Phase 2 extractor), Pydantic V2, pytest + respx.

**Reference spec:** `docs/superpowers/specs/2026-04-22-phase-3-5-site-discovery-design.md`.

---

## Deliverables (phase exit criteria)

- `uv run pytest` green with all new tests including the named must-haves
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` clean
- Docker Compose (with macOS overlay locally) end-to-end:
  - `POST /api/sites` with `base_url="https://ysifc.com/"` and no `pages`
  - `POST /api/sites/1/discover` returns a `DiscoveryResult` with HTML program-like pages (and any PDFs surfaced with `kind="pdf"`)
  - Caller adds one HTML candidate via existing `POST /api/sites/{id}/pages` → scheduler crawls → offerings populate → `GET /api/matches?kid_id=1` shows real matches
  - `POST /api/sites/{id}/pages {"url":"...","kind":"pdf"}` → 422 with clear error
- Discovery call logs one structured line including `input_tokens`, `output_tokens`, `cost_usd`; typical cost under $0.05

## Conventions

- **Branch:** `phase-3-5-site-discovery` off `main`. Final merge with `--no-ff`.
- TDD: failing test → verify fail → implement → verify pass → commit.
- **EXACT file paths in `git add`** — never directory-level (Phase 2+3 interleaving lessons).
- Pydantic V2 — `ConfigDict(extra="forbid")` on write schemas.
- mypy strict — if a `# type: ignore[...]` is flagged unused, remove it.
- **Commits unsigned in this session is accepted.** If `git commit` fails for any OTHER reason, report BLOCKED; don't retry.

---

## File structure delta

```
src/yas/discovery/                        # NEW
├── __init__.py
├── filters.py                            # is_junk(url) — pure sync
├── sitemap.py                            # async fetch_sitemap_urls
├── links.py                              # extract_internal_links — sync
├── heads.py                              # HeadInfo dataclass + async scrape_head
├── classifier.py                         # Pydantic schemas + prompt + classify_candidates
└── discover.py                           # DiscoveryResult + async discover_site orchestrator

src/yas/web/routes/
├── discover_schemas.py                   # NEW — request/response shapes
└── sites.py                              # MODIFIED — add /discover endpoint
└── sites_schemas.py                      # MODIFIED — PageCreate.kind becomes Literal

src/yas/config.py                         # MODIFIED — 6 new settings
.env.example                              # MODIFIED

tests/
├── unit/
│   ├── test_discovery_filters.py
│   ├── test_discovery_sitemap.py
│   ├── test_discovery_links.py
│   ├── test_discovery_heads.py
│   └── test_discovery_classifier.py
└── integration/
    └── test_api_discover.py
```

---

## Task 1 — Branch, config additions, PageCreate.kind tightening

**Files:**
- Modify: `src/yas/config.py`
- Modify: `.env.example`
- Modify: `src/yas/web/routes/sites_schemas.py` (PageCreate.kind → Literal)
- Modify: `tests/unit/test_config.py` (new tests)
- Modify: `tests/integration/test_api_sites.py` (pdf-kind rejection test)

- [ ] **Step 1: Cut the branch**

```bash
cd /Users/owine/Git/youth-activity-scheduler
git checkout main
git checkout -b phase-3-5-site-discovery
```

- [ ] **Step 2: Add config tests (failing)**

Append to `tests/unit/test_config.py`:

```python
def test_discovery_settings_defaults(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = _settings()
    assert s.discovery_enabled is True
    assert s.discovery_max_candidates == 50
    assert s.discovery_max_returned == 20
    assert s.discovery_min_score == 0.5
    assert s.discovery_head_fetch_concurrency == 10
    assert s.discovery_head_fetch_timeout_s == 10


def test_discovery_settings_overrides(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("YAS_DISCOVERY_MAX_CANDIDATES", "30")
    monkeypatch.setenv("YAS_DISCOVERY_MIN_SCORE", "0.7")
    s = _settings()
    assert s.discovery_max_candidates == 30
    assert s.discovery_min_score == 0.7
```

Run: `uv run pytest tests/unit/test_config.py -v` — expect failures.

- [ ] **Step 3: Add config fields**

Append to `Settings` class in `src/yas/config.py`:

```python
    # Site discovery
    discovery_enabled: bool = True
    discovery_max_candidates: int = 50
    discovery_max_returned: int = 20
    discovery_min_score: float = 0.5
    discovery_head_fetch_concurrency: int = 10
    discovery_head_fetch_timeout_s: int = 10
```

- [ ] **Step 4: Update `.env.example`**

Append:
```
# Site discovery
# YAS_DISCOVERY_ENABLED=true
# YAS_DISCOVERY_MAX_CANDIDATES=50
# YAS_DISCOVERY_MAX_RETURNED=20
# YAS_DISCOVERY_MIN_SCORE=0.5
# YAS_DISCOVERY_HEAD_FETCH_CONCURRENCY=10
# YAS_DISCOVERY_HEAD_FETCH_TIMEOUT_S=10
```

- [ ] **Step 5: Tighten `PageCreate.kind` to Literal**

Open `src/yas/web/routes/sites_schemas.py`. Find `PageCreate`. Change its `kind` field from `str` to a `Literal`:

```python
from typing import Literal  # ensure imported

class PageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: HttpUrl
    kind: Literal["schedule", "registration", "list", "other"] = "schedule"
```

- [ ] **Step 6: Add a failing test for PDF rejection**

Append to `tests/integration/test_api_sites.py`:

```python
@pytest.mark.asyncio
async def test_add_page_rejects_pdf_kind(client):
    c, _ = client
    created = await c.post("/api/sites", json={"name": "X", "base_url": "https://x/"})
    sid = created.json()["id"]
    r = await c.post(
        f"/api/sites/{sid}/pages",
        json={"url": "https://x/schedule.pdf", "kind": "pdf"},
    )
    assert r.status_code == 422
```

- [ ] **Step 7: Run gates**

```bash
uv run pytest tests/unit/test_config.py tests/integration/test_api_sites.py -v
uv run pytest
uv run ruff check .
uv run mypy src
```

All green.

- [ ] **Step 8: Commit**

```bash
git add src/yas/config.py .env.example \
    src/yas/web/routes/sites_schemas.py \
    tests/unit/test_config.py tests/integration/test_api_sites.py
git commit -m "chore: add phase-3.5 config; tighten PageCreate.kind to Literal (rejects pdf)"
```

---

## Task 2 — Junk URL filter

**Files:**
- Create: `src/yas/discovery/__init__.py` (empty)
- Create: `src/yas/discovery/filters.py`
- Create: `tests/unit/test_discovery_filters.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_discovery_filters.py`:

```python
import pytest

from yas.discovery.filters import is_junk


# Each: (url, expected_is_junk)
_CASES = [
    # Path prefixes — rejected
    ("https://example.com/wp-admin/", True),
    ("https://example.com/wp-content/uploads/foo.png", True),
    ("https://example.com/wp-json/api/v2", True),
    ("https://example.com/feed/", True),
    ("https://example.com/author/jane/", True),
    ("https://example.com/tag/soccer/", True),
    ("https://example.com/category/news/", True),
    ("https://example.com/comments/feed", True),
    ("https://example.com/login", True),
    ("https://example.com/account", True),
    ("https://example.com/cart", True),
    ("https://example.com/checkout", True),
    # Query signatures — rejected
    ("https://example.com/?replytocom=123", True),
    ("https://example.com/?s=search+term", True),
    # File extensions — rejected
    ("https://example.com/sitemap.xml", True),
    ("https://example.com/logo.png", True),
    ("https://example.com/hero.jpg", True),
    ("https://example.com/icon.svg", True),
    ("https://example.com/style.css", True),
    ("https://example.com/app.js", True),
    ("https://example.com/font.woff2", True),
    # PDFs — ALLOWED
    ("https://example.com/spring-2026.pdf", False),
    ("https://example.com/programs/brochure.PDF", False),
    # Real-looking program pages — ALLOWED
    ("https://example.com/programs/summer-camps/", False),
    ("https://example.com/register", False),
    ("https://example.com/schedule-2026", False),
    ("https://example.com/", False),
]


@pytest.mark.parametrize("url,expected", _CASES)
def test_is_junk(url, expected):
    assert is_junk(url) is expected
```

Run: `uv run pytest tests/unit/test_discovery_filters.py -v` — expect ImportError.

- [ ] **Step 2: Implement `src/yas/discovery/__init__.py`** (empty file)

- [ ] **Step 3: Implement `src/yas/discovery/filters.py`**

```python
"""Deterministic junk-URL filter for discovery candidates.

Filters out navigation/boilerplate and non-document URLs before the LLM
classifier sees them, saving tokens on predictable garbage. PDFs are NOT
filtered — discovery surfaces them with kind="pdf" for visibility.
"""

from __future__ import annotations

from urllib.parse import urlparse

_PATH_PREFIX_REJECTS: tuple[str, ...] = (
    "/wp-admin",
    "/wp-content",
    "/wp-json",
    "/wp-login",
    "/feed",
    "/author/",
    "/tag/",
    "/category/",
    "/comments/",
    "/comments",
    "/login",
    "/logout",
    "/account",
    "/cart",
    "/checkout",
)

_QUERY_SIGNATURES: tuple[str, ...] = ("replytocom=", "s=")

_REJECTED_EXTENSIONS: tuple[str, ...] = (
    ".xml",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".css",
    ".js",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
)


def is_junk(url: str) -> bool:
    """True if URL should be dropped before classification."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    if any(path.startswith(p) for p in _PATH_PREFIX_REJECTS):
        return True
    if any(path.endswith(ext) for ext in _REJECTED_EXTENSIONS):
        return True
    query = parsed.query
    if query and any(sig in query for sig in _QUERY_SIGNATURES):
        return True
    return False
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/unit/test_discovery_filters.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/discovery/__init__.py src/yas/discovery/filters.py tests/unit/test_discovery_filters.py
git commit -m "feat(discovery): add deterministic junk-URL filter (pdfs allowed)"
```

---

## Task 3 — Sitemap fetch + parse

**Files:**
- Create: `src/yas/discovery/sitemap.py`
- Create: `tests/unit/test_discovery_sitemap.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_discovery_sitemap.py`:

```python
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
```

Run: `uv run pytest tests/unit/test_discovery_sitemap.py -v` — expect ImportError.

- [ ] **Step 2: Implement `src/yas/discovery/sitemap.py`**

```python
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
    except httpx.TransportError:
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


async def _fetch_index_children(index_root: ET.Element, http_client: httpx.AsyncClient) -> list[str]:
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
```

- [ ] **Step 3: Run + commit**

```bash
uv run pytest tests/unit/test_discovery_sitemap.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/discovery/sitemap.py tests/unit/test_discovery_sitemap.py
git commit -m "feat(discovery): add sitemap fetcher with index-follow fallback"
```

---

## Task 4 — Internal link extractor

**Files:**
- Create: `src/yas/discovery/links.py`
- Create: `tests/unit/test_discovery_links.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_discovery_links.py`:

```python
from yas.discovery.links import extract_internal_links


def test_extracts_same_host_links_with_anchor_text():
    html = """<html><body>
      <a href="/programs/">Our Programs</a>
      <a href="/register/">Register</a>
      <a href="https://example.com/schedule">Schedule</a>
    </body></html>"""
    pairs = extract_internal_links(html, "https://example.com/")
    urls = {u for u, _ in pairs}
    assert urls == {
        "https://example.com/programs/",
        "https://example.com/register/",
        "https://example.com/schedule",
    }


def test_drops_external_links():
    html = """<html><body>
      <a href="/programs/">Programs</a>
      <a href="https://other.com/whatever">Other</a>
    </body></html>"""
    pairs = extract_internal_links(html, "https://example.com/")
    urls = [u for u, _ in pairs]
    assert urls == ["https://example.com/programs/"]


def test_drops_hash_and_mailto():
    html = """<html><body>
      <a href="#section">Anchor</a>
      <a href="mailto:a@b.com">Email</a>
      <a href="tel:123">Call</a>
      <a href="/real/">Real</a>
    </body></html>"""
    pairs = extract_internal_links(html, "https://example.com/")
    urls = [u for u, _ in pairs]
    assert urls == ["https://example.com/real/"]


def test_preserves_longest_anchor_text_on_dedup():
    html = """<html><body>
      <a href="/programs/">Programs</a>
      <a href="/programs/">Browse Our Summer Programs</a>
    </body></html>"""
    pairs = extract_internal_links(html, "https://example.com/")
    assert pairs == [("https://example.com/programs/", "Browse Our Summer Programs")]


def test_strips_fragment():
    html = '<a href="/programs/#toc">Programs</a>'
    pairs = extract_internal_links(html, "https://example.com/")
    urls = [u for u, _ in pairs]
    assert urls == ["https://example.com/programs/"]


def test_handles_missing_href():
    html = """<html><body>
      <a>No href</a>
      <a href="">Empty</a>
      <a href="/real/">Real</a>
    </body></html>"""
    pairs = extract_internal_links(html, "https://example.com/")
    urls = [u for u, _ in pairs]
    assert urls == ["https://example.com/real/"]


def test_collapses_anchor_whitespace():
    html = '<a href="/x">  Summer  \n Camps   </a>'
    pairs = extract_internal_links(html, "https://example.com/")
    assert pairs == [("https://example.com/x", "Summer Camps")]
```

Run: `uv run pytest tests/unit/test_discovery_links.py -v` — expect ImportError.

- [ ] **Step 2: Implement `src/yas/discovery/links.py`**

```python
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
```

- [ ] **Step 3: Run + commit**

```bash
uv run pytest tests/unit/test_discovery_links.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/discovery/links.py tests/unit/test_discovery_links.py
git commit -m "feat(discovery): add internal link extractor via selectolax"
```

---

## Task 5 — Head scraper + HeadInfo

**Files:**
- Create: `src/yas/discovery/heads.py`
- Create: `tests/unit/test_discovery_heads.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_discovery_heads.py`:

```python
import asyncio

import httpx
import pytest
import respx

from yas.discovery.heads import HeadInfo, scrape_head, scrape_heads_concurrently


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
            "https://ex.com/summer", http_client=http, timeout_s=5,
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
            "https://ex.com/brochures/spring-2026.pdf", http_client=http, timeout_s=5,
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
            [(u, None) for u in urls], http_client=http, timeout_s=5, concurrency=3,
        )
    assert len(results) == 30
    assert all(r is not None for r in results)
    assert peak["max"] <= 3
```

Run: `uv run pytest tests/unit/test_discovery_heads.py -v` — expect ImportError.

- [ ] **Step 2: Implement `src/yas/discovery/heads.py`**

```python
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
    except Exception:  # noqa: BLE001
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
                url, http_client=http_client, timeout_s=timeout_s, anchor_text=anchor,
            )

    return list(
        await asyncio.gather(*(_one(u, a) for u, a in url_anchor_pairs), return_exceptions=False)
    )
```

- [ ] **Step 3: Run + commit**

```bash
uv run pytest tests/unit/test_discovery_heads.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/discovery/heads.py tests/unit/test_discovery_heads.py
git commit -m "feat(discovery): add head scraper with PDF short-circuit and semaphore"
```

---

## Task 6 — LLM classifier

**Files:**
- Create: `src/yas/discovery/classifier.py`
- Create: `tests/unit/test_discovery_classifier.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_discovery_classifier.py`:

```python
from dataclasses import dataclass

import pytest

from yas.discovery.classifier import (
    ClassificationError,
    ScoredCandidate,
    build_classifier_prompt,
    classify_candidates,
)
from yas.discovery.heads import HeadInfo
from yas.llm.client import ExtractionResult


def _head(url: str, title: str = "", meta: str | None = None, kind: str = "html",
          anchor: str | None = None) -> HeadInfo:
    return HeadInfo(url=url, title=title, meta_description=meta, kind=kind, anchor_text=anchor)


def test_prompt_mentions_html_and_pdf_and_anchor_text():
    system, user = build_classifier_prompt(
        [_head("https://x/a", "Summer Camps"),
         _head("https://x/b.pdf", "spring.pdf", kind="pdf"),
         _head("https://x/c", "Programs", anchor="Our Programs")],
        site_name="X",
    )
    assert "report_candidates" in system
    assert "program or schedule" in system.lower()
    # User payload has each URL/title.
    assert "https://x/a" in user
    assert "Summer Camps" in user
    assert "https://x/b.pdf" in user
    assert "pdf" in user.lower()
    assert "https://x/c" in user
    assert "Our Programs" in user


class _FakeClient:
    """Duck-typed to satisfy the minimal surface classifier uses on AnthropicClient."""

    def __init__(self, canned_input: dict):
        self.canned = canned_input

    async def call_tool(self, *, system: str, user: str, tool_schema: dict) -> tuple[dict, str, float]:
        # Return (tool_input, model_name, cost_usd)
        return self.canned, "fake-haiku", 0.002


@pytest.mark.asyncio
async def test_classify_filters_hallucinated_urls(monkeypatch):
    candidates = [_head("https://x/a", "A"), _head("https://x/b", "B")]
    canned = {
        "candidates": [
            {"url": "https://x/a", "score": 0.9, "reason": "looks like program page"},
            {"url": "https://x/HALLUCINATED", "score": 1.0, "reason": "nonexistent URL"},
        ],
    }
    client = _FakeClient(canned)
    results = await classify_candidates(candidates, llm_client=client, site_name="X")
    # Hallucinated URL dropped; a->0.9 kept, b->0.0 implicit default
    urls = {r.url: r.score for r in results}
    assert urls == {"https://x/a": 0.9, "https://x/b": 0.0}


@pytest.mark.asyncio
async def test_classify_scores_zero_for_missing_urls():
    candidates = [_head("https://x/a"), _head("https://x/b"), _head("https://x/c")]
    canned = {
        "candidates": [
            {"url": "https://x/a", "score": 0.5, "reason": "maybe"},
        ],
    }
    client = _FakeClient(canned)
    results = await classify_candidates(candidates, llm_client=client, site_name="X")
    score_by_url = {r.url: r.score for r in results}
    assert score_by_url["https://x/a"] == 0.5
    assert score_by_url["https://x/b"] == 0.0
    assert score_by_url["https://x/c"] == 0.0


@pytest.mark.asyncio
async def test_classify_raises_on_invalid_tool_input():
    candidates = [_head("https://x/a")]
    # Missing required "reason" field and score out of range.
    bad = {"candidates": [{"url": "https://x/a", "score": 5.0}]}
    client = _FakeClient(bad)
    with pytest.raises(ClassificationError):
        await classify_candidates(candidates, llm_client=client, site_name="X")


@pytest.mark.asyncio
async def test_classify_empty_input_returns_empty():
    client = _FakeClient({"candidates": []})
    results = await classify_candidates([], llm_client=client, site_name="X")
    assert results == []


def test_scored_candidate_validates_score_range():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ScoredCandidate(url="https://x", score=1.5, reason="bad")
```

Run: `uv run pytest tests/unit/test_discovery_classifier.py -v` — expect ImportError.

- [ ] **Step 2: Extend `AnthropicClient` (MINIMAL)**

The existing `AnthropicClient` in `src/yas/llm/client.py` exposes `extract_offerings(...)`. Discovery needs a more general tool-use call. Add a new method `call_tool` on `AnthropicClient` (and the protocol) that discovery uses, OR a thin classifier-side wrapper that constructs the tool call directly.

**Do it classifier-side** — keep `AnthropicClient` single-purpose per its existing design. Introduce a small protocol `ClassifierLLMClient` in `classifier.py` defining just the method the classifier needs; the real call is implemented inline against `self._client.messages.create(...)`.

Alternative that's cleaner: add a generic `call_tool(system, user, tool_name, input_schema) -> tuple[dict, str, float]` to `AnthropicClient` and reuse it for both extraction and classification. **Go with this** — the extractor can migrate later if desired, but for now the classifier uses the new method.

Edit `src/yas/llm/client.py`:

1. Add a new method `async def call_tool(self, *, system: str, user: str, tool_name: str, tool_description: str, input_schema: dict[str, Any], max_tokens: int = 4096) -> tuple[dict[str, Any], str, float]`. Extract the helper logic out of `extract_offerings` (tool construction, create() call, tool-input extraction, cost computation); have both methods call it. Keep `extract_offerings` behavior identical — same `ExtractionError` raised, same return value.

2. **Extend the `LLMClient` Protocol** in the same file to also declare `call_tool` alongside `extract_offerings`. This keeps `AppState.llm: LLMClient | None` type-clean when the discovery route consumes it via `call_tool`.

```python
class LLMClient(Protocol):
    async def extract_offerings(
        self, *, html: str, url: str, site_name: str
    ) -> ExtractionResult: ...

    async def call_tool(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], str, float]: ...
```

The `FakeLLMClient` in `tests/fakes/llm.py` must also gain a `call_tool` stub so it continues to satisfy the protocol (mypy strict will catch this). Minimal stub: `async def call_tool(self, **_) -> tuple[dict[str, Any], str, float]: return {}, "fake", 0.0` — tests that exercise discovery should use a different fake (covered in Task 6's test file and Task 7's orchestrator tests, which define their own `_FakeLLM` with a real `call_tool`).

Minimal refactor pattern:

```python
# Pseudo-code, apply to actual file:
async def _call_messages(self, *, system, user, tool_name, tool_description, input_schema, max_tokens):
    tool = {"name": tool_name, "description": tool_description, "input_schema": input_schema}
    msg = await self._client.messages.create(
        model=self._model,
        max_tokens=max_tokens,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user}],
    )
    tool_input = _find_tool_input(msg, tool_name)
    if tool_input is None:
        raise _ToolMissingError(_dump_msg(msg), stop_reason=getattr(msg, "stop_reason", "?"))
    cost = _estimate_cost_usd(msg)
    model = getattr(msg, "model", self._model)
    return tool_input, model, cost


async def call_tool(self, *, system, user, tool_name, tool_description, input_schema, max_tokens=4096):
    # Public wrapper. Propagates _ToolMissingError as a generic ToolCallError.
    try:
        return await self._call_messages(...)
    except _ToolMissingError as exc:
        raise ToolCallError(raw=exc.raw, detail=f"model stopped without calling {tool_name} (stop_reason={exc.stop_reason})") from exc
```

`_find_tool_input` already exists; parameterize it to take the tool name. Add `ToolCallError` alongside `ExtractionError` in `client.py`. Update `extract_offerings` to call `_call_messages` with `tool_name="report_offerings"`, description, and `ExtractionResponse.model_json_schema()`; catch the same error shape and re-raise as `ExtractionError` for backwards compatibility.

Run the existing Phase 2 LLM client tests afterward to confirm no regression:

```bash
uv run pytest tests/unit/test_llm_client.py -v
```

All should still pass.

- [ ] **Step 3: Implement `src/yas/discovery/classifier.py`**

```python
"""LLM classifier that scores discovery candidates 0-1 for program-detail fit.

Uses Claude Haiku via the existing AnthropicClient.call_tool path with a
discovery-specific prompt and Pydantic schema. Hallucinated URLs are
dropped; missing input URLs implicitly score 0.0."""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yas.discovery.heads import HeadInfo
from yas.logging import get_logger

log = get_logger("yas.discovery.classifier")


class ScoredCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str


class ClassificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[ScoredCandidate]


class ClassificationError(Exception):
    def __init__(self, raw: str, detail: str):
        super().__init__(detail)
        self.raw = raw
        self.detail = detail


class ClassifierLLMClient(Protocol):
    async def call_tool(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], str, float]: ...


_SYSTEM = """You classify pages on a youth activity / sports / enrichment site.
Given a list of URLs with titles, meta descriptions, and kind (html or pdf),
identify pages that contain actual program or schedule DETAIL — dates, ages,
times, prices, registration info.

Reject: navigation/landing pages, "our programs" overviews without details,
registration routers (the /register/ page itself), news/blog posts, team
rosters, "about us" / "contact" / "policies" pages, login/account pages,
homepages unless they clearly ARE the schedule.

For each URL, assign a score in [0.0, 1.0] and a one-line reason. Prefer
precision over recall — missing a page is better than recommending a bad one.

Call `report_candidates` with your ranked list. Do not invent URLs not in
the input."""


def build_classifier_prompt(
    candidates: list[HeadInfo], *, site_name: str
) -> tuple[str, str]:
    items = [
        {
            "url": c.url,
            "title": c.title,
            "meta": c.meta_description,
            "kind": c.kind,
            "anchor_text": c.anchor_text,
        }
        for c in candidates
    ]
    user = (
        f"Site: {site_name}\n\n"
        f"Candidates (JSON):\n{json.dumps(items, indent=2, ensure_ascii=False)}"
    )
    return _SYSTEM, user


def _tool_schema() -> dict[str, Any]:
    return ClassificationResponse.model_json_schema()


async def classify_candidates(
    candidates: list[HeadInfo],
    *,
    llm_client: ClassifierLLMClient,
    site_name: str,
) -> list[ScoredCandidate]:
    if not candidates:
        return []

    system, user = build_classifier_prompt(candidates, site_name=site_name)
    tool_input, model, cost_usd = await llm_client.call_tool(
        system=system,
        user=user,
        tool_name="report_candidates",
        tool_description="Report the scored list of discovery candidates.",
        input_schema=_tool_schema(),
    )
    try:
        parsed = ClassificationResponse.model_validate(tool_input)
    except ValidationError as exc:
        raise ClassificationError(raw=str(tool_input), detail=str(exc)) from exc

    log.info(
        "discovery.classifier.call",
        model=model,
        cost_usd=cost_usd,
        candidates_in=len(candidates),
        scored_out=len(parsed.candidates),
    )

    valid_urls = {c.url for c in candidates}
    by_url: dict[str, ScoredCandidate] = {}
    for sc in parsed.candidates:
        if sc.url not in valid_urls:
            log.warning("discovery.classifier.hallucinated_url", url=sc.url)
            continue
        by_url[sc.url] = sc

    # Fill zero-score defaults for any input URL the model didn't rate.
    result: list[ScoredCandidate] = []
    for c in candidates:
        existing = by_url.get(c.url)
        if existing is not None:
            result.append(existing)
        else:
            result.append(ScoredCandidate(url=c.url, score=0.0, reason="not scored"))
    return result
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/unit/test_discovery_classifier.py tests/unit/test_llm_client.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/llm/client.py src/yas/discovery/classifier.py tests/unit/test_discovery_classifier.py
git commit -m "feat(discovery): add LLM classifier with generic call_tool on AnthropicClient"
```

---

## Task 7 — Discovery orchestrator

**Files:**
- Create: `src/yas/discovery/discover.py`
- Create: `tests/integration/test_discover_orchestrator.py`

- [ ] **Step 1: Failing integration test**

`tests/integration/test_discover_orchestrator.py`:

```python
from dataclasses import dataclass, field
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
```

Run: `uv run pytest tests/integration/test_discover_orchestrator.py -v` — expect ImportError.

- [ ] **Step 2: Implement `src/yas/discovery/discover.py`**

```python
"""Orchestrator: seed → sitemap + links → filter → heads → classify → filter + cap."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from yas.config import Settings
from yas.discovery.classifier import ClassificationError, classify_candidates
from yas.discovery.filters import is_junk
from yas.discovery.heads import HeadInfo, scrape_heads_concurrently
from yas.discovery.links import extract_internal_links
from yas.discovery.sitemap import fetch_sitemap_urls
from yas.logging import get_logger

log = get_logger("yas.discovery")


@dataclass(frozen=True)
class DiscoveryStats:
    sitemap_urls: int
    link_urls: int
    filtered_junk: int
    fetched_heads: int
    classified: int
    returned: int


@dataclass(frozen=True)
class DiscoveryCandidate:
    url: str
    title: str
    kind: Literal["html", "pdf"]
    score: float
    reason: str


@dataclass(frozen=True)
class DiscoveryResult:
    site_id: int
    seed_url: str
    stats: DiscoveryStats
    candidates: list[DiscoveryCandidate] = field(default_factory=list)


class DiscoveryError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


async def discover_site(
    *,
    site: Any,        # duck-typed: needs .id, .name, .base_url
    http_client: httpx.AsyncClient,
    llm_client: Any,  # duck-typed: ClassifierLLMClient
    settings: Settings,
    min_score: float | None = None,
    max_candidates: int | None = None,
) -> DiscoveryResult:
    min_score_f = min_score if min_score is not None else settings.discovery_min_score
    max_out = max_candidates if max_candidates is not None else settings.discovery_max_returned

    # 1. Seed fetch.
    try:
        r = await http_client.get(site.base_url, timeout=settings.discovery_head_fetch_timeout_s)
    except httpx.TransportError as exc:
        raise DiscoveryError("seed_fetch_failed", str(exc)) from exc
    if r.status_code >= 400:
        raise DiscoveryError("seed_fetch_failed", f"status={r.status_code}")
    seed_html = r.text

    # 2. Sitemap + link extraction in parallel.
    sitemap_task = asyncio.create_task(
        fetch_sitemap_urls(site.base_url, http_client=http_client)
    )
    link_pairs = extract_internal_links(seed_html, site.base_url)
    sitemap_urls = await sitemap_task

    # 3. Union with sitemap-first ordering; capture anchor text from link side.
    link_anchor_by_url = dict(link_pairs)
    union_ordered: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for url in sitemap_urls:
        if url in seen:
            continue
        seen.add(url)
        union_ordered.append((url, link_anchor_by_url.get(url)))
    for url, anchor in link_pairs:
        if url in seen:
            continue
        seen.add(url)
        union_ordered.append((url, anchor))

    # 4. Junk filter.
    filtered_out = 0
    kept: list[tuple[str, str | None]] = []
    for url, anchor in union_ordered:
        if is_junk(url):
            filtered_out += 1
            continue
        kept.append((url, anchor))

    # 5. Pre-LLM cap.
    capped = kept[: settings.discovery_max_candidates]

    # 6. Head scrape.
    head_results = await scrape_heads_concurrently(
        capped,
        http_client=http_client,
        timeout_s=settings.discovery_head_fetch_timeout_s,
        concurrency=settings.discovery_head_fetch_concurrency,
    )
    heads: list[HeadInfo] = [h for h in head_results if h is not None]

    # 7. Classify.
    try:
        scored = await classify_candidates(heads, llm_client=llm_client, site_name=site.name)
    except ClassificationError as exc:
        raise DiscoveryError("classification_failed", exc.detail) from exc

    # 8. Filter by min_score and cap.
    by_url = {h.url: h for h in heads}
    enriched = [
        (by_url[sc.url], sc) for sc in scored if sc.url in by_url
    ]
    enriched.sort(key=lambda pair: pair[1].score, reverse=True)
    out: list[DiscoveryCandidate] = []
    for head, sc in enriched:
        if sc.score < min_score_f:
            continue
        out.append(DiscoveryCandidate(
            url=head.url,
            title=head.title,
            kind=head.kind,
            score=sc.score,
            reason=sc.reason,
        ))
        if len(out) >= max_out:
            break

    stats = DiscoveryStats(
        sitemap_urls=len(sitemap_urls),
        link_urls=len(link_pairs),
        filtered_junk=filtered_out,
        fetched_heads=len(heads),
        classified=len(scored),
        returned=len(out),
    )
    log.info("discovery.complete", site_id=site.id, **vars(stats))
    return DiscoveryResult(site_id=site.id, seed_url=site.base_url, stats=stats, candidates=out)
```

- [ ] **Step 3: Run + commit**

```bash
uv run pytest tests/integration/test_discover_orchestrator.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/discovery/discover.py tests/integration/test_discover_orchestrator.py
git commit -m "feat(discovery): add discover_site orchestrator composing all stages"
```

---

## Task 8 — HTTP route + schemas

**Files:**
- Create: `src/yas/web/routes/discover_schemas.py`
- Modify: `src/yas/web/routes/sites.py` (add `/discover` endpoint)
- Create: `tests/integration/test_api_discover.py`

- [ ] **Step 1: Failing API test**

`tests/integration/test_api_discover.py`:

```python
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import Site
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


_SEED = """<html><body>
  <a href="/programs/">Programs</a>
  <a href="/feed/">RSS</a>
  <a href="/brochure.pdf">Brochure</a>
</body></html>"""

_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://ysi.test/programs/summer/</loc></url>
</urlset>"""

_PAGE = "<html><head><title>T</title></head></html>"


class _FakeLLM:
    """Exposes only call_tool; used in place of AnthropicClient for discovery tests."""

    def __init__(self, scored: list[dict]):
        self.scored = scored
        self.call_count = 0

    async def call_tool(self, *, system, user, tool_name, tool_description, input_schema, max_tokens=4096):
        self.call_count += 1
        return {"candidates": self.scored}, "fake-haiku", 0.003


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/d.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Site(id=1, name="YSI", base_url="https://ysi.test/"))

    llm = _FakeLLM([
        {"url": "https://ysi.test/programs/summer/", "score": 0.9, "reason": "program detail"},
        {"url": "https://ysi.test/programs/", "score": 0.4, "reason": "router"},
        {"url": "https://ysi.test/brochure.pdf", "score": 0.7, "reason": "pdf brochure"},
    ])
    app = create_app(engine=engine, llm=llm)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine, llm
    await engine.dispose()


@pytest.mark.asyncio
@respx.mock
async def test_discover_returns_candidates(client):
    c, _, llm = client
    respx.get("https://ysi.test/").mock(return_value=httpx.Response(200, text=_SEED))
    respx.get("https://ysi.test/sitemap.xml").mock(return_value=httpx.Response(200, content=_SITEMAP))
    respx.get("https://ysi.test/programs/summer/").mock(return_value=httpx.Response(200, text=_PAGE))
    respx.get("https://ysi.test/programs/").mock(return_value=httpx.Response(200, text=_PAGE))

    r = await c.post("/api/sites/1/discover")
    assert r.status_code == 200
    body = r.json()
    assert body["site_id"] == 1
    urls = {ch["url"] for ch in body["candidates"]}
    # PDF surfaced; /feed/ and /programs/ (score 0.4) filtered.
    assert "https://ysi.test/programs/summer/" in urls
    assert "https://ysi.test/brochure.pdf" in urls
    pdf = next(ch for ch in body["candidates"] if ch["kind"] == "pdf")
    assert pdf["title"] == "brochure.pdf"


@pytest.mark.asyncio
@respx.mock
async def test_discover_404_when_site_missing(client):
    c, _, _ = client
    r = await c.post("/api/sites/999/discover")
    assert r.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_discover_502_when_seed_fails(client):
    c, _, _ = client
    respx.get("https://ysi.test/").mock(return_value=httpx.Response(502))
    r = await c.post("/api/sites/1/discover")
    assert r.status_code == 502
    assert "seed_fetch_failed" in r.json()["detail"]


@pytest.mark.asyncio
@respx.mock
async def test_discover_accepts_min_score_override(client):
    c, _, _ = client
    respx.get("https://ysi.test/").mock(return_value=httpx.Response(200, text=_SEED))
    respx.get("https://ysi.test/sitemap.xml").mock(return_value=httpx.Response(200, content=_SITEMAP))
    respx.get("https://ysi.test/programs/summer/").mock(return_value=httpx.Response(200, text=_PAGE))
    respx.get("https://ysi.test/programs/").mock(return_value=httpx.Response(200, text=_PAGE))
    r = await c.post("/api/sites/1/discover", json={"min_score": 0.85})
    assert r.status_code == 200
    body = r.json()
    # Only summer/ scores >= 0.85; pdf 0.7 filtered
    urls = {ch["url"] for ch in body["candidates"]}
    assert urls == {"https://ysi.test/programs/summer/"}


@pytest.mark.asyncio
async def test_discover_rejects_invalid_min_score(client):
    c, _, _ = client
    r = await c.post("/api/sites/1/discover", json={"min_score": 1.5})
    assert r.status_code == 422
```

Run: `uv run pytest tests/integration/test_api_discover.py -v` — expect import/route failures.

- [ ] **Step 2: Create `src/yas/web/routes/discover_schemas.py`**

```python
"""Pydantic models for /api/sites/{id}/discover."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)
    max_candidates: int | None = Field(default=None, ge=1, le=50)


class CandidateOut(BaseModel):
    url: str
    title: str
    kind: Literal["html", "pdf"]
    score: float
    reason: str


class DiscoveryStatsOut(BaseModel):
    sitemap_urls: int
    link_urls: int
    filtered_junk: int
    fetched_heads: int
    classified: int
    returned: int


class DiscoveryResultOut(BaseModel):
    site_id: int
    seed_url: str
    stats: DiscoveryStatsOut
    candidates: list[CandidateOut]
```

- [ ] **Step 3: Add endpoint to `src/yas/web/routes/sites.py`**

Append imports at the top:
```python
import httpx
from fastapi import Body
from fastapi.responses import JSONResponse

from yas.discovery.discover import DiscoveryError, discover_site
from yas.web.routes.discover_schemas import (
    CandidateOut,
    DiscoverRequest,
    DiscoveryResultOut,
    DiscoveryStatsOut,
)
```

Add the endpoint (place it near the existing sites endpoints):

```python
@router.post("/{site_id}/discover", response_model=DiscoveryResultOut)
async def discover_pages(
    site_id: int,
    request: Request,
    payload: DiscoverRequest | None = Body(default=None),
) -> DiscoveryResultOut | JSONResponse:
    engine = _engine(request)
    settings = request.app.state.yas.settings
    llm = request.app.state.yas.llm
    if llm is None:
        raise HTTPException(status_code=503, detail="llm_not_configured")

    async with session_scope(engine) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        # detach so we can use it after the session closes
        await s.flush()
        site_snapshot = _SiteSnapshot(id=site.id, name=site.name, base_url=site.base_url)

    body = payload or DiscoverRequest()
    async with httpx.AsyncClient(
        headers={"User-Agent": "yas/0.1 (+discovery)"},
        follow_redirects=True,
    ) as http:
        try:
            result = await discover_site(
                site=site_snapshot,
                http_client=http,
                llm_client=llm,
                settings=settings,
                min_score=body.min_score,
                max_candidates=body.max_candidates,
            )
        except DiscoveryError as exc:
            return JSONResponse(
                status_code=502,
                content={"detail": f"{exc.code}: {exc.detail}"},
            )

    return DiscoveryResultOut(
        site_id=result.site_id,
        seed_url=result.seed_url,
        stats=DiscoveryStatsOut(**vars(result.stats)),
        candidates=[CandidateOut(**vars(c)) for c in result.candidates],
    )
```

Add a tiny local dataclass near the top of `sites.py`:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class _SiteSnapshot:
    id: int
    name: str
    base_url: str
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/integration/test_api_discover.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/web/routes/discover_schemas.py src/yas/web/routes/sites.py \
    tests/integration/test_api_discover.py
git commit -m "feat(web): add POST /api/sites/{id}/discover read-only endpoint"
```

---

## Task 9 — Smoke script + README + phase exit verify

**Files:**
- Create: `scripts/smoke_phase3_5.sh`
- Modify: `README.md`

- [ ] **Step 1: Smoke script**

`scripts/smoke_phase3_5.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if ! grep -q '^YAS_ANTHROPIC_API_KEY=sk-' .env 2>/dev/null || grep -q '^YAS_ANTHROPIC_API_KEY=sk-test-nonop$' .env; then
  echo "ERROR: .env must set YAS_ANTHROPIC_API_KEY to a real key." >&2
  exit 2
fi

COMPOSE="docker compose"
if [ "$(uname)" = "Darwin" ]; then
  COMPOSE="$COMPOSE -f docker-compose.yml -f docker-compose.macos.yml"
fi

$COMPOSE down 2>/dev/null || true
$COMPOSE up -d yas-migrate
$COMPOSE up -d yas-worker yas-api
sleep 10

echo "--- household ---"
curl -sS -X PATCH localhost:8080/api/household -H 'content-type: application/json' \
  -d '{"home_address":"2045 N Lincoln Park W, Chicago, IL","default_max_distance_mi":30.0}' > /dev/null

echo "--- kid ---"
curl -sS -X POST localhost:8080/api/kids -H 'content-type: application/json' -d '{
  "name":"Sam","dob":"2019-05-01","interests":["soccer"]
}' > /dev/null

echo "--- site with only base_url (no pages) ---"
curl -sS -X POST localhost:8080/api/sites -H 'content-type: application/json' -d '{
  "name":"YSIFC","base_url":"https://ysifc.com/","needs_browser":true
}' | jq .

echo ""
echo "--- discover ---"
DISCOVER=$(curl -sS -X POST localhost:8080/api/sites/1/discover)
echo "$DISCOVER" | jq .

echo ""
echo "--- picking top HTML candidate ---"
TOP_URL=$(echo "$DISCOVER" | jq -r '[.candidates[] | select(.kind == "html")] | first | .url')
if [ -z "$TOP_URL" ] || [ "$TOP_URL" = "null" ]; then
  echo "No HTML candidate discovered; exiting smoke." && $COMPOSE down && exit 1
fi
echo "Picked: $TOP_URL"

curl -sS -X POST "localhost:8080/api/sites/1/pages" -H 'content-type: application/json' \
  -d "{\"url\":\"$TOP_URL\",\"kind\":\"schedule\"}" | jq .

echo ""
echo "Waiting 90s for scheduler + crawl + extract + rematch..."
sleep 90

echo ""
echo "--- offerings ---"
$COMPOSE exec -T yas-api sqlite3 /data/activities.db \
  'select id, name, program_type, age_min, age_max, start_date from offerings'

echo ""
echo "--- matches ---"
curl -sS 'localhost:8080/api/matches?kid_id=1' | jq '.[] | {offering_id, score, gates: .reasons.gates}'

echo ""
echo "--- PDF rejection check ---"
curl -sS -w "\nHTTP %{http_code}\n" -X POST localhost:8080/api/sites/1/pages \
  -H 'content-type: application/json' \
  -d '{"url":"https://ysifc.com/brochure.pdf","kind":"pdf"}'

$COMPOSE down
```

Make executable: `chmod +x scripts/smoke_phase3_5.sh`.

- [ ] **Step 2: README update**

Add a new **Discovering pages** section after "Managing sites":

```markdown
## Discovering pages on a site

If you don't know which exact URLs have programs on them, register the site
with just `base_url` and call `/discover`:

```bash
curl -sS -X POST localhost:8080/api/sites \
  -H 'content-type: application/json' \
  -d '{"name":"Some Club","base_url":"https://example.org/","needs_browser":true}'

curl -sS -X POST localhost:8080/api/sites/1/discover | jq .
```

Discovery checks `/sitemap.xml` and extracts internal links from the seed
page, feeds each candidate's title + meta description to Claude Haiku, and
returns a ranked list of likely program-detail pages. PDFs are surfaced
with `"kind": "pdf"` but are not yet trackable (PDF crawling is a future
phase). HTML candidates can be added to tracking with the existing
`POST /api/sites/{id}/pages` endpoint.

Typical discovery cost: ~$0.02/call. The endpoint is read-only — it never
adds pages automatically.
```

- [ ] **Step 3: Final verification — all exit gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -v
```

Then the end-to-end smoke (requires real API key):

```bash
./scripts/smoke_phase3_5.sh
```

Expected:
- `POST /api/sites/1/discover` returns 200 with at least one HTML candidate
- The script picks the top HTML URL, adds it as a tracked page, crawls successfully
- `/api/matches?kid_id=1` eventually populates (may be empty if no match passes all hard gates — that's OK; discovery itself is the deliverable)
- `POST /api/sites/1/pages {"kind":"pdf"}` returns 422

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_phase3_5.sh README.md
git commit -m "docs: add phase-3.5 smoke and discovery quickstart"
```

---

## Phase 3.5 exit checklist

Apply @superpowers:verification-before-completion. Every box below must be verified with an actual command, not asserted.

- [ ] `uv run ruff check .` clean
- [ ] `uv run ruff format --check .` clean
- [ ] `uv run mypy src` clean
- [ ] `uv run pytest` — all new tests green plus full suite
- [ ] `scripts/smoke_phase3_5.sh` succeeds end-to-end against the real YSIFC URL with a real API key
- [ ] Discovery returns a ranked list including at least one HTML candidate
- [ ] Adding the top HTML candidate produces a successful crawl (offerings appear)
- [ ] Attempting to add `{"kind":"pdf"}` returns 422
- [ ] Discovery call logs one structured line with `cost_usd` populated; typical under $0.05

When all boxes check, merge with `--no-ff` to `main`. Proceed to **Phase 4 — Alerting**.
