# Phase 3.5 — Site Discovery Design Spec

**Status:** Draft — awaiting user review
**Date:** 2026-04-22
**Depends on:** Phase 1 (Foundation), Phase 2 (Crawl pipeline), Phase 3 (Matching) — all merged to `main`
**Target repo:** `youth-activity-scheduler/`

---

## 1. Purpose and scope

Register a site with just a home-page URL (or any landing URL) and have the system **discover which sub-pages are actual program / schedule detail pages**. You paste `https://ysifc.com/`; discovery returns `https://ysifc.com/programs/summer-camps-2026/` and any other program-shaped pages, ranked by confidence. You confirm the subset you want to track; existing `POST /api/sites/{id}/pages` adds them as tracked pages.

Phase 3 smoke against YSIFC revealed this gap: the `/register/` URL is a navigation router, not a schedule page, so the extractor returned zero offerings. The fix is not to require users to know the exact right URL — it's to make discovery a first-class pipeline step.

### In scope

- New `POST /api/sites/{id}/discover` endpoint — pure read; returns ranked candidates with reasons; does not add anything to `pages`
- Two-source candidate collection: `/sitemap.xml` + `/sitemap_index.xml` (follow one level) UNION internal `<a href>` links from the seed page (same host); dedupe
- Deterministic junk-URL filter (`/wp-admin`, `/feed`, image/xml/css/js extensions) — **PDFs allowed through**
- Per-candidate `<head>` enrichment via httpx (title + meta description), capped at 10 concurrent fetches, 50 candidates total
- Single LLM classification call via Claude Haiku using tool-use / structured output; scores 0–1 with a one-line reason per candidate
- PDF surfacing: PDFs are classified too but marked `kind="pdf"`; cannot yet be added as tracked pages (schema rejection at `POST /api/sites/{id}/pages`); full PDF support is a later phase
- Synchronous endpoint; blocks the caller for the ~5–15 s discovery round-trip
- Config knobs for max candidates, min score, concurrency, timeouts

### Explicitly out of scope

- Actually crawling / extracting PDFs (surfaced only)
- Multi-hop link following beyond the seed page
- Discovery result caching (each call re-runs)
- Async job queue for discovery progress (Phase 5 when the UI needs it)
- Scheduled rediscovery (manual only)
- Discovery UI (Phase 5 wires this endpoint into its Add Site wizard)
- Authenticated sitemap / link-protected pages (unchanged from earlier phases)

---

## 2. Architectural approach

One new package (`src/yas/discovery/`) + one new route. Composition mirrors the existing pipeline: small pure-ish functions for each stage, an orchestrator that composes them, a route adapter that plumbs AppState → orchestrator inputs.

```
POST /api/sites/{id}/discover
  │
  └── discover.discover_site(site, http_client, llm)
        ├── sitemap.fetch_sitemap_urls(base_url)          # httpx only
        ├── links.extract_internal_links(seed_html, seed_url)
        ├── (union + dedupe + filters.is_junk filter + 50-cap)
        ├── heads.scrape_head(url)   # ×N with Semaphore(10); PDF short-circuits
        ├── classifier.classify_candidates(enriched, llm) # single LLM call
        └── (min_score filter + 20-cap + sort)
              → DiscoveryResult
```

Discovery forces httpx even on `needs_browser=true` sites — sitemap.xml and `<head>` tags don't need JS. Playwright is reserved for the actual crawl after pages are confirmed.

Discovery is **not cached**. Each call re-runs the full pipeline (~$0.02 per call, sub-cent in steady state). One-shot-per-site in practice; caching complexity isn't earned.

---

## 3. Modules

### 3.1 `src/yas/discovery/sitemap.py`

```python
async def fetch_sitemap_urls(base_url: str, *, http_client: httpx.AsyncClient) -> list[str]:
    """Try {base}/sitemap.xml and {base}/sitemap_index.xml. Follow one level
    of index references. Return bare URLs. Network or parse errors → []."""
```

Internal helpers: `_parse_sitemap_xml(xml_bytes)` → list of URLs; `_parse_sitemap_index_xml(xml_bytes)` → list of child sitemap URLs. Both tolerate malformed XML (return `[]`).

### 3.2 `src/yas/discovery/links.py`

```python
def extract_internal_links(seed_html: str, seed_url: str) -> list[tuple[str, str]]:
    """Extract (url, anchor_text) pairs for internal links from seed HTML.
    Uses selectolax. Filters to same-host (including scheme). Dedupes by URL,
    preserving the longest anchor text seen."""
```

### 3.3 `src/yas/discovery/filters.py`

```python
def is_junk(url: str) -> bool: ...
```

Module-level `_JUNK_PATTERNS`:

- Path prefixes: `/wp-admin`, `/wp-content`, `/wp-json`, `/wp-login`, `/feed`, `/author/`, `/tag/`, `/category/`, `/comments/`, `/login`, `/logout`, `/account`, `/cart`, `/checkout`
- Query signatures: `?replytocom=`, `?s=`, `?p=<number>`
- File extensions: `.xml`, `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.svg`, `.css`, `.js`, `.ico`, `.woff`, `.woff2`, `.ttf`, `.eot`

**PDFs are NOT filtered.** `.pdf` URLs pass through to classification.

### 3.4 `src/yas/discovery/heads.py`

```python
@dataclass(frozen=True)
class HeadInfo:
    url: str
    title: str
    meta_description: str | None
    kind: Literal["html", "pdf"]

async def scrape_head(
    url: str, *, http_client: httpx.AsyncClient, timeout_s: int,
) -> HeadInfo | None:
    """Return HeadInfo or None on any failure (4xx/5xx/timeout/parse error).
    For PDF URLs (path ends in .pdf), skip the HTTP GET and return
    HeadInfo(title=<last path segment>, meta_description=None, kind="pdf")."""
```

Orchestrator-side helper: scrape N candidates concurrently under an `asyncio.Semaphore(settings.discovery_head_fetch_concurrency)`. Failures produce None and are dropped.

### 3.5 `src/yas/discovery/classifier.py`

```python
class ScoredCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str

class ClassificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[ScoredCandidate]

async def classify_candidates(
    candidates: list[HeadInfo],
    llm: LLMClient,
    *,
    site_name: str,
) -> list[ScoredCandidate]:
    """Single LLM call with tool-use. Returns every candidate scored (missing
    entries score 0.0). Hallucinated URLs not in input are dropped with a
    warning log. Raises ClassificationError on Pydantic validation failure."""
```

Prompt (verbatim intent; exact text lives in a module constant):

> You classify pages of a youth activity / sports / enrichment site. Given a list of URLs with titles, meta descriptions, and kind (`html` or `pdf`), identify pages that contain actual program or schedule **detail** — dates, ages, times, prices, registration info.
>
> Reject: navigation/landing pages, "our programs" overviews without details, registration routers, news/blog posts, team rosters, "about us", "contact", "policies", login pages, homepages unless they clearly ARE the schedule.
>
> Assign score 0.0–1.0 plus a one-line reason for each URL. Prefer precision over recall — missing a page is better than recommending a bad one.
>
> Call `report_candidates` with your ranked list. Do not invent URLs not in the input.

`ClassificationError` mirrors Phase 2's `ExtractionError` shape: carries `raw` and `detail` attributes.

### 3.6 `src/yas/discovery/discover.py`

```python
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
    candidates: list[DiscoveryCandidate]

async def discover_site(
    *,
    site: Site,
    http_client: httpx.AsyncClient,
    llm: LLMClient,
    settings: Settings,
    min_score: float | None = None,
    max_candidates: int | None = None,
) -> DiscoveryResult: ...
```

Algorithm:

1. GET seed via httpx. On failure → raise `DiscoveryError("seed_fetch_failed", cause)`.
2. Concurrently: `fetch_sitemap_urls(site.base_url)` and `extract_internal_links(seed_html, site.base_url)`.
3. Union URLs (preserve first-seen anchor text). Apply `filters.is_junk`. Cap at `settings.discovery_max_candidates` (default 50).
4. Fetch heads concurrently with semaphore; collect successful `HeadInfo` rows.
5. Call `classifier.classify_candidates`. On `ClassificationError` → raise `DiscoveryError("classification_failed", detail)`.
6. Filter by `min_score` (default `settings.discovery_min_score`, 0.5). Sort by score desc. Cap at `max_candidates` (default `settings.discovery_max_returned`, 20).
7. Return `DiscoveryResult`.

### 3.7 `src/yas/web/routes/discover_schemas.py`

```python
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

### 3.8 Route: `POST /api/sites/{id}/discover`

Added in `src/yas/web/routes/sites.py`. Loads site, calls `discover_site(...)` with an httpx client, llm, and settings taken from AppState. Returns `DiscoveryResultOut`.

Status codes:
- `200 OK` — discovery ran; candidates may be `[]` if nothing passed threshold
- `404 Not Found` — site_id doesn't exist
- `502 Bad Gateway` — `DiscoveryError` (seed fetch or classifier hard-fail); error detail in body
- `422 Unprocessable Entity` — invalid `min_score` / `max_candidates` (Pydantic)

### 3.9 Validation change: `POST /api/sites/{id}/pages` rejects `kind="pdf"`

`sites_schemas.PageCreate.kind` becomes a `Literal["schedule", "registration", "list", "other"]` — PDFs don't fit and submitting `"pdf"` is a Pydantic 422. No runtime content-type sniffing; a mis-kind submission (`{"url": "...pdf", "kind": "schedule"}`) will fail at the next crawl, land in `crawl_runs.error_text`, and be fixable via `DELETE /api/sites/{id}/pages/{page_id}`. Adversarial mis-kind is out of scope.

---

## 4. Configuration additions

```python
# src/yas/config.py
discovery_enabled: bool = True
discovery_max_candidates: int = 50       # cap BEFORE LLM classification
discovery_max_returned: int = 20         # cap AFTER filter
discovery_min_score: float = 0.5
discovery_head_fetch_concurrency: int = 10
discovery_head_fetch_timeout_s: int = 10
```

`.env.example` updated with `YAS_DISCOVERY_*` entries.

No worker changes. Discovery runs in the API process (FastAPI async handler). No new worker tasks.

---

## 5. Dependencies

No new packages. `selectolax` (Phase 2), `httpx` (Phase 2), Pydantic (Phase 1), Claude Haiku client (Phase 2) all already in place.

---

## 6. Testing strategy

### 6.1 Unit (pure)

- `test_discovery_filters.py` — allow/reject matrix for `is_junk`. Pinned: `/wp-admin` rejected, `.xml` rejected, **`.pdf` allowed**, image/css/js extensions rejected.
- `test_discovery_sitemap.py` — parse fixture XML (flat sitemap + sitemap index). Network calls mocked via `respx`. Malformed XML → `[]`.
- `test_discovery_links.py` — `selectolax` parse, same-host filter, dedup preserving longest anchor text.
- `test_discovery_heads.py` — `respx`-mocked scrapes: title + meta extraction, 4xx/5xx/timeout → None, PDF URL → short-circuit with filename title, concurrency cap enforcement.
- `test_discovery_classifier.py` — fake LLM returning canned `ClassificationResponse`; tests for hallucinated-URL dropping, missing-URL implicit-zero scoring, `ClassificationError` on schema violation.

### 6.2 Integration

`test_api_discover.py`:

- **Happy path:** respx mocks seed + sitemap + N heads; fake LLM scores 6 candidates including 1 PDF; endpoint returns 200 with populated stats and candidates. PDF has `kind="pdf"`, filename as title.
- **Sitemap missing, link-crawl fallback:** sitemap 404; seed page contains program links; discovery still returns candidates.
- **Seed fetch fails:** endpoint returns 502 with `DiscoveryError` detail.
- **Empty result:** classifier scores everything below threshold → 200 with `candidates: []`, stats populated.
- **Invalid request body:** `min_score=1.5` → 422.
- **`POST /api/sites/{id}/pages` with `kind="pdf"`:** → 422 from Pydantic.

### 6.3 Named must-have tests

- `test_discovery_surfaces_pdf_with_kind_marker`
- `test_discovery_union_dedupes_sitemap_and_links`
- `test_discovery_drops_hallucinated_urls_from_llm`
- `test_discovery_fetch_head_respects_concurrency_cap` — 30 candidates with semaphore of 3 → asserts never more than 3 in-flight
- `test_junk_filter_allows_pdf_rejects_xml_images`
- `test_discovery_returns_empty_candidates_when_none_pass_threshold`
- `test_post_pages_rejects_pdf_kind` — Pydantic validation on the existing sites endpoint

---

## 7. Exit criteria

- All new tests green; full suite green
- `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` clean
- **End-to-end smoke on Docker Compose (with macOS overlay locally):**
  - `POST /api/sites {name, base_url: "https://ysifc.com/", needs_browser: true}` (no `pages`)
  - `POST /api/sites/1/discover` returns a `DiscoveryResult` with HTML program pages and (if present) PDF brochures as candidates
  - User-picked HTML candidate added via `POST /api/sites/1/pages` → scheduler crawls → offerings populated → `/api/matches?kid_id=1` returns real-data matches (with age-gate clamp helping)
  - Cost per discovery call under $0.05; typical ~$0.02
- No silent failures: discovery errors surface in API response body (502) and in the structured log

## 8. Open questions / deferred

- **PDF crawling and extraction** — surfaced now, trackable later. Dedicated phase after 4 (alerting) when we have real usage data on how often PDFs matter.
- **Discovery caching** — deferred. If a user runs discovery multiple times per site for different seed URLs, pays each time.
- **Scheduled rediscovery** — no mechanism for "rediscover every 90 days to catch new program pages." Manual only.
- **Multi-hop link follow** — single-hop from seed for Phase 3.5. If real sites need depth 2+ to reach programs, revisit.
- **Anchor text to LLM** — when a candidate came via link extraction and has anchor text, do we pass it to the classifier? The plan says yes but only when present; sitemap-only candidates have no anchor. Acceptable asymmetry.

## 9. What Phase 3.5 does NOT touch

- Alerting (Phase 4)
- Calendar / dashboard / UI (Phase 5)
- Adaptive cadence (Phase 6)
- PDF content handling
- Async job queues
