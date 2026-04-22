# Phase 2 — Crawl Pipeline MVP Design Spec

**Status:** Draft — awaiting user review
**Date:** 2026-04-22
**Depends on:** Phase 1 (Foundation — merged to `main` 2026-04-21)
**Target repo:** `youth-activity-scheduler/`

---

## 1. Purpose and scope

End-to-end crawl + extract pipeline for one-site-at-a-time operation: you register a site via HTTP API, the worker crawls it on a fixed cadence, the pipeline fetches → detects change → extracts structured offerings via Claude Haiku → reconciles against prior state. New/updated/withdrawn offerings appear in the DB and are visible via the site-management API. LLM extractions are cached by content hash so unchanged pages never re-call the API.

This phase intentionally excludes: matching, alerting, the Web UI, adapter framework, adaptive cadence, and the Haiku→Sonnet fallback. Those land in Phases 3–6.

### In scope

- Fetcher (httpx + Chromium via Playwright), shared lazy browser, polite retries, per-site concurrency of 1
- Change detection via `selectolax`-based HTML normalization + SHA-256 content hash
- LLM extraction via Claude Haiku using tool-use / structured output against a fixed Pydantic schema, with an `extraction_cache` lookup by content hash
- Reconciler with `(normalized_name, start_date)` match key, emitting new / updated / withdrawn / unchanged
- Fixed-interval scheduler (from `site.default_cadence_s`) running inside the existing worker process
- `robots.txt` **ignored by default**, per-site opt-in via `crawl_hints["respect_robots"] = True`
- Site-management HTTP API: `POST /api/sites`, `GET /api/sites[/{id}]`, `PATCH`, `DELETE`, `POST /api/sites/{id}/pages`, `DELETE /api/sites/{id}/pages/{page_id}`, `POST /api/sites/{id}/crawl-now`
- Fixture HTTP server for hermetic integration tests
- `FakeLLMClient` for tests
- Manual real-site smoke script against `https://www.lilsluggerschicago.com/spring-session-24.html`

### Explicitly out of scope (for later phases)

- Matching engine, hard gates, scoring (Phase 3)
- School-block materialization, enrollment blocks (Phase 3)
- Alerting, channels, digest (Phase 4)
- Web UI, SSE, Add Site wizard, dashboards (Phase 5)
- Adaptive cadence (registration-proximity ramp) (Phase 6)
- Site-specific hand-written adapter framework (Phase 6)
- Haiku → Sonnet fallback (Phase 6)
- LLM daily cost-cap enforcement (Phase 6)

---

## 2. Architectural approach

Tiered pipeline as described in Phase 1 spec §4, but Phase 2 implements only the LLM branch (no hand-written adapters yet). Flow:

```
POST /api/sites          →  sites + pages rows
crawl_scheduler_loop     →  selects due pages (fixed-interval)
pipeline.crawl_page      →  fetcher → change_detector → extractor → reconciler
                            ↓
                         crawl_runs row written; events logged
```

The worker gains a second async task (`crawl_scheduler_loop`) alongside the Phase 1 heartbeat loop, coordinated via `asyncio.TaskGroup`. Fetcher and LLM client are constructed once at worker startup and shared across pipeline invocations.

---

## 3. Modules (new code)

All new modules live under `src/yas/crawl/`, `src/yas/llm/`, and `src/yas/web/routes/`.

### 3.1 `src/yas/crawl/fetcher.py`

```python
@dataclass(frozen=True)
class FetchResult:
    url: str            # final URL after redirects
    status_code: int
    html: str
    used_browser: bool
    elapsed_ms: int

class Fetcher(Protocol):
    async def fetch(self, page: Page, site: Site) -> FetchResult: ...
    async def aclose(self) -> None: ...
```

**`DefaultFetcher`:**

- Holds one `httpx.AsyncClient` with `User-Agent: yas/0.1 (+https://github.com/<user>/youth-activity-scheduler)` and a 30s total timeout.
- Lazily launches one Playwright Chromium `Browser` + `BrowserContext`, shared across calls, torn down in `aclose()`.
- `site.needs_browser=True` → Playwright path; else httpx. No fallback between them.
- Per-site concurrency via `dict[site_id, asyncio.Lock]`, acquired before fetch.
- Retry policy: 3 attempts, exponential backoff `(1s, 4s, 10s)` on `429, 502, 503, 504`, and `httpx.TransportError`. Other 4xx fails immediately.
- `robots.txt`: **ignored by default**. Only checked when `site.crawl_hints.get("respect_robots") is True`. Cached per site per process lifetime.
- Raises `FetchError(status, url, cause)` only after exhausting retries.
- Instantiated once in worker startup; shared via `AppState`. `aclose()` runs on shutdown.

### 3.2 `src/yas/crawl/change_detector.py`

Two pure functions:

```python
def normalize(html: str) -> str: ...
def content_hash(normalized: str) -> str: ...
```

Normalization (in order):

1. Parse with `selectolax.parser.HTMLParser`.
2. Remove `<script>`, `<style>`, `<noscript>`, `<nav>`, `<footer>`, `<header>`, `<aside>` subtrees.
3. Remove all attributes matching `data-*`, `aria-*`, and `style`.
4. Remove elements whose `class` contains any of `cookie`, `banner`, `notification`, `timestamp`, `csrf`, `track`.
5. Collapse all whitespace runs to single space; trim.

Hash is SHA-256 over UTF-8 bytes of the normalized string, hex-digested.

### 3.3 `src/yas/crawl/normalize.py`

```python
def normalize_name(s: str) -> str:
    """lowercase → strip punctuation → collapse whitespace → trim."""
```

Shared by the reconciler (now) and the matcher (Phase 3).

### 3.4 `src/yas/crawl/extractor.py`

```python
@dataclass(frozen=True)
class ExtractionResult:
    offerings: list[ExtractedOffering]
    content_hash: str
    from_cache: bool
    model: str | None           # None when from_cache
    cost_usd: float              # 0.0 when from_cache

class ExtractionError(Exception):
    def __init__(self, raw_response: str, validation_errors: str): ...

async def extract(
    engine: AsyncEngine,
    llm: LLMClient,
    html: str,
    url: str,
    site_name: str,
) -> ExtractionResult: ...
```

Flow: normalize → hash → `extraction_cache` lookup (hit → return); on miss call LLM, validate with Pydantic, write cache row, return. Validation failure raises `ExtractionError` carrying the raw response and the first validation message.

### 3.5 `src/yas/crawl/reconciler.py`

```python
@dataclass(frozen=True)
class ReconcileResult:
    new: list[int]             # offering IDs
    updated: list[int]
    withdrawn: list[int]
    unchanged: list[int]

async def reconcile(
    session: AsyncSession,
    page: Page,
    extracted: list[ExtractedOffering],
) -> ReconcileResult: ...
```

Runs inside caller's `session_scope`; does not commit.

Algorithm:

1. Load active `offerings` for `page_id`; bucket by `(normalized_name, start_date)`.
2. For each extracted offering: if key matches, compare field-by-field (see §3.5.1) — equal = unchanged; different = updated. If no match, insert new.
3. Any existing key not matched this run → set `status = withdrawn`.
4. `location_name` / `location_address` flow through `get_or_create_location` (dedup by `normalize_name(name)` within site). Geocoding deferred to Phase 3; lat/lon stay NULL.

#### 3.5.1 Fields compared for "updated"

`name, description, age_min, age_max, program_type, start_date, end_date, days_of_week, time_start, time_end, location_id, price_cents, registration_opens_at, registration_url`. `raw_json` is overwritten but does not by itself trigger "updated".

#### 3.5.2 Withdrawn resurrection

A withdrawn offering that reappears in a later crawl produces a **new** insert (does not reactivate the withdrawn row). Accepted for Phase 2; revisit if it causes noise.

### 3.6 `src/yas/crawl/scheduler.py`

`crawl_scheduler_loop(engine, settings, fetcher, llm)`:

- Every `settings.crawl_scheduler_tick_s` (default `30`):
  - Query:
    ```sql
    SELECT p.*, s.*
    FROM pages p JOIN sites s ON s.id = p.site_id
    WHERE s.active = TRUE
      AND (s.muted_until IS NULL OR s.muted_until < now())
      AND (p.next_check_at IS NULL OR p.next_check_at <= now())
    ORDER BY p.next_check_at NULLS FIRST
    LIMIT settings.crawl_scheduler_batch_size
    ```
  - For each row, spawn `pipeline.crawl_page(...)` as a task. Per-site concurrency of 1 is enforced inside the fetcher.
  - Await all tasks for back-pressure before the next tick.
- `settings.crawl_scheduler_enabled: bool = True` toggle.
- Defaults: tick 30s, batch 10.

### 3.7 `src/yas/crawl/pipeline.py`

```python
async def crawl_page(
    *,
    engine: AsyncEngine,
    fetcher: Fetcher,
    llm: LLMClient,
    page: Page,
    site: Site,
) -> CrawlResult: ...
```

Behaviour:

1. Open `CrawlRun(started_at=now, site_id, status=ok)`.
2. `fetcher.fetch(...)`. On `FetchError`: bump `page.consecutive_failures`, status `failed`, record `error_text`, `next_check_at = now + min(default_cadence_s * (2 ** failures), default_cadence_s * 4)`.
3. If `content_hash == page.content_hash`: short-circuit — status `ok`, `pages_fetched=1`, `changes_detected=0`, update `page.last_fetched` and `next_check_at`.
4. Else call `extractor.extract(...)`. On `ExtractionError`: status `failed`, `error_text`, **don't touch offerings**, advance `next_check_at` normally to prevent hammering.
5. On success: open `session_scope`, `reconciler.reconcile(...)`, commit. Fill `crawl_runs.changes_detected`, `llm_calls`, `llm_cost_usd`. Update `page.content_hash`, `last_fetched`, `last_changed` (if hash changed), reset `consecutive_failures=0`.
6. Unexpected exceptions are caught at the pipeline boundary, logged with traceback, recorded to `error_text` (truncated), status `failed`. The worker loop is never broken.
7. Always: `crawl_run.finished_at = now`; persist.

Structured events logged (info level) per reconciler category:

```json
{"event":"offering.new", "offering_id":123, "site_id":4, "name":"Little Kickers Sat AM"}
{"event":"offering.updated", "offering_id":124, "site_id":4, "fields":["price_cents"]}
{"event":"offering.withdrawn", "offering_id":122, "site_id":4}
{"event":"page.changed", "page_id":7, "site_id":4, "new_hash":"..."}
```

### 3.8 `src/yas/llm/`

**`schemas.py`:**

```python
class ExtractedOffering(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    program_type: ProgramType
    start_date: date | None = None
    end_date: date | None = None
    days_of_week: list[DayOfWeek] = []
    time_start: time | None = None
    time_end: time | None = None
    location_name: str | None = None
    location_address: str | None = None
    price_cents: int | None = None
    registration_opens_at: datetime | None = None
    registration_url: str | None = None

class ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offerings: list[ExtractedOffering]
```

`ProgramType` and `DayOfWeek` enums are reused from `src/yas/db/models/_types.py` where possible; `DayOfWeek` added there (`mon, tue, wed, thu, fri, sat, sun`) if not present.

**`prompt.py`:**

`build_extraction_prompt(html, url, site_name) -> tuple[str, str]` returning `(system, user)`. System prompt declares role, the fixed `program_type` vocabulary, date format conventions, and "if a field isn't clearly stated, return null rather than guessing." User prompt carries normalized HTML + URL + site name.

**`client.py`:**

```python
class LLMClient(Protocol):
    async def extract_offerings(
        self, *, html: str, url: str, site_name: str
    ) -> ExtractionResult: ...

class AnthropicClient:
    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None: ...
```

Uses Anthropic SDK tool-use: the model is asked to call a `report_offerings` tool whose `input_schema` is `ExtractionResponse.model_json_schema()`. The tool's input is the structured extraction. Extra keys in the tool input trigger Pydantic `extra="forbid"` rejection → `ExtractionError`.

Model configurable via `settings.llm_extraction_model` (default `claude-haiku-4-5-20251001`) so the Sonnet upgrade is one-line in Phase 6.

### 3.9 `src/yas/web/routes/sites.py` + `sites_schemas.py`

Endpoints (all JSON):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/sites` | Create site; optional `pages` array creates tracked pages atomically and sets `next_check_at=now` |
| `GET` | `/api/sites` | List all sites |
| `GET` | `/api/sites/{id}` | One site with its pages |
| `PATCH` | `/api/sites/{id}` | Update `active`, `muted_until`, `default_cadence_s`, `needs_browser`, `crawl_hints` |
| `DELETE` | `/api/sites/{id}` | Hard delete (cascades to pages/offerings via FK) |
| `POST` | `/api/sites/{id}/pages` | Add a tracked page (`next_check_at=now`) |
| `DELETE` | `/api/sites/{id}/pages/{page_id}` | Remove a tracked page |
| `POST` | `/api/sites/{id}/crawl-now` | Set `next_check_at=now` on all pages of the site |

Pydantic request/response models in `sites_schemas.py`. URL syntax + required fields validated. No auth (same stance as `/healthz`; localhost only).

Mounted via a FastAPI `APIRouter` in `src/yas/web/routes/__init__.py`, registered by `create_app(...)`.

---

## 4. Configuration additions

New `Settings` fields:

- `crawl_scheduler_enabled: bool = True`
- `crawl_scheduler_tick_s: int = 30`
- `crawl_scheduler_batch_size: int = 10`
- `llm_extraction_model: str = "claude-haiku-4-5-20251001"`

`YAS_` env prefix as existing. `.env.example` updated.

---

## 5. Dependencies

Added to `pyproject.toml` runtime deps:

- `selectolax>=0.3.21` — HTML parser for change detector
- `playwright>=1.42.0` — Chromium engine

Added to dev deps:

- `aiohttp>=3.9.0` — test fixture server

Dockerfile delta: after the second `uv sync` step, install Chromium:

```dockerfile
RUN uv run playwright install --with-deps chromium
```

Adds ~400MB to the image.

---

## 6. Testing strategy

### 6.1 Unit

- `test_change_detector.py` — normalization rules, hash stability across whitespace/attribute/class variations.
- `test_normalize.py` — name normalization corner cases.
- `test_fetcher.py` — httpx path using `respx`: happy path, each retry code, exhaustion. `robots.txt` behaviour (default ignore; opt-in respect).
- `test_extractor.py` — cache hit short-circuits LLM; cache miss invokes LLM, writes cache row, returns result; schema failure raises `ExtractionError`.
- `test_reconciler.py` — parametrized diff cases: empty→some (new), some→empty (withdrawn), matched unchanged, matched updated (single + multi field), matched with different `start_date`, null-`start_date` matching.
- `test_llm_schemas.py` — accept/reject examples for `ExtractedOffering` and `ExtractionResponse`.

### 6.2 Integration (hermetic)

Spin up `FixtureSite` (local `aiohttp.web.Application` on `127.0.0.1:0`) serving captured HTML plus a `set_page(path, html)` mutator for change-detection scenarios.

- `test_pipeline.py`:
  - Full happy path: register site + page → tick scheduler → offerings appear; `crawl_runs.status=ok`, `llm_calls=1`.
  - Second tick on unchanged page → `llm_calls=0`, `changes_detected=0`, cache hit.
  - Content change → new `crawl_runs` row, updated/new offerings populated.
  - `ExtractionError` path: `FakeLLMClient` raises → `crawl_runs.status=failed`, offerings untouched, next crawl still scheduled.
  - `FetchError` path: fixture server returns 500 → retries exhausted → `consecutive_failures` bumped, backoff applied.
- `test_api_sites.py`: exercises each of the 7 site-management endpoints through FastAPI's `AsyncClient` + in-memory SQLite.

### 6.3 Playwright integration

`test_playwright_fetcher.py` fetches a `file://` HTML file with a `<script>` that mutates the DOM post-load. Verifies `used_browser=True` and that post-JS content appears in `html`.

Skipped when Chromium binaries aren't installed. CI installs them via `uv run playwright install --with-deps chromium`.

### 6.4 Fakes

- `tests/fakes/llm.py`: `FakeLLMClient(responses)` scripts extraction output keyed on `(url, content_hash)` or `site_name`. Used by all integration tests except the Playwright one.

### 6.5 Manual smoke

`scripts/smoke_phase2.sh` — documented real-site ritual (see §8). Not in CI; requires a real `YAS_ANTHROPIC_API_KEY`.

---

## 7. Worker integration

Phase 1's worker ran heartbeat only. Phase 2:

```python
async def run_worker(engine, settings):
    fetcher = DefaultFetcher(settings)
    llm = AnthropicClient(api_key=settings.anthropic_api_key, model=settings.llm_extraction_model)
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(heartbeat_loop(engine, settings))
            if settings.crawl_scheduler_enabled:
                tg.create_task(crawl_scheduler_loop(engine, settings, fetcher, llm))
    finally:
        await fetcher.aclose()
```

Either task raising ends the worker cleanly. Fetcher lifecycle tied to worker lifecycle.

---

## 8. End-of-phase smoke test

`scripts/smoke_phase2.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

rm -f data/activities.db*
docker compose up -d yas-migrate yas-worker yas-api
sleep 10

curl -sS -X POST localhost:8080/api/sites \
  -H 'content-type: application/json' \
  -d '{
    "name": "Lil Sluggers Chicago",
    "base_url": "https://www.lilsluggerschicago.com/",
    "needs_browser": true,
    "pages": [
      {"url": "https://www.lilsluggerschicago.com/spring-session-24.html", "kind": "schedule"}
    ]
  }'

echo "waiting 90s for scheduler + crawl + extract..."
sleep 90

curl -sS localhost:8080/api/sites/1 | jq
sqlite3 data/activities.db 'select id, name, age_min, age_max, start_date, time_start from offerings'
sqlite3 data/activities.db 'select id, site_id, status, pages_fetched, changes_detected, llm_calls, llm_cost_usd, error_text from crawl_runs order by id desc limit 5'

docker compose down
```

Phase exit criterion: at least one real `offerings` row with non-null core fields (name, program_type, some schedule data), `crawl_runs.status=ok`, `llm_calls=1`, `llm_cost_usd > 0` (well under $0.01). A second run of the same script against the unchanged page should show `llm_calls=0` on the second crawl (cache hit).

---

## 9. Exit criteria

- `uv run pytest` green (all Phase 2 tests plus prior Phase 1)
- `uv run ruff check .` clean; `uv run ruff format --check .` clean
- `uv run mypy src` clean with strict config
- `docker compose up -d` runs three services; API returns 200 on `/healthz` and `/readyz`
- `scripts/smoke_phase2.sh` succeeds end-to-end against the real Lil Sluggers URL with a real API key
- Second run of the smoke against the unchanged page reports `llm_calls=0` (cache hit observed)
- No silent failures: every fetch/extract failure appears in `crawl_runs.error_text`
- `/docs` (OpenAPI UI) lists all 7 site-management endpoints with working schemas

## 10. Open questions / deferred

- **Withdrawn resurrection** — if it causes noise, revisit the reconciler to resurrect rather than re-insert.
- **HTML normalization aggressiveness** — conservative default; tune after observing churn rates in `crawl_runs`.
- **LLM prompt versioning** — a `prompt_version` field on `extraction_cache` could let us invalidate cache on prompt changes. Deferred; for Phase 2, changing the prompt manually requires wiping the cache table.
- **Playwright browser reuse across worker restarts** — currently launched per-worker-lifetime; a shared daemon would be more efficient but YAGNI at one worker.
- **Per-site rate-limit headers** — not honored in Phase 2 (we use fixed backoff on 429). If a target site complains, revisit.
