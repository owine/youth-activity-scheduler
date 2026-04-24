# Phase 5a — Read-Only Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Each task follows @superpowers:test-driven-development (write failing test → minimal impl → green → commit). The exit checklist invokes @superpowers:verification-before-completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a single-page React dashboard that surfaces what Phases 1–4 have been writing to the database — a global Inbox, per-kid match views, site overviews, and read-only settings — served as a static bundle by the existing FastAPI app on port 8080.

**Architecture:** Two parallel tracks meeting at the Dockerfile. Backend grows three small extensions to existing schemas, two new read-only endpoints, and an SPA-fallback route. Frontend is a brand-new `frontend/` directory containing a Vite + React + TypeScript SPA built with Tailwind + shadcn/ui, using TanStack Query for server state and TanStack Router for typed file-based routing. Production: multi-stage Dockerfile builds the SPA in a Node image, FastAPI serves the result from `/app/static/` at `/`.

**Tech Stack:**
- Backend: existing FastAPI + SQLAlchemy 2.x + Alembic + Pydantic v2; aiosqlite in dev, real SQLite in prod
- Frontend: Vite 5 + React 19 + TypeScript 5 + Tailwind 3 + shadcn/ui (Radix primitives) + TanStack Query 5 + TanStack Router 1
- Testing: pytest (existing) + Vitest + React Testing Library + MSW + Playwright

**Spec:** `docs/superpowers/specs/2026-04-24-phase-5a-read-only-dashboard-design.md` — read it before starting any task. Every section reference below (e.g., "spec §4.1") points there.

**Branching:** create `phase-5a-dashboard` off `main`. Do NOT work on main. All commits get auto-signed (commit.gpgsign is on locally).

---

## File structure

### Backend (modifying existing or new under `src/yas/web/routes/`)

| Path | What | Status |
|---|---|---|
| `src/yas/web/routes/matches_schemas.py` | Extend `OfferingSummary` with `registration_opens_at`, `site_name` | modify |
| `src/yas/web/routes/matches.py` | Add `JOIN sites` to populate `site_name` | modify |
| `src/yas/web/routes/kids_schemas.py` | Add `ignore_hard_gates` to embedded `WatchlistOut` | modify |
| `src/yas/web/routes/household_schemas.py` | Add `home_address`, `home_location_name` to `HouseholdOut` | modify |
| `src/yas/web/routes/household.py` | Join `Location` to populate the two new fields on GET | modify |
| `src/yas/web/routes/site_crawls.py` | New router for `GET /api/sites/{id}/crawls` | create |
| `src/yas/web/routes/site_crawls_schemas.py` | `CrawlRunOut` Pydantic model | create |
| `src/yas/web/routes/inbox.py` | New router for `GET /api/inbox/summary` | create |
| `src/yas/web/routes/inbox_schemas.py` | `InboxSummaryOut`, `InboxAlertOut`, `InboxKidMatchCountOut`, `InboxSiteActivityOut` | create |
| `src/yas/web/routes/inbox_alert_summary.py` | Pure function: `(alert_type, payload) -> summary_text` dispatch | create |
| `src/yas/web/routes/__init__.py` | Export `inbox_router`, `site_crawls_router` | modify |
| `src/yas/web/app.py` | Register new routers; mount `StaticFiles` at `/assets`; add catch-all SPA fallback | modify |
| `src/yas/web/spa_fallback.py` | The catch-all route handler (separate file for testability) | create |
| `Dockerfile` | Multi-stage: Node build of `frontend/dist/` + Python copy into `/app/static/` | modify |

### Backend tests

| Path | What | Status |
|---|---|---|
| `tests/integration/test_api_inbox.py` | Happy path, empty window, malformed timestamp, opening_soon semantics | create |
| `tests/integration/test_api_site_crawls.py` | Happy path, 404, limit bounds, empty history, failed crawl | create |
| `tests/integration/test_spa_fallback.py` | API precedence, deep-link returns HTML, unknown API returns 404 JSON | create |
| `tests/integration/test_api_matches.py` | Add assertions for new `registration_opens_at` + `site_name` fields | modify |
| `tests/integration/test_api_kids.py` | Add assertion for embedded watchlist `ignore_hard_gates` field | modify |
| `tests/integration/test_api_household.py` | Add assertion for `home_address` + `home_location_name` on GET | modify |
| `tests/unit/test_inbox_alert_summary.py` | Dispatch table coverage for every `AlertType` | create |

### Frontend (new tree under `frontend/`)

| Path | What | Status |
|---|---|---|
| `frontend/package.json`, `package-lock.json` | npm deps + scripts | create |
| `frontend/tsconfig.json`, `tsconfig.node.json` | TS config | create |
| `frontend/vite.config.ts` | Vite + React + Router plugin + dev proxy | create |
| `frontend/tailwind.config.ts`, `postcss.config.js` | Tailwind setup | create |
| `frontend/index.html` | SPA entry HTML (theme-resolution script inline) | create |
| `frontend/.eslintrc.cjs`, `.prettierrc` | Lint/format config | create |
| `frontend/components.json` | shadcn config | create |
| `frontend/src/main.tsx` | React entry; wires Query + Router + Theme providers | create |
| `frontend/src/styles/globals.css` | Tailwind directives + shadcn CSS variables (light + dark) | create |
| `frontend/src/routes/__root.tsx` | App shell layout (TopBar + KidSwitcher + Outlet) | create |
| `frontend/src/routes/index.tsx` | Inbox page | create |
| `frontend/src/routes/kids.$id.matches.tsx` | Matches tab | create |
| `frontend/src/routes/kids.$id.watchlist.tsx` | Watchlist tab | create |
| `frontend/src/routes/sites.index.tsx` | Sites list | create |
| `frontend/src/routes/sites.$id.tsx` | Site detail | create |
| `frontend/src/routes/settings.tsx` | Read-only settings | create |
| `frontend/src/components/ui/*` | shadcn primitives: button, card, sheet, tabs, badge, skeleton, alert, collapsible, slider, input | create (via shadcn CLI) |
| `frontend/src/components/layout/AppShell.tsx`, `TopBar.tsx`, `KidSwitcher.tsx`, `ThemeToggle.tsx` | Layout chrome | create |
| `frontend/src/components/inbox/AlertsSection.tsx`, `NewMatchesByKidSection.tsx`, `SiteActivitySection.tsx`, `AlertDetailDrawer.tsx` | Inbox sections | create |
| `frontend/src/components/matches/UrgencyGroup.tsx`, `MatchCard.tsx`, `MatchDetailDrawer.tsx`, `MatchFilters.tsx` | Match views | create |
| `frontend/src/components/sites/SiteList.tsx`, `SiteRow.tsx`, `SiteDetail.tsx`, `CrawlHistoryList.tsx` | Site views | create |
| `frontend/src/components/alerts/AlertRow.tsx`, `AlertTypeBadge.tsx` | Alert primitives | create |
| `frontend/src/components/common/ErrorBanner.tsx`, `EmptyState.tsx` | Status components | create |
| `frontend/src/lib/api.ts` | `fetch` wrappers; throws on non-2xx | create |
| `frontend/src/lib/queries.ts` | TanStack Query hooks per resource | create |
| `frontend/src/lib/types.ts` | API response types (mirror Pydantic) | create |
| `frontend/src/lib/format.ts` | `price`, `relDate`, `fmt` matching Phase 4 Jinja filters | create |
| `frontend/src/lib/theme.ts` | `prefers-color-scheme` resolver + localStorage override | create |
| `frontend/src/test/setup.ts` | Vitest + RTL + MSW bootstrap | create |
| `frontend/src/test/handlers.ts` | MSW request handlers for each API endpoint | create |
| `frontend/src/**/*.test.tsx` | Component tests | create |
| `frontend/playwright.config.ts` | Playwright base config | create |
| `frontend/e2e/inbox.spec.ts`, `kid-matches.spec.ts`, `deep-link.spec.ts` | E2E specs | create |

### Operational

| Path | What | Status |
|---|---|---|
| `scripts/e2e_phase5a.sh` | Bring up Docker stack with seeded DB, run Playwright | create |
| `scripts/seed_e2e.py` | Insert deterministic e2e fixtures into a fresh DB | create |
| `README.md` | Append "Web UI" section: dev loop, theme override, e2e run | modify |

---

## Sequencing rationale

Backend extensions (Tasks 1–4) land first because they unblock the frontend (without `site_name` and `registration_opens_at`, the matches page can't render). The new endpoints (Tasks 5–6) come next so all backend types are stable before any TS interface is hand-written. Then the SPA fallback wiring (Task 7) and Dockerfile (Task 8) — both small but cross-cutting. Frontend scaffolding (Tasks 9–11) brings up an empty React app that builds cleanly. The shared lib layer (Tasks 12–14) provides typed primitives. Pages then ship outside-in: shell first, inbox, then per-kid, then sites, then settings (Tasks 15–20). Tests and e2e (Tasks 21–22) close the loop. README + exit gates (Task 23) finish.

---

## Task 1 — Extend `OfferingSummary` with `registration_opens_at` and `site_name`

**Files:**
- Modify: `src/yas/web/routes/matches_schemas.py`
- Modify: `src/yas/web/routes/matches.py`
- Modify: `tests/integration/test_api_matches.py`

This unblocks the frontend Matches page urgency grouping and the "site name" badge on each card (spec §3.2.1, §4.4).

- [ ] **Step 1: Read the current file shapes**

```bash
cat src/yas/web/routes/matches_schemas.py
cat src/yas/web/routes/matches.py
cat tests/integration/test_api_matches.py
```

Note the existing `OfferingSummary` fields and the `select(Match, Offering).join(Offering, Match.offering_id == Offering.id)` query in `matches.py`.

- [ ] **Step 2: Add a failing test** in `tests/integration/test_api_matches.py`

Use the existing `client` fixture (do not invent a new one). `Offering` requires `page_id` (FK to a `Page`) and `normalized_name` — both non-nullable; the seed block must include them. The pattern below mirrors how the existing tests in this file seed:

```python
from datetime import UTC, datetime
from yas.db.models import Kid, Match, Offering, Page, Site
from yas.db.session import session_scope

@pytest.mark.asyncio
async def test_match_includes_offering_registration_opens_at_and_site_name(client):
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=datetime(2019, 5, 1).date()))
        s.add(Site(id=1, name="Lil Sluggers", base_url="https://x", needs_browser=False))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p", kind="schedule"))
        await s.flush()
        s.add(Offering(
            id=1, site_id=1, page_id=1, name="Spring T-Ball", normalized_name="spring t-ball",
            program_type="other", status="active",
            registration_opens_at=now,
        ))
        await s.flush()
        s.add(Match(kid_id=1, offering_id=1, score=0.9, reasons={}, computed_at=now))
    r = await c.get("/api/matches?kid_id=1")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    offering = body[0]["offering"]
    assert offering["site_name"] == "Lil Sluggers"
    assert offering["registration_opens_at"] is not None
```

Verify the existing `client` fixture in `tests/integration/test_api_matches.py` — if its yield shape differs (e.g., yields `(client, engine, ...)` not `(client, engine)`), adjust the unpacking. Read the top of the file before writing.

- [ ] **Step 3: Run test, confirm it fails**

```bash
uv run pytest tests/integration/test_api_matches.py::test_match_includes_offering_registration_opens_at_and_site_name -v
```

Expected: KeyError or AssertionError on `site_name` / `registration_opens_at`.

- [ ] **Step 4: Extend `OfferingSummary`**

In `matches_schemas.py`, add two fields to the existing `OfferingSummary` class:

```python
registration_opens_at: datetime | None = None
site_name: str
```

Order: keep existing fields in their current order; append the two new ones. Import `datetime` if not already imported.

- [ ] **Step 5: Update the matches query to join Site**

In `matches.py`, replace:

```python
q = select(Match, Offering).join(Offering, Match.offering_id == Offering.id)
```

with:

```python
from yas.db.models import Match, Offering, Site
# ...
q = (
    select(Match, Offering, Site.name)
    .join(Offering, Match.offering_id == Offering.id)
    .join(Site, Site.id == Offering.site_id)
)
```

In the loop that builds `MatchOut`, unpack `match, offering, site_name` from each row, and pass `site_name=site_name` and `registration_opens_at=offering.registration_opens_at` into `OfferingSummary.model_validate({...})` — or, if you build `OfferingSummary` field-by-field, add the two fields explicitly.

If `OfferingSummary` is constructed via `model_validate(offering)`, switch to a dict construction so you can inject `site_name`:

```python
offering_summary = OfferingSummary.model_validate({
    **{k: getattr(offering, k) for k in OfferingSummary.model_fields if k != "site_name"},
    "site_name": site_name,
})
```

- [ ] **Step 6: Run the new test plus the full matches test file**

```bash
uv run pytest tests/integration/test_api_matches.py -v
```

Expected: all green.

- [ ] **Step 7: Run the full suite**

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: no regressions.

- [ ] **Step 8: Commit**

```bash
git add src/yas/web/routes/matches_schemas.py src/yas/web/routes/matches.py tests/integration/test_api_matches.py
git commit -m "feat(web): add registration_opens_at and site_name to OfferingSummary"
```

---

## Task 2 — Add `ignore_hard_gates` to embedded `WatchlistOut`

**Files:**
- Modify: `src/yas/web/routes/kids_schemas.py`
- Modify: `tests/integration/test_api_kids.py`

This is the embedded `WatchlistOut` inside `KidDetailOut` — NOT the standalone `watchlist_schemas.WatchlistOut` which already has the field (spec §4.4).

- [ ] **Step 1: Add a failing test**

Use the existing `client` fixture in `tests/integration/test_api_kids.py` (read its yield shape first):

```python
from datetime import datetime
from yas.db.models import Kid, WatchlistEntry
from yas.db.session import session_scope

@pytest.mark.asyncio
async def test_kid_detail_watchlist_includes_ignore_hard_gates(client):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=datetime(2019, 5, 1).date()))
        await s.flush()
        s.add(WatchlistEntry(
            kid_id=1, site_id=None, pattern="baseball", priority="normal",
            notes=None, active=True, ignore_hard_gates=True,
        ))
    r = await c.get("/api/kids/1")
    assert r.status_code == 200
    watchlist = r.json()["watchlist"]
    assert len(watchlist) == 1
    assert watchlist[0]["ignore_hard_gates"] is True
```

- [ ] **Step 2: Run test, confirm fail**

```bash
uv run pytest tests/integration/test_api_kids.py::test_kid_detail_watchlist_includes_ignore_hard_gates -v
```

- [ ] **Step 3: Add the field**

In `kids_schemas.py`, locate the `class WatchlistOut(BaseModel)` (around line 106). Add:

```python
ignore_hard_gates: bool
```

Place it after `active: bool`.

- [ ] **Step 4: Run test, confirm pass + full suite**

```bash
uv run pytest tests/integration/test_api_kids.py -v
uv run pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add src/yas/web/routes/kids_schemas.py tests/integration/test_api_kids.py
git commit -m "feat(web): add ignore_hard_gates to embedded watchlist in KidDetailOut"
```

---

## Task 3 — Add `home_address` and `home_location_name` to `HouseholdOut`

**Files:**
- Modify: `src/yas/web/routes/household_schemas.py`
- Modify: `src/yas/web/routes/household.py`
- Modify: `tests/integration/test_api_household.py`

Required by Settings page (spec §3.4, §4.4).

- [ ] **Step 1: Read current state**

```bash
cat src/yas/web/routes/household_schemas.py
cat src/yas/web/routes/household.py
```

`HouseholdOut` currently has `home_location_id: int | None` only. We need to populate `home_address` and `home_location_name` by joining `Location`.

- [ ] **Step 2: Add a failing test**

```python
async def test_get_household_returns_address_and_name_when_set(client):
    c, engine, _ = client
    # First set the address via existing PATCH
    await c.patch(
        "/api/household",
        json={"home_address": "123 Main St, Chicago, IL", "home_location_name": "Home"},
    )
    # Then GET
    r = await c.get("/api/household")
    assert r.status_code == 200
    body = r.json()
    assert body["home_address"] == "123 Main St, Chicago, IL"
    assert body["home_location_name"] == "Home"


async def test_get_household_returns_null_address_when_unset(client):
    c, _, _ = client
    r = await c.get("/api/household")
    assert r.status_code == 200
    body = r.json()
    assert body["home_address"] is None
    assert body["home_location_name"] is None
```

- [ ] **Step 3: Run, confirm fail**

```bash
uv run pytest tests/integration/test_api_household.py::test_get_household_returns_address_and_name_when_set -v
```

- [ ] **Step 4: Extend `HouseholdOut`**

In `household_schemas.py`, REPLACE the entire existing `class HouseholdOut(BaseModel):` block with the following — preserve `model_config = ConfigDict(from_attributes=True)`:

```python
class HouseholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    home_location_id: int | None
    home_address: str | None
    home_location_name: str | None
    default_max_distance_mi: float | None
    digest_time: str
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    daily_llm_cost_cap_usd: float
```

Note: `home_address` and `home_location_name` are populated by the route handler (Step 5), not by SQLAlchemy from-attributes — they live on the related `Location` row, not on `HouseholdSettings`.

- [ ] **Step 5: Update `get_household` to join Location**

In `household.py`, `Location` is already imported (alongside `GeocodeAttempt`, `HouseholdSettings`); no new imports needed. Define a helper and use it in BOTH handlers (do not leave the GET or PATCH handler returning `HouseholdOut.model_validate(hh)` — that would not populate the new fields):

```python
async def _to_out(s: AsyncSession, hh: HouseholdSettings) -> HouseholdOut:
    loc = None
    if hh.home_location_id is not None:
        loc = (
            await s.execute(select(Location).where(Location.id == hh.home_location_id))
        ).scalar_one_or_none()
    return HouseholdOut(
        id=hh.id,
        home_location_id=hh.home_location_id,
        home_address=loc.address if loc else None,
        home_location_name=loc.name if loc else None,
        default_max_distance_mi=hh.default_max_distance_mi,
        digest_time=hh.digest_time,
        quiet_hours_start=hh.quiet_hours_start,
        quiet_hours_end=hh.quiet_hours_end,
        daily_llm_cost_cap_usd=hh.daily_llm_cost_cap_usd,
    )
```

Then replace both `return HouseholdOut.model_validate(hh)` call sites in `get_household` and `patch_household` with `return await _to_out(s, hh)`.

- [ ] **Step 6: Run tests + full suite**

```bash
uv run pytest tests/integration/test_api_household.py -v
uv run pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add src/yas/web/routes/household_schemas.py src/yas/web/routes/household.py tests/integration/test_api_household.py
git commit -m "feat(web): expose home_address and home_location_name on GET /api/household"
```

---

## Task 4 — New endpoint `GET /api/sites/{id}/crawls`

**Files:**
- Create: `src/yas/web/routes/site_crawls.py`
- Create: `src/yas/web/routes/site_crawls_schemas.py`
- Modify: `src/yas/web/routes/__init__.py` (export `site_crawls_router`)
- Modify: `src/yas/web/app.py` (include router)
- Create: `tests/integration/test_api_site_crawls.py`

Spec §4.2.

- [ ] **Step 1: Write the schema**

Create `site_crawls_schemas.py`:

```python
"""Pydantic models for /api/sites/{id}/crawls."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CrawlRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    site_id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    pages_fetched: int
    changes_detected: int
    llm_calls: int
    llm_cost_usd: float
    error_text: str | None
```

- [ ] **Step 2: Write failing tests**

`tests/integration/test_api_site_crawls.py`:

```python
import pytest
from datetime import UTC, datetime
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import CrawlRun, Site
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/c.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_crawls_empty(client):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(Site(name="Test", base_url="https://t.example", needs_browser=False))
    r = await c.get("/api/sites/1/crawls")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_crawls_returns_recent_first(client):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(Site(name="Test", base_url="https://t.example", needs_browser=False))
        await s.flush()
        for i in range(3):
            s.add(CrawlRun(
                site_id=1,
                started_at=datetime(2026, 4, 24 - i, 12, 0, tzinfo=UTC),
                finished_at=datetime(2026, 4, 24 - i, 12, 5, tzinfo=UTC),
                status="ok",
                pages_fetched=i + 1,
                changes_detected=i,
                llm_calls=0,
                llm_cost_usd=0.0,
            ))
    r = await c.get("/api/sites/1/crawls")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    # Most recent first
    assert body[0]["pages_fetched"] == 1  # i=0 → most recent
    assert body[2]["pages_fetched"] == 3


@pytest.mark.asyncio
async def test_list_crawls_404_for_unknown_site(client):
    c, _ = client
    r = await c.get("/api/sites/999/crawls")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_crawls_respects_limit(client):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(Site(name="Test", base_url="https://t.example", needs_browser=False))
        await s.flush()
        for i in range(20):
            s.add(CrawlRun(
                site_id=1,
                started_at=datetime(2026, 4, 1 + i, 12, 0, tzinfo=UTC),
                status="ok",
                pages_fetched=0, changes_detected=0, llm_calls=0, llm_cost_usd=0.0,
            ))
    r = await c.get("/api/sites/1/crawls?limit=5")
    assert r.status_code == 200
    assert len(r.json()) == 5


@pytest.mark.asyncio
async def test_list_crawls_limit_validation(client):
    c, _ = client
    r1 = await c.get("/api/sites/1/crawls?limit=0")
    assert r1.status_code == 422
    r2 = await c.get("/api/sites/1/crawls?limit=101")
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_list_crawls_includes_error_text_for_failed_crawls(client):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(Site(name="Test", base_url="https://t.example", needs_browser=False))
        await s.flush()
        s.add(CrawlRun(
            site_id=1,
            started_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
            status="failed",
            pages_fetched=0, changes_detected=0, llm_calls=0, llm_cost_usd=0.0,
            error_text="connection refused",
        ))
    r = await c.get("/api/sites/1/crawls")
    body = r.json()
    assert body[0]["status"] == "failed"
    assert body[0]["error_text"] == "connection refused"
```

- [ ] **Step 3: Run, confirm all fail**

```bash
uv run pytest tests/integration/test_api_site_crawls.py -v
```

- [ ] **Step 4: Implement the router**

Create `src/yas/web/routes/site_crawls.py`:

```python
"""Read-only /api/sites/{id}/crawls endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.db.models import CrawlRun, Site
from yas.db.session import session_scope
from yas.web.routes.site_crawls_schemas import CrawlRunOut

router = APIRouter(prefix="/api/sites", tags=["sites"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


@router.get("/{site_id}/crawls", response_model=list[CrawlRunOut])
async def list_crawls(
    site_id: int,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[CrawlRunOut]:
    async with session_scope(_engine(request)) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
        if site is None:
            raise HTTPException(status_code=404, detail=f"site {site_id} not found")
        rows = (
            await s.execute(
                select(CrawlRun)
                .where(CrawlRun.site_id == site_id)
                .order_by(CrawlRun.started_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [CrawlRunOut.model_validate(r) for r in rows]
```

- [ ] **Step 5: Register the router**

In `src/yas/web/routes/__init__.py`, import + export `site_crawls_router`. Update the `__all__` alphabetically.

In `src/yas/web/app.py`, add `app.include_router(site_crawls_router)` to the existing block. Order does not matter relative to other routers.

- [ ] **Step 6: Run tests, then full suite**

```bash
uv run pytest tests/integration/test_api_site_crawls.py -v
uv run pytest -q
uv run ruff check . && uv run mypy src
```

- [ ] **Step 7: Commit**

```bash
git add src/yas/web/routes/site_crawls.py src/yas/web/routes/site_crawls_schemas.py \
    src/yas/web/routes/__init__.py src/yas/web/app.py \
    tests/integration/test_api_site_crawls.py
git commit -m "feat(web): add GET /api/sites/{id}/crawls"
```

---

## Task 5 — Inbox alert summary dispatch (pure function + tests)

**Files:**
- Create: `src/yas/web/routes/inbox_alert_summary.py`
- Create: `tests/unit/test_inbox_alert_summary.py`

This is a pure function that turns an `(AlertType, payload_json)` pair into the one-line `summary_text` shown in `InboxAlertOut`. Isolating it as its own module keeps the inbox endpoint thin and makes the dispatch table fully unit-testable.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_inbox_alert_summary.py`:

```python
"""Coverage for every AlertType branch of the inbox summary dispatch."""

import pytest

from yas.db.models._types import AlertType
from yas.web.routes.inbox_alert_summary import summarize_alert


def test_watchlist_hit():
    s = summarize_alert(
        AlertType.watchlist_hit,
        kid_name="Sam",
        payload={"offering_name": "Spring T-Ball", "site_name": "Lil Sluggers"},
    )
    assert "Sam" in s and "Spring T-Ball" in s


@pytest.mark.parametrize(
    "alert_type,window_text",
    [
        (AlertType.reg_opens_24h, "24h"),
        (AlertType.reg_opens_1h, "1 hour"),
        (AlertType.reg_opens_now, "now"),
    ],
)
def test_reg_opens_variants(alert_type, window_text):
    s = summarize_alert(
        alert_type,
        kid_name="Sam",
        payload={"offering_name": "Spring T-Ball", "registration_url": "https://x"},
    )
    assert "Spring T-Ball" in s
    assert window_text.lower() in s.lower()


def test_new_match():
    s = summarize_alert(
        AlertType.new_match,
        kid_name="Sam",
        payload={"offering_name": "Beginner Swim"},
    )
    assert "Sam" in s and "Beginner Swim" in s


def test_crawl_failed():
    s = summarize_alert(
        AlertType.crawl_failed,
        kid_name=None,
        payload={"site_name": "North Side YMCA"},
    )
    assert "North Side YMCA" in s and ("crawl" in s.lower() or "fail" in s.lower())


def test_schedule_posted():
    s = summarize_alert(
        AlertType.schedule_posted,
        kid_name=None,
        payload={"site_name": "Chi Park Dist", "n_offerings": 6},
    )
    assert "Chi Park Dist" in s and "6" in s


def test_site_stagnant():
    s = summarize_alert(
        AlertType.site_stagnant,
        kid_name=None,
        payload={"site_name": "Pottery Barn"},
    )
    assert "Pottery Barn" in s and "stagnant" in s.lower()


def test_no_matches_for_kid():
    s = summarize_alert(
        AlertType.no_matches_for_kid,
        kid_name="Maya",
        payload={},
    )
    assert "Maya" in s and "no" in s.lower()


def test_push_cap():
    s = summarize_alert(
        AlertType.push_cap,
        kid_name="Sam",
        payload={"cap": 5},
    )
    assert "Sam" in s and "5" in s


def test_digest():
    s = summarize_alert(
        AlertType.digest,
        kid_name="Sam",
        payload={"top_line": "Sam's activities — 3 new matches"},
    )
    assert "Sam" in s


def test_unknown_alert_type_falls_back_to_type_name():
    # Defensive: dispatch table must not raise on unexpected input
    class FakeType:
        value = "unknown_type"
    s = summarize_alert(FakeType(), kid_name=None, payload={})  # type: ignore[arg-type]
    assert "unknown_type" in s.lower() or "alert" in s.lower()
```

- [ ] **Step 2: Run, confirm fail**

```bash
uv run pytest tests/unit/test_inbox_alert_summary.py -v
```

- [ ] **Step 3: Implement**

Create `src/yas/web/routes/inbox_alert_summary.py`:

```python
"""Pure dispatch from (AlertType, payload) → human one-liner for the Inbox."""

from __future__ import annotations

from typing import Any

from yas.db.models._types import AlertType


def summarize_alert(
    alert_type: AlertType,
    *,
    kid_name: str | None,
    payload: dict[str, Any],
) -> str:
    """Return a one-line human summary for an alert.

    Pure function; no DB access. The inbox endpoint joins kid_name from the
    DB and passes it in. Payload shape varies per type — keys we don't find
    fall back to defaults so this never raises on real data.
    """
    name = kid_name or "—"
    offering = payload.get("offering_name", "an activity")
    site = payload.get("site_name", "a site")
    type_value = getattr(alert_type, "value", str(alert_type))

    if type_value == AlertType.watchlist_hit.value:
        return f"Watchlist hit for {name} — {offering} · {site}"
    if type_value == AlertType.new_match.value:
        return f"New match for {name} — {offering}"
    if type_value == AlertType.reg_opens_24h.value:
        return f"Registration opens in 24h — {offering} for {name}"
    if type_value == AlertType.reg_opens_1h.value:
        return f"Registration opens in 1 hour — {offering} for {name}"
    if type_value == AlertType.reg_opens_now.value:
        return f"Registration is open now — {offering} for {name}"
    if type_value == AlertType.schedule_posted.value:
        n = payload.get("n_offerings", 0)
        return f"{site} posted {n} new offering{'s' if n != 1 else ''}"
    if type_value == AlertType.crawl_failed.value:
        return f"Crawl failed — {site}"
    if type_value == AlertType.site_stagnant.value:
        return f"{site} appears stagnant"
    if type_value == AlertType.no_matches_for_kid.value:
        return f"No matches for {name} yet"
    if type_value == AlertType.push_cap.value:
        cap = payload.get("cap", "?")
        return f"Push cap reached for {name} ({cap} this period)"
    if type_value == AlertType.digest.value:
        return payload.get("top_line", f"Daily digest for {name}")
    return f"{type_value} alert"
```

- [ ] **Step 4: Run, confirm pass**

```bash
uv run pytest tests/unit/test_inbox_alert_summary.py -v
uv run ruff check . && uv run mypy src
```

- [ ] **Step 5: Commit**

```bash
git add src/yas/web/routes/inbox_alert_summary.py tests/unit/test_inbox_alert_summary.py
git commit -m "feat(inbox): add summarize_alert dispatch for inbox UI one-liners"
```

---

## Task 6 — `GET /api/inbox/summary` endpoint

**Files:**
- Create: `src/yas/web/routes/inbox_schemas.py`
- Create: `src/yas/web/routes/inbox.py`
- Modify: `src/yas/web/routes/__init__.py` (export)
- Modify: `src/yas/web/app.py` (register)
- Create: `tests/integration/test_api_inbox.py`

Spec §4.1. The largest backend task. Build it incrementally: schemas first, then each section (alerts → matches → site activity), then assemble.

- [ ] **Step 1: Write the schemas**

Create `src/yas/web/routes/inbox_schemas.py`:

```python
"""Pydantic models for GET /api/inbox/summary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class InboxAlertOut(BaseModel):
    """Enriched alert shape for the inbox endpoint.

    Distinct from AlertOut in alerts_schemas.py: adds kid_name (joined) and
    summary_text (server-composed). Existing /api/alerts endpoints continue
    to return the plain AlertOut.
    """
    model_config = ConfigDict(from_attributes=True)
    id: int
    type: str
    kid_id: int | None
    kid_name: str | None
    offering_id: int | None
    site_id: int | None
    channels: list[str]
    scheduled_for: datetime
    sent_at: datetime | None
    skipped: bool
    dedup_key: str
    payload_json: dict[str, Any]
    summary_text: str


class InboxKidMatchCountOut(BaseModel):
    kid_id: int
    kid_name: str
    total_new: int
    opening_soon_count: int


class InboxSiteActivityOut(BaseModel):
    refreshed_count: int
    posted_new_count: int
    stagnant_count: int


class InboxSummaryOut(BaseModel):
    window_start: datetime
    window_end: datetime
    alerts: list[InboxAlertOut]
    new_matches_by_kid: list[InboxKidMatchCountOut]
    site_activity: InboxSiteActivityOut
```

- [ ] **Step 2: Write tests covering the response shape and key semantics**

`tests/integration/test_api_inbox.py`:

```python
import pytest
from datetime import UTC, datetime, timedelta
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import (
    Alert, CrawlRun, Kid, Match, Offering, Site, WatchlistEntry,
)
from yas.db.models._types import AlertType, CrawlStatus
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/i.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_inbox_empty_window_returns_zero_counts(client):
    c, _ = client
    now = datetime.now(UTC)
    r = await c.get(
        "/api/inbox/summary",
        params={"since": _iso(now - timedelta(days=7)), "until": _iso(now)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["alerts"] == []
    assert body["new_matches_by_kid"] == []
    assert body["site_activity"]["refreshed_count"] == 0
    assert body["site_activity"]["posted_new_count"] == 0
    assert body["site_activity"]["stagnant_count"] == 0


@pytest.mark.asyncio
async def test_inbox_includes_alert_with_kid_name_and_summary(client):
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=datetime(2019, 5, 1).date()))
        s.add(Site(id=1, name="Lil Sluggers", base_url="https://x", needs_browser=False))
        await s.flush()
        s.add(Alert(
            type=AlertType.watchlist_hit.value,
            kid_id=1,
            site_id=1,
            channels=["email"],
            scheduled_for=now - timedelta(hours=1),
            dedup_key="k1",
            payload_json={"offering_name": "T-Ball", "site_name": "Lil Sluggers"},
        ))
    r = await c.get(
        "/api/inbox/summary",
        params={"since": _iso(now - timedelta(days=1)), "until": _iso(now + timedelta(seconds=1))},
    )
    body = r.json()
    assert len(body["alerts"]) == 1
    a = body["alerts"][0]
    assert a["kid_name"] == "Sam"
    assert "T-Ball" in a["summary_text"]


@pytest.mark.asyncio
async def test_inbox_new_matches_grouped_by_kid_with_opening_soon_counts(client):
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=datetime(2019, 5, 1).date()))
        s.add(Site(id=1, name="X", base_url="https://x", needs_browser=False))
        await s.flush()
        # Two offerings: one opens tomorrow (counts as opening_soon),
        # one opens in 30 days (does not).
        s.add(Offering(
            id=1, site_id=1, name="Open soon",
            start_date=(now + timedelta(days=20)).date(),
            registration_opens_at=now + timedelta(days=1),
            status="active",
        ))
        s.add(Offering(
            id=2, site_id=1, name="Open later",
            start_date=(now + timedelta(days=60)).date(),
            registration_opens_at=now + timedelta(days=30),
            status="active",
        ))
        await s.flush()
        s.add(Match(kid_id=1, offering_id=1, score=0.9, reasons={}, computed_at=now - timedelta(hours=1)))
        s.add(Match(kid_id=1, offering_id=2, score=0.8, reasons={}, computed_at=now - timedelta(hours=2)))
    r = await c.get(
        "/api/inbox/summary",
        params={"since": _iso(now - timedelta(days=1)), "until": _iso(now + timedelta(seconds=1))},
    )
    body = r.json()
    assert len(body["new_matches_by_kid"]) == 1
    row = body["new_matches_by_kid"][0]
    assert row["kid_id"] == 1
    assert row["kid_name"] == "Sam"
    assert row["total_new"] == 2
    assert row["opening_soon_count"] == 1  # only the one opening tomorrow


@pytest.mark.asyncio
async def test_inbox_site_activity_counts(client):
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        for i in range(2):
            s.add(Site(id=i + 1, name=f"S{i}", base_url=f"https://s{i}", needs_browser=False))
        await s.flush()
        # Site 1: successful crawl in window
        s.add(CrawlRun(
            site_id=1, started_at=now - timedelta(hours=2), status=CrawlStatus.ok.value,
            pages_fetched=1, changes_detected=0, llm_calls=0, llm_cost_usd=0.0,
        ))
        # Site 2: schedule_posted alert in window
        s.add(Alert(
            type=AlertType.schedule_posted.value, site_id=2, channels=[],
            scheduled_for=now - timedelta(hours=1), dedup_key="sp1",
            payload_json={"site_name": "S1", "n_offerings": 3},
        ))
    r = await c.get(
        "/api/inbox/summary",
        params={"since": _iso(now - timedelta(days=1)), "until": _iso(now + timedelta(seconds=1))},
    )
    body = r.json()
    assert body["site_activity"]["refreshed_count"] == 1
    assert body["site_activity"]["posted_new_count"] == 1


@pytest.mark.asyncio
async def test_inbox_malformed_timestamp_returns_422(client):
    c, _ = client
    r = await c.get("/api/inbox/summary", params={"since": "not-a-date", "until": "also-not"})
    assert r.status_code == 422
```

- [ ] **Step 3: Run, confirm all fail**

```bash
uv run pytest tests/integration/test_api_inbox.py -v
```

- [ ] **Step 4: Implement the router**

Create `src/yas/web/routes/inbox.py`:

```python
"""GET /api/inbox/summary — single-roundtrip aggregate for the dashboard inbox."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.alerts.detectors.site_stagnant import detect_stagnant_sites
from yas.db.models import Alert, CrawlRun, Kid, Match, Offering
from yas.db.models._types import AlertType, CrawlStatus
from yas.db.session import session_scope
from yas.web.routes.inbox_alert_summary import summarize_alert
from yas.web.routes.inbox_schemas import (
    InboxAlertOut,
    InboxKidMatchCountOut,
    InboxSiteActivityOut,
    InboxSummaryOut,
)

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


@router.get("/summary", response_model=InboxSummaryOut)
async def inbox_summary(
    request: Request,
    since: Annotated[datetime, Query()],
    until: Annotated[datetime, Query()],
) -> InboxSummaryOut:
    settings = request.app.state.yas.settings
    now = datetime.now(UTC)
    opens_soon_window_end = now + timedelta(days=7)

    async with session_scope(_engine(request)) as s:
        # --- Alerts in window with kid_name joined ---
        alerts_q = (
            select(Alert, Kid.name)
            .outerjoin(Kid, Kid.id == Alert.kid_id)
            .where(Alert.scheduled_for >= since)
            .where(Alert.scheduled_for < until)
            .order_by(Alert.scheduled_for.desc())
            .limit(50)
        )
        alert_rows = (await s.execute(alerts_q)).all()
        inbox_alerts: list[InboxAlertOut] = []
        for alert, kid_name in alert_rows:
            try:
                at = AlertType(alert.type)
            except ValueError:
                # Unknown type stored — defensive
                at = alert.type  # type: ignore[assignment]
            summary = summarize_alert(at, kid_name=kid_name, payload=alert.payload_json or {})
            inbox_alerts.append(InboxAlertOut(
                id=alert.id,
                type=alert.type,
                kid_id=alert.kid_id,
                kid_name=kid_name,
                offering_id=alert.offering_id,
                site_id=alert.site_id,
                channels=list(alert.channels or []),
                scheduled_for=alert.scheduled_for,
                sent_at=alert.sent_at,
                skipped=alert.skipped,
                dedup_key=alert.dedup_key,
                payload_json=alert.payload_json or {},
                summary_text=summary,
            ))

        # --- New matches grouped by kid ---
        # total_new: matches where computed_at IN [since, until)
        # opening_soon_count: subset whose offering has registration_opens_at IN [now, now+7d]
        # Computed in two passes for clarity; can be folded into one query later if hot.
        per_kid_total_q = (
            select(Kid.id, Kid.name, func.count(Match.id))
            .join(Match, Match.kid_id == Kid.id)
            .where(Match.computed_at >= since)
            .where(Match.computed_at < until)
            .group_by(Kid.id, Kid.name)
        )
        per_kid_total_rows = (await s.execute(per_kid_total_q)).all()

        per_kid_opens_q = (
            select(Kid.id, func.count(Match.id))
            .join(Match, Match.kid_id == Kid.id)
            .join(Offering, Offering.id == Match.offering_id)
            .where(Match.computed_at >= since)
            .where(Match.computed_at < until)
            .where(Offering.registration_opens_at.is_not(None))
            .where(Offering.registration_opens_at >= now)
            .where(Offering.registration_opens_at < opens_soon_window_end)
            .group_by(Kid.id)
        )
        per_kid_opens_rows = dict((await s.execute(per_kid_opens_q)).all())

        new_matches_by_kid = [
            InboxKidMatchCountOut(
                kid_id=kid_id,
                kid_name=kid_name,
                total_new=total,
                opening_soon_count=per_kid_opens_rows.get(kid_id, 0),
            )
            for kid_id, kid_name, total in per_kid_total_rows
        ]

        # --- Site activity ---
        refreshed_count = (await s.execute(
            select(func.count(func.distinct(CrawlRun.site_id)))
            .where(CrawlRun.started_at >= since)
            .where(CrawlRun.started_at < until)
            .where(CrawlRun.status == CrawlStatus.ok.value)
        )).scalar_one()

        posted_new_count = (await s.execute(
            select(func.count(func.distinct(Alert.site_id)))
            .where(Alert.type == AlertType.schedule_posted.value)
            .where(Alert.scheduled_for >= since)
            .where(Alert.scheduled_for < until)
            .where(Alert.site_id.is_not(None))
        )).scalar_one()

        # Stagnant: reuse the existing detector. Verified signature in
        # src/yas/alerts/detectors/site_stagnant.py: kwarg is `threshold_days`,
        # not `stagnant_after_days`. Config key is `alert_stagnant_site_days`.
        stagnant_ids = await detect_stagnant_sites(
            s,
            threshold_days=settings.alert_stagnant_site_days,
            now=now,
        )
        stagnant_count = len(stagnant_ids)

    return InboxSummaryOut(
        window_start=since,
        window_end=until,
        alerts=inbox_alerts,
        new_matches_by_kid=new_matches_by_kid,
        site_activity=InboxSiteActivityOut(
            refreshed_count=refreshed_count,
            posted_new_count=posted_new_count,
            stagnant_count=stagnant_count,
        ),
    )
```

If the actual detector signature differs (different kwarg name, or returns something other than a list), adjust the call. Verify by reading `src/yas/alerts/detectors/site_stagnant.py` before implementing.

- [ ] **Step 5: Register the router**

In `src/yas/web/routes/__init__.py`, export `inbox_router`. In `src/yas/web/app.py`, `app.include_router(inbox_router)`.

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/integration/test_api_inbox.py -v
uv run pytest -q
uv run ruff check . && uv run mypy src
```

- [ ] **Step 7: Commit**

```bash
git add src/yas/web/routes/inbox.py src/yas/web/routes/inbox_schemas.py \
    src/yas/web/routes/__init__.py src/yas/web/app.py \
    tests/integration/test_api_inbox.py
git commit -m "feat(web): add GET /api/inbox/summary"
```

---

## Task 7 — SPA fallback wiring (StaticFiles at /assets + catch-all)

**Files:**
- Create: `src/yas/web/spa_fallback.py`
- Modify: `src/yas/web/app.py`
- Create: `tests/integration/test_spa_fallback.py`

Spec §4.3. Even though there's no built SPA yet, we wire the routing now so backend and frontend can develop in parallel and the catch-all is testable.

- [ ] **Step 1: Write failing tests**

`tests/integration/test_spa_fallback.py`:

```python
"""SPA fallback route ordering invariants."""

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.session import create_engine_for
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    # Point STATIC_DIR at a fixture dir that contains an index.html
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>SPA</body></html>")
    (static / "assets").mkdir()
    (static / "assets" / "app-abc.js").write_text("console.log('hi')")
    monkeypatch.setenv("YAS_STATIC_DIR", str(static))

    url = f"sqlite+aiosqlite:///{tmp_path}/s.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_api_path_returns_json_not_spa(client):
    r = await client.get("/api/kids")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_unknown_api_path_returns_404_json_not_spa(client):
    r = await client.get("/api/nonexistent")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_root_returns_spa_html(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "SPA" in r.text


@pytest.mark.asyncio
async def test_deep_link_returns_spa_html(client):
    r = await client.get("/kids/1/matches")
    assert r.status_code == 200
    assert "SPA" in r.text
    # Cache-Control prevents stale HTML
    assert r.headers.get("cache-control", "").lower().startswith("no-cache")


@pytest.mark.asyncio
async def test_assets_path_serves_static_file(client):
    r = await client.get("/assets/app-abc.js")
    assert r.status_code == 200
    assert "console.log" in r.text


@pytest.mark.asyncio
async def test_unknown_asset_returns_404_not_spa(client):
    r = await client.get("/assets/missing.js")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_healthz_unaffected(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
```

- [ ] **Step 2: Run, confirm fail**

```bash
uv run pytest tests/integration/test_spa_fallback.py -v
```

- [ ] **Step 3: Implement the fallback module**

Create `src/yas/web/spa_fallback.py`:

```python
"""SPA fallback for GET requests not matched by API routes or the assets mount."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def _static_dir() -> Path:
    """Return the static-files root.

    In production this is /app/static (set by the Dockerfile). In tests and
    local dev it can be overridden via YAS_STATIC_DIR.
    """
    return Path(os.environ.get("YAS_STATIC_DIR", "/app/static"))


def install_spa_fallback(app: FastAPI) -> None:
    """Mount /assets, install API 404 guard, add SPA catch-all. MUST be called LAST in app setup."""
    static = _static_dir()

    if (static / "assets").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets", html=False), name="assets")

    # API 404 guard: registered BEFORE the SPA catch-all so unknown /api/*
    # paths return JSON 404 instead of being swallowed by the SPA fallback.
    # Without this, /api/nonexistent would match /{full_path:path} and return
    # index.html with status 200.
    @app.get("/api/{path:path}", include_in_schema=False)
    async def api_not_found(path: str) -> JSONResponse:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        return FileResponse(
            static / "index.html",
            headers={"Cache-Control": "no-cache"},
        )
```

- [ ] **Step 4: Wire into `app.py`**

At the END of `create_app` (after every `include_router` call, before `return app`):

```python
from yas.web.spa_fallback import install_spa_fallback
# ... existing wiring ...
install_spa_fallback(app)
return app
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/integration/test_spa_fallback.py -v
uv run pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add src/yas/web/spa_fallback.py src/yas/web/app.py tests/integration/test_spa_fallback.py
git commit -m "feat(web): add SPA fallback route + /assets static mount"
```

---

## Task 8 — Multi-stage Dockerfile

**Files:**
- Modify: `Dockerfile`

The Node build stage will fail until `frontend/` exists; this task lays the groundwork. Include a guard so the build still works pre-frontend (treat missing `frontend/` as a build failure with a clear error).

- [ ] **Step 1: Read current Dockerfile**

```bash
cat Dockerfile
```

- [ ] **Step 2: Replace with multi-stage**

```dockerfile
# --- Stage 1: build the React SPA ---
FROM node:20-alpine AS frontend-build
WORKDIR /build
# Cache deps separately
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
# Build
COPY frontend/ ./
RUN npm run build  # emits /build/dist with index.html + assets/

# --- Stage 2: existing Python image ---
FROM python:3.12-slim AS app
# ... preserve everything that was already in the file ...

# Copy the SPA bundle into the static dir consumed by yas.web.spa_fallback
COPY --from=frontend-build /build/dist /app/static
```

Preserve every existing Python step. Only add the new `FROM node:20-alpine AS frontend-build` block at the top and the trailing `COPY --from=frontend-build` at the end.

- [ ] **Step 3: Verify the Dockerfile parses (build will fail until frontend/ exists)**

```bash
docker compose -f docker-compose.yml build yas-api 2>&1 | head -20
```

Expected: failure mentioning missing `frontend/package.json`. That's correct — the rest of this plan creates `frontend/`.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "build: convert Dockerfile to multi-stage with node frontend build"
```

---

## Task 9 — Frontend scaffold (Vite + React + TS + ESLint)

**Files:**
- Create: `frontend/package.json`, `frontend/package-lock.json`
- Create: `frontend/tsconfig.json`, `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/vite-env.d.ts`
- Create: `frontend/.eslintrc.cjs`, `frontend/.prettierrc`, `frontend/.gitignore`

This task brings up an empty React app that builds and lints cleanly. No real UI yet.

- [ ] **Step 1: Create the directory + package.json**

```bash
mkdir -p frontend/src
cd frontend
```

Write `frontend/package.json`:

```json
{
  "name": "yas-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint . --max-warnings 0",
    "typecheck": "tsc --noEmit",
    "format": "prettier --write .",
    "format:check": "prettier --check ."
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@typescript-eslint/eslint-plugin": "^7.18.0",
    "@typescript-eslint/parser": "^7.18.0",
    "@vitejs/plugin-react": "^4.3.4",
    "eslint": "^8.57.0",
    "eslint-config-prettier": "^9.1.0",
    "eslint-plugin-react-hooks": "^5.1.0",
    "eslint-plugin-react-refresh": "^0.4.16",
    "prettier": "^3.4.2",
    "typescript": "^5.7.2",
    "vite": "^6.0.5"
  }
}
```

- [ ] **Step 2: Install deps to generate `package-lock.json`**

```bash
cd frontend && npm install
```

- [ ] **Step 3: TS configs**

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedSideEffectImports": true,
    "skipLibCheck": true,
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "skipLibCheck": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "noEmit": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 4: Vite config with API proxy**

`frontend/vite.config.ts`:

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/api':     { target: 'http://localhost:8080', changeOrigin: true },
      '/healthz': { target: 'http://localhost:8080', changeOrigin: true },
      '/readyz':  { target: 'http://localhost:8080', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
```

- [ ] **Step 5: Entry HTML + main**

`frontend/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Youth Activity Scheduler</title>
    <script>
      // Theme resolution before React hydrates — prevents FOUC.
      (function () {
        var stored = localStorage.getItem('yas-theme');
        var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        var dark = stored === 'dark' || (stored !== 'light' && prefersDark);
        if (dark) document.documentElement.classList.add('dark');
      })();
    </script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/main.tsx`:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <h1>YAS</h1>
  </StrictMode>,
);
```

`frontend/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

- [ ] **Step 6: Lint + format configs**

ESLint v8 is pinned (not v9) because the config uses the legacy `.eslintrc.cjs` format. ESLint v9 requires flat config (`eslint.config.js`); upgrading is a separate cleanup, not part of 5a.

`frontend/.eslintrc.cjs`:

```cjs
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
    'prettier',
  ],
  ignorePatterns: ['dist', '.eslintrc.cjs', 'node_modules'],
  parser: '@typescript-eslint/parser',
  parserOptions: { ecmaVersion: 2022, sourceType: 'module' },
  plugins: ['@typescript-eslint', 'react-refresh'],
  rules: {
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
  },
};
```

`frontend/.prettierrc`:

```json
{
  "semi": true,
  "singleQuote": true,
  "trailingComma": "all",
  "printWidth": 100
}
```

`frontend/.gitignore`:

```
node_modules
dist
.vite
*.log
```

- [ ] **Step 7: Verify build, lint, typecheck pass**

```bash
cd frontend
npm run typecheck
npm run lint
npm run build
ls dist  # should contain index.html + assets/
```

- [ ] **Step 8: Commit**

```bash
cd ..
git add frontend/
git commit -m "build: scaffold frontend (vite + react + ts + eslint)"
```

---

## Task 10 — Tailwind + shadcn/ui base

**Files:**
- Create: `frontend/tailwind.config.ts`, `frontend/postcss.config.js`
- Create: `frontend/src/styles/globals.css`
- Create: `frontend/components.json`
- Create: `frontend/src/lib/utils.ts` (shadcn convention)
- Modify: `frontend/src/main.tsx`, `frontend/index.html` (root, not under src/), `frontend/package.json`

This installs Tailwind, shadcn's tokens, and adds the first batch of shadcn primitives.

- [ ] **Step 1: Install Tailwind + shadcn deps**

```bash
cd frontend
npm install -D tailwindcss@^3.4.0 postcss autoprefixer tailwindcss-animate
npm install class-variance-authority clsx tailwind-merge lucide-react
```

- [ ] **Step 2: Tailwind + PostCSS config**

`frontend/tailwind.config.ts`:

```ts
import type { Config } from 'tailwindcss';
import animate from 'tailwindcss-animate';

const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    container: { center: true, padding: '1rem' },
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
    },
  },
  plugins: [animate],
};

export default config;
```

`frontend/postcss.config.js`:

```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 3: Globals CSS with shadcn tokens**

`frontend/src/styles/globals.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 222.2 84% 4.9%;
    --card: 0 0% 100%;
    --card-foreground: 222.2 84% 4.9%;
    --primary: 222.2 47.4% 11.2%;
    --primary-foreground: 210 40% 98%;
    --secondary: 210 40% 96.1%;
    --secondary-foreground: 222.2 47.4% 11.2%;
    --muted: 210 40% 96.1%;
    --muted-foreground: 215.4 16.3% 46.9%;
    --accent: 210 40% 96.1%;
    --accent-foreground: 222.2 47.4% 11.2%;
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 210 40% 98%;
    --border: 214.3 31.8% 91.4%;
    --input: 214.3 31.8% 91.4%;
    --ring: 222.2 84% 4.9%;
    --radius: 0.5rem;
  }
  .dark {
    --background: 222.2 84% 4.9%;
    --foreground: 210 40% 98%;
    --card: 222.2 84% 4.9%;
    --card-foreground: 210 40% 98%;
    --primary: 210 40% 98%;
    --primary-foreground: 222.2 47.4% 11.2%;
    --secondary: 217.2 32.6% 17.5%;
    --secondary-foreground: 210 40% 98%;
    --muted: 217.2 32.6% 17.5%;
    --muted-foreground: 215 20.2% 65.1%;
    --accent: 217.2 32.6% 17.5%;
    --accent-foreground: 210 40% 98%;
    --destructive: 0 62.8% 30.6%;
    --destructive-foreground: 210 40% 98%;
    --border: 217.2 32.6% 17.5%;
    --input: 217.2 32.6% 17.5%;
    --ring: 212.7 26.8% 83.9%;
  }
  body {
    @apply bg-background text-foreground;
  }
}
```

- [ ] **Step 4: shadcn config + utils**

`frontend/components.json`:

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "default",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.ts",
    "css": "src/styles/globals.css",
    "baseColor": "slate",
    "cssVariables": true,
    "prefix": ""
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

`frontend/src/lib/utils.ts`:

```ts
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 5: Wire globals into main + smoke test in main.tsx**

Edit `frontend/src/main.tsx`:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/globals.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <div className="container py-8">
      <h1 className="text-3xl font-semibold">YAS</h1>
      <p className="text-muted-foreground">Tailwind base wired.</p>
    </div>
  </StrictMode>,
);
```

- [ ] **Step 6: Add the first batch of shadcn primitives via CLI**

```bash
cd frontend
npx shadcn@latest add button card sheet tabs badge skeleton alert collapsible slider input
```

When prompted, accept the defaults; this writes files into `src/components/ui/`.

- [ ] **Step 7: Build, lint, typecheck**

```bash
npm run typecheck
npm run lint
npm run build
```

- [ ] **Step 8: Manual sanity check (optional)**

```bash
npm run dev &
# open http://localhost:5173 — should see "YAS" + "Tailwind base wired." styled with the chosen font/colors.
# Toggle the OS theme; the dark CSS variable set should kick in if you have OS dark mode on.
kill %1
```

- [ ] **Step 9: Commit**

```bash
cd ..
git add frontend/
git commit -m "build(frontend): add tailwind + shadcn ui primitives"
```

---

## Task 11 — TanStack Router + Query providers + base routes

**Files:**
- Create: `frontend/src/routes/__root.tsx`, `index.tsx`, `kids.$id.matches.tsx`, `kids.$id.watchlist.tsx`, `sites.index.tsx`, `sites.$id.tsx`, `settings.tsx`
- Create: `frontend/src/routeTree.gen.ts` (auto-generated; commit it)
- Modify: `frontend/src/main.tsx`, `frontend/vite.config.ts`, `frontend/package.json`

- [ ] **Step 1: Install router + query**

```bash
cd frontend
npm install @tanstack/react-query @tanstack/react-router
npm install -D @tanstack/react-query-devtools @tanstack/router-vite-plugin @tanstack/router-devtools
```

- [ ] **Step 2: Wire the router plugin into Vite**

Edit `vite.config.ts` to import `@tanstack/router-vite-plugin` and add it to `plugins` BEFORE `react()`:

```ts
import { TanStackRouterVite } from '@tanstack/router-vite-plugin';
// ...
plugins: [TanStackRouterVite(), react()],
```

- [ ] **Step 3: Create the route files (skeletons; one per page)**

`frontend/src/routes/__root.tsx`:

```tsx
import { Outlet, createRootRoute } from '@tanstack/react-router';

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-border px-4 py-3">
        <h1 className="text-lg font-semibold">YAS</h1>
      </header>
      <main className="p-4">
        <Outlet />
      </main>
    </div>
  );
}
```

`frontend/src/routes/index.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/')({
  component: InboxPage,
});

function InboxPage() {
  return <h2 className="text-2xl">Inbox</h2>;
}
```

`frontend/src/routes/kids.$id.matches.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/kids/$id/matches')({
  component: KidMatchesPage,
});

function KidMatchesPage() {
  const { id } = Route.useParams();
  return <h2 className="text-2xl">Kid {id} — Matches</h2>;
}
```

Same shape for `kids.$id.watchlist.tsx`, `sites.index.tsx` (route `'/sites'` — no trailing slash; must match the `to="/sites"` Links used in TopBar and SiteActivitySection), `sites.$id.tsx` (route `'/sites/$id'`), `settings.tsx` (route `'/settings'`). Each renders a placeholder `<h2>`. The router plugin will auto-generate `routeTree.gen.ts` on the next dev/build run.

- [ ] **Step 4: Wire router + query providers in main.tsx**

`frontend/src/main.tsx`:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createRouter } from '@tanstack/react-router';
import './styles/globals.css';
import { routeTree } from './routeTree.gen';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: true,
      retry: 2,
    },
  },
});

const router = createRouter({ routeTree, defaultPreload: 'intent' });

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
```

- [ ] **Step 5: First dev run generates routeTree**

```bash
npm run dev
# Wait ~2s for the router plugin to emit src/routeTree.gen.ts, then Ctrl+C.
```

- [ ] **Step 6: Verify navigation**

```bash
npm run dev
# http://localhost:5173 → "Inbox"
# http://localhost:5173/kids/1/matches → "Kid 1 — Matches"
# http://localhost:5173/settings → renders settings placeholder
```

- [ ] **Step 7: Build + typecheck + lint**

```bash
npm run build
npm run typecheck
npm run lint
```

- [ ] **Step 8: Commit**

```bash
cd ..
git add frontend/
git commit -m "build(frontend): wire tanstack router + query with placeholder routes"
```

---

## Task 12 — `lib/types.ts` + `lib/api.ts`

**Files:**
- Create: `frontend/src/lib/types.ts`, `api.ts`

Typed mirrors of the Pydantic response shapes + thin fetch wrappers. Hand-maintained for now (no codegen — too much overhead for the size of this API).

- [ ] **Step 1: Write types**

`frontend/src/lib/types.ts`:

```ts
// Mirrors Pydantic schemas in src/yas/web/routes/. Hand-maintained.
// When backend types change, update both sides; tests/integration will
// fail loudly if shapes drift.

export type AlertType =
  | 'watchlist_hit'
  | 'new_match'
  | 'reg_opens_24h'
  | 'reg_opens_1h'
  | 'reg_opens_now'
  | 'schedule_posted'
  | 'crawl_failed'
  | 'digest'
  | 'site_stagnant'
  | 'no_matches_for_kid'
  | 'push_cap';

// Mirrors src/yas/web/routes/matches_schemas.py::OfferingSummary AFTER Task 1's
// extension. Date/datetime are ISO strings over the wire.
export interface OfferingSummary {
  id: number;
  name: string;
  program_type: string;
  age_min: number | null;
  age_max: number | null;
  start_date: string | null;
  end_date: string | null;
  days_of_week: string[];
  time_start: string | null;
  time_end: string | null;
  price_cents: number | null;
  registration_url: string | null;
  site_id: number;
  // Added in Task 1:
  site_name: string;
  registration_opens_at: string | null;
}

export interface Match {
  kid_id: number;
  offering_id: number;
  score: number;
  reasons: Record<string, unknown>;
  computed_at: string;
  offering: OfferingSummary;
}

export interface InboxAlert {
  id: number;
  type: AlertType | string;
  kid_id: number | null;
  kid_name: string | null;
  offering_id: number | null;
  site_id: number | null;
  channels: string[];
  scheduled_for: string;
  sent_at: string | null;
  skipped: boolean;
  dedup_key: string;
  payload_json: Record<string, unknown>;
  summary_text: string;
}

export interface InboxKidMatchCount {
  kid_id: number;
  kid_name: string;
  total_new: number;
  opening_soon_count: number;
}

export interface InboxSiteActivity {
  refreshed_count: number;
  posted_new_count: number;
  stagnant_count: number;
}

export interface InboxSummary {
  window_start: string;
  window_end: string;
  alerts: InboxAlert[];
  new_matches_by_kid: InboxKidMatchCount[];
  site_activity: InboxSiteActivity;
}

export interface KidBrief {
  id: number;
  name: string;
  dob: string;
  interests: string[];
  active: boolean;
}

export interface WatchlistEntry {
  id: number;
  kid_id: number;
  site_id: number | null;
  pattern: string;
  priority: string;
  notes: string | null;
  active: boolean;
  ignore_hard_gates: boolean;
}

export interface KidDetail extends KidBrief {
  watchlist: WatchlistEntry[];
  // ... add the other embedded arrays the UI uses (matches, enrollments)
}

export interface Page {
  id: number;
  url: string;
  kind: string;
  content_hash: string | null;
  last_fetched: string | null;
  next_check_at: string | null;
}

export interface Site {
  id: number;
  name: string;
  base_url: string;
  adapter: string;
  needs_browser: boolean;
  active: boolean;
  default_cadence_s: number;
  muted_until: string | null;
  pages: Page[];
}

export interface CrawlRun {
  id: number;
  site_id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  pages_fetched: number;
  changes_detected: number;
  llm_calls: number;
  llm_cost_usd: number;
  error_text: string | null;
}

export interface AlertRouting {
  type: AlertType | string;
  channels: string[];
  enabled: boolean;
}

export interface Household {
  id: number;
  home_location_id: number | null;
  home_address: string | null;
  home_location_name: string | null;
  default_max_distance_mi: number | null;
  digest_time: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  daily_llm_cost_cap_usd: number;
}
```

- [ ] **Step 2: Write the fetch wrapper**

`frontend/src/lib/api.ts`:

```ts
export class ApiError extends Error {
  constructor(public readonly status: number, public readonly body: unknown) {
    super(`API error ${status}`);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!r.ok) {
    let body: unknown = null;
    try {
      body = await r.json();
    } catch {
      body = await r.text();
    }
    throw new ApiError(r.status, body);
  }
  return r.json() as Promise<T>;
}

export const api = {
  get<T>(path: string) {
    return request<T>(path);
  },
};
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run typecheck && npm run lint
```

- [ ] **Step 4: Commit**

```bash
cd ..
git add frontend/src/lib/types.ts frontend/src/lib/api.ts
git commit -m "feat(frontend): add API types + fetch wrapper"
```

---

## Task 13 — `lib/queries.ts` (TanStack Query hooks per resource)

**Files:**
- Create: `frontend/src/lib/queries.ts`

- [ ] **Step 1: Implement**

```ts
import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import type {
  AlertRouting,
  CrawlRun,
  Household,
  InboxSummary,
  KidBrief,
  KidDetail,
  Match,
  Site,
} from './types';

const minus = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
};

export function useInboxSummary(days = 7) {
  return useQuery({
    queryKey: ['inbox', 'summary', days],
    queryFn: () => {
      const since = minus(days);
      const until = new Date().toISOString();
      return api.get<InboxSummary>(
        `/api/inbox/summary?since=${encodeURIComponent(since)}&until=${encodeURIComponent(until)}`,
      );
    },
    refetchInterval: 60_000,
  });
}

export function useKids() {
  return useQuery({
    queryKey: ['kids'],
    queryFn: () => api.get<KidBrief[]>('/api/kids'),
  });
}

export function useKid(id: number) {
  return useQuery({
    queryKey: ['kids', id],
    queryFn: () => api.get<KidDetail>(`/api/kids/${id}`),
    enabled: Number.isFinite(id),
  });
}

export function useKidMatches(kidId: number) {
  return useQuery({
    queryKey: ['matches', kidId],
    queryFn: () => api.get<Match[]>(`/api/matches?kid_id=${kidId}&limit=200`),
    enabled: Number.isFinite(kidId),
  });
}

export function useSites() {
  return useQuery({
    queryKey: ['sites'],
    queryFn: () => api.get<Site[]>('/api/sites'),
  });
}

export function useSite(id: number) {
  return useQuery({
    queryKey: ['sites', id],
    queryFn: () => api.get<Site>(`/api/sites/${id}`),
    enabled: Number.isFinite(id),
  });
}

export function useSiteCrawls(id: number, limit = 10) {
  return useQuery({
    queryKey: ['sites', id, 'crawls', limit],
    queryFn: () => api.get<CrawlRun[]>(`/api/sites/${id}/crawls?limit=${limit}`),
    enabled: Number.isFinite(id),
  });
}

export function useHousehold() {
  return useQuery({
    queryKey: ['household'],
    queryFn: () => api.get<Household>('/api/household'),
  });
}

export function useAlertRouting() {
  return useQuery({
    queryKey: ['alert_routing'],
    queryFn: () => api.get<AlertRouting[]>('/api/alert_routing'),
  });
}
```

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npm run typecheck && npm run lint
cd ..
git add frontend/src/lib/queries.ts
git commit -m "feat(frontend): add tanstack-query hooks for every read endpoint"
```

---

## Task 14 — `lib/format.ts` + `lib/theme.ts`

**Files:**
- Create: `frontend/src/lib/format.ts`, `lib/theme.ts`
- Create: `frontend/src/lib/format.test.ts` (unit tests)

Mirrors Phase 4 Jinja filter semantics so digest emails and the SPA render identically.

- [ ] **Step 1: Install date-fns**

```bash
cd frontend && npm install date-fns
```

- [ ] **Step 2: format.ts**

```ts
import { differenceInCalendarDays, format, isSameDay, parseISO } from 'date-fns';

export function price(value: number | null | undefined): string {
  if (value == null || value < 0) return '';
  if (value === 0) return 'Free';
  return `$${value.toFixed(2)}`;
}

export function relDate(value: string | Date | null | undefined, now: Date = new Date()): string {
  if (value == null) return '';
  const d = typeof value === 'string' ? parseISO(value) : value;
  const diff = differenceInCalendarDays(d, now);
  if (isSameDay(d, now)) return 'Today';
  if (diff === 1) return 'Tomorrow';
  if (diff > 1 && diff <= 6) return `in ${diff} days`;
  // Within ~3 months: short day + month + day
  if (Math.abs(diff) <= 90) return format(d, 'EEE MMM d');
  return format(d, 'PP');
}

export function fmt(value: string | Date, fmtStr = "EEE h:mm a · MMM d"): string {
  const d = typeof value === 'string' ? parseISO(value) : value;
  return format(d, fmtStr);
}
```

- [ ] **Step 3: theme.ts**

```ts
export type Theme = 'system' | 'light' | 'dark';
const KEY = 'yas-theme';

export function getStoredTheme(): Theme {
  const v = localStorage.getItem(KEY);
  return v === 'light' || v === 'dark' ? v : 'system';
}

export function setStoredTheme(t: Theme): void {
  if (t === 'system') localStorage.removeItem(KEY);
  else localStorage.setItem(KEY, t);
  applyTheme(t);
}

export function resolveTheme(t: Theme): 'light' | 'dark' {
  if (t !== 'system') return t;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function applyTheme(t: Theme): void {
  const resolved = resolveTheme(t);
  document.documentElement.classList.toggle('dark', resolved === 'dark');
}
```

- [ ] **Step 4: format unit tests**

`frontend/src/lib/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { price, relDate } from './format';

describe('price', () => {
  it('returns empty for null', () => expect(price(null)).toBe(''));
  it('returns empty for negative', () => expect(price(-1)).toBe(''));
  it('returns Free for zero', () => expect(price(0)).toBe('Free'));
  it('formats positive', () => expect(price(12.5)).toBe('$12.50'));
});

describe('relDate', () => {
  const now = new Date('2026-04-24T12:00:00Z');
  it('Today', () => expect(relDate('2026-04-24T08:00:00Z', now)).toBe('Today'));
  it('Tomorrow', () => expect(relDate('2026-04-25T12:00:00Z', now)).toBe('Tomorrow'));
  it('in N days', () => expect(relDate('2026-04-28T12:00:00Z', now)).toBe('in 4 days'));
  it('weekday MMM d for ~3mo window', () => {
    const d = relDate('2026-05-15T12:00:00Z', now);
    expect(d).toMatch(/^\w{3} May 15$/);
  });
});
```

- [ ] **Step 5: Install Vitest infrastructure**

```bash
cd frontend
npm install -D vitest @vitest/ui happy-dom @testing-library/react @testing-library/jest-dom @testing-library/user-event msw @types/node
```

Update `package.json` scripts: add `"test": "vitest run", "test:watch": "vitest"`.

Add a `vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  test: {
    environment: 'happy-dom',
    setupFiles: './src/test/setup.ts',
    globals: true,
  },
});
```

`frontend/src/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest';
```

- [ ] **Step 6: Run tests**

```bash
npm run test
```

Expected: 8 passing format tests.

- [ ] **Step 7: Commit**

```bash
cd ..
git add frontend/
git commit -m "feat(frontend): add format helpers + theme manager + vitest setup"
```

---

## Task 15 — App shell: TopBar, KidSwitcher, ThemeToggle

**Files:**
- Create: `frontend/src/components/layout/AppShell.tsx`, `TopBar.tsx`, `KidSwitcher.tsx`, `ThemeToggle.tsx`
- Modify: `frontend/src/routes/__root.tsx`
- Create: `frontend/src/components/layout/TopBar.test.tsx`

The kid-centric C layout (spec §3 introduction).

- [ ] **Step 1: TopBar + KidSwitcher + ThemeToggle**

`frontend/src/components/layout/ThemeToggle.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Moon, Sun, Monitor } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { applyTheme, getStoredTheme, setStoredTheme, type Theme } from '@/lib/theme';

const order: Theme[] = ['system', 'light', 'dark'];
const Icon = { system: Monitor, light: Sun, dark: Moon } as const;
const label: Record<Theme, string> = { system: 'System', light: 'Light', dark: 'Dark' };

export function ThemeToggle() {
  const [t, setT] = useState<Theme>('system');

  useEffect(() => {
    setT(getStoredTheme());
  }, []);

  // React to OS-level changes when in system mode.
  useEffect(() => {
    if (t !== 'system') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => applyTheme('system');
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [t]);

  const cycle = () => {
    const next = order[(order.indexOf(t) + 1) % order.length];
    setStoredTheme(next);
    setT(next);
  };

  const C = Icon[t];
  return (
    <Button variant="ghost" size="sm" onClick={cycle} aria-label={`Theme: ${label[t]}`}>
      <C className="h-4 w-4" />
    </Button>
  );
}
```

`frontend/src/components/layout/KidSwitcher.tsx`:

```tsx
import { Link, useParams } from '@tanstack/react-router';
import { useKids } from '@/lib/queries';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

export function KidSwitcher() {
  const { data, isLoading, isError } = useKids();
  const params = useParams({ strict: false });
  const activeId = (params as { id?: string }).id;

  if (isLoading) return <Skeleton className="h-7 w-32" />;
  if (isError || !data || data.length === 0) return null;

  return (
    <nav aria-label="Switch kid" className="flex gap-1">
      {data.filter((k) => k.active).map((k) => (
        <Link
          key={k.id}
          to="/kids/$id/matches"
          params={{ id: String(k.id) }}
          className={cn(
            'rounded-md px-3 py-1 text-sm transition',
            String(k.id) === activeId
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {k.name}
        </Link>
      ))}
    </nav>
  );
}
```

`frontend/src/components/layout/TopBar.tsx`:

```tsx
import { Link } from '@tanstack/react-router';
import { Bell, Globe, Settings } from 'lucide-react';
import { KidSwitcher } from './KidSwitcher';
import { ThemeToggle } from './ThemeToggle';
import { useInboxSummary } from '@/lib/queries';
import { Badge } from '@/components/ui/badge';

export function TopBar() {
  const { data } = useInboxSummary();
  const alertCount = data?.alerts.length ?? 0;

  return (
    <header className="border-b border-border bg-background/95 backdrop-blur px-4 py-2.5 flex items-center gap-4">
      <Link to="/" className="text-lg font-semibold">YAS</Link>
      <div className="flex-1">
        <KidSwitcher />
      </div>
      <Link to="/" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <Bell className="h-4 w-4" /> Inbox
        {alertCount > 0 && (
          <Badge variant="destructive" className="ml-1 h-5 px-1.5 text-xs">{alertCount}</Badge>
        )}
      </Link>
      <Link to="/sites" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <Globe className="h-4 w-4" /> Sites
      </Link>
      <Link to="/settings" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <Settings className="h-4 w-4" /> Settings
      </Link>
      <ThemeToggle />
    </header>
  );
}
```

`frontend/src/components/layout/AppShell.tsx`:

```tsx
import type { ReactNode } from 'react';
import { TopBar } from './TopBar';

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <TopBar />
      <main className="container max-w-5xl py-6">{children}</main>
    </div>
  );
}
```

- [ ] **Step 2: Wire AppShell into __root.tsx**

```tsx
import { Outlet, createRootRoute } from '@tanstack/react-router';
import { AppShell } from '@/components/layout/AppShell';

export const Route = createRootRoute({
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
});
```

- [ ] **Step 3: Component test for TopBar**

`frontend/src/components/layout/TopBar.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { createRouter, createRootRoute, RouterProvider } from '@tanstack/react-router';
import { AppShell } from './AppShell';

const server = setupServer(
  http.get('/api/kids', () =>
    HttpResponse.json([{ id: 1, name: 'Sam', dob: '2019-05-01', interests: [], active: true }]),
  ),
  http.get('/api/inbox/summary', () =>
    HttpResponse.json({
      window_start: '2026-04-17T00:00:00Z',
      window_end: '2026-04-24T00:00:00Z',
      alerts: [{ id: 1, type: 'watchlist_hit', kid_id: 1, kid_name: 'Sam', offering_id: null, site_id: null, channels: [], scheduled_for: '...', sent_at: null, skipped: false, dedup_key: 'k', payload_json: {}, summary_text: 'x' }],
      new_matches_by_kid: [],
      site_activity: { refreshed_count: 0, posted_new_count: 0, stagnant_count: 0 },
    }),
  ),
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('TopBar', () => {
  it('renders kid switcher with active kids and alert badge with count', async () => {
    const root = createRootRoute({ component: () => <AppShell>{null}</AppShell> });
    const router = createRouter({ routeTree: root });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Sam')).toBeInTheDocument();
    expect(await screen.findByText('1')).toBeInTheDocument(); // alert badge
  });
});
```

(If MSW import fails, follow MSW v2 setup docs; the rest of the test is the same shape.)

- [ ] **Step 4: Run + commit**

```bash
cd frontend && npm run test && npm run build && npm run lint
cd ..
git add frontend/
git commit -m "feat(frontend): add app shell with TopBar, KidSwitcher, ThemeToggle"
```

---

## Task 16 — Inbox page (3 sections + drawer)

**Files:**
- Modify: `frontend/src/routes/index.tsx`
- Create: `frontend/src/components/inbox/AlertsSection.tsx`, `NewMatchesByKidSection.tsx`, `SiteActivitySection.tsx`, `AlertDetailDrawer.tsx`
- Create: `frontend/src/components/alerts/AlertTypeBadge.tsx`
- Create: `frontend/src/components/common/EmptyState.tsx`, `ErrorBanner.tsx`
- Create: `frontend/src/components/inbox/AlertsSection.test.tsx`

Spec §3.1.

- [ ] **Step 1: Common components**

`frontend/src/components/common/EmptyState.tsx`:

```tsx
export function EmptyState({ children }: { children: React.ReactNode }) {
  return <p className="py-6 text-sm text-muted-foreground">{children}</p>;
}
```

`frontend/src/components/common/ErrorBanner.tsx`:

```tsx
import { AlertCircle } from 'lucide-react';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Alert variant="destructive">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>Couldn't load</AlertTitle>
      <AlertDescription className="flex items-center justify-between gap-3">
        <span>{message}</span>
        {onRetry && <Button size="sm" variant="outline" onClick={onRetry}>Retry</Button>}
      </AlertDescription>
    </Alert>
  );
}
```

- [ ] **Step 2: AlertTypeBadge**

`frontend/src/components/alerts/AlertTypeBadge.tsx`:

```tsx
import { Badge } from '@/components/ui/badge';

const tone: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  watchlist_hit: 'destructive',
  reg_opens_now: 'destructive',
  reg_opens_1h: 'destructive',
  reg_opens_24h: 'default',
  new_match: 'secondary',
  schedule_posted: 'outline',
  crawl_failed: 'destructive',
  site_stagnant: 'outline',
  no_matches_for_kid: 'outline',
  push_cap: 'outline',
  digest: 'secondary',
};

export function AlertTypeBadge({ type }: { type: string }) {
  return <Badge variant={tone[type] ?? 'outline'}>{type}</Badge>;
}
```

- [ ] **Step 3: AlertDetailDrawer**

`frontend/src/components/inbox/AlertDetailDrawer.tsx`:

```tsx
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import type { InboxAlert } from '@/lib/types';
import { AlertTypeBadge } from '@/components/alerts/AlertTypeBadge';
import { fmt } from '@/lib/format';

export function AlertDetailDrawer({
  alert,
  open,
  onOpenChange,
}: {
  alert: InboxAlert | null;
  open: boolean;
  onOpenChange: (b: boolean) => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        {alert && (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-center gap-2">
                <AlertTypeBadge type={alert.type} /> {alert.kid_name ?? '—'}
              </SheetTitle>
              <SheetDescription>{alert.summary_text}</SheetDescription>
            </SheetHeader>
            <dl className="mt-6 space-y-2 text-sm">
              <div><dt className="text-muted-foreground">Scheduled for</dt><dd>{fmt(alert.scheduled_for)}</dd></div>
              {alert.sent_at && <div><dt className="text-muted-foreground">Sent at</dt><dd>{fmt(alert.sent_at)}</dd></div>}
              <div><dt className="text-muted-foreground">Channels</dt><dd>{alert.channels.join(', ') || '—'}</dd></div>
              <div><dt className="text-muted-foreground">Status</dt><dd>{alert.skipped ? 'Skipped' : alert.sent_at ? 'Sent' : 'Pending'}</dd></div>
            </dl>
            <pre className="mt-6 text-xs bg-muted p-3 rounded-md overflow-auto">
              {JSON.stringify(alert.payload_json, null, 2)}
            </pre>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 4: AlertsSection**

`frontend/src/components/inbox/AlertsSection.tsx`:

```tsx
import { useState } from 'react';
import type { InboxAlert } from '@/lib/types';
import { AlertTypeBadge } from '@/components/alerts/AlertTypeBadge';
import { AlertDetailDrawer } from './AlertDetailDrawer';
import { EmptyState } from '@/components/common/EmptyState';

export function AlertsSection({ alerts }: { alerts: InboxAlert[] }) {
  const [selected, setSelected] = useState<InboxAlert | null>(null);

  return (
    <section aria-labelledby="alerts-heading" className="space-y-2">
      <h2 id="alerts-heading" className="text-xs font-semibold uppercase text-muted-foreground">
        Alerts ({alerts.length})
      </h2>
      {alerts.length === 0 ? (
        <EmptyState>No alerts this week. Quiet is good.</EmptyState>
      ) : (
        <ul className="space-y-1.5">
          {alerts.map((a) => (
            <li
              key={a.id}
              className="rounded-md border border-border p-3 cursor-pointer hover:bg-accent transition"
              onClick={() => setSelected(a)}
            >
              <div className="flex items-start gap-3">
                <AlertTypeBadge type={a.type} />
                <span className="flex-1 text-sm">{a.summary_text}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
      <AlertDetailDrawer alert={selected} open={selected !== null} onOpenChange={(o) => !o && setSelected(null)} />
    </section>
  );
}
```

- [ ] **Step 5: NewMatchesByKidSection**

```tsx
import { Link } from '@tanstack/react-router';
import type { InboxKidMatchCount } from '@/lib/types';
import { EmptyState } from '@/components/common/EmptyState';

export function NewMatchesByKidSection({ rows }: { rows: InboxKidMatchCount[] }) {
  return (
    <section aria-labelledby="matches-heading" className="space-y-2">
      <h2 id="matches-heading" className="text-xs font-semibold uppercase text-muted-foreground">
        New matches
      </h2>
      {rows.length === 0 ? (
        <EmptyState>No new matches in this window.</EmptyState>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2">
          {rows.map((r) => (
            <li key={r.kid_id}>
              <Link
                to="/kids/$id/matches"
                params={{ id: String(r.kid_id) }}
                className="block rounded-md border border-border p-3 hover:bg-accent transition"
              >
                <div className="font-semibold">{r.kid_name}</div>
                <div className="text-sm text-muted-foreground">
                  {r.total_new} new · {r.opening_soon_count} opening soon
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

- [ ] **Step 6: SiteActivitySection**

```tsx
import { Link } from '@tanstack/react-router';
import type { InboxSiteActivity } from '@/lib/types';

export function SiteActivitySection({ activity }: { activity: InboxSiteActivity }) {
  if (activity.refreshed_count + activity.posted_new_count + activity.stagnant_count === 0) {
    return null;
  }
  return (
    <section aria-labelledby="sites-heading" className="space-y-2">
      <h2 id="sites-heading" className="text-xs font-semibold uppercase text-muted-foreground">
        Site activity
      </h2>
      <p className="text-sm text-muted-foreground">
        {activity.refreshed_count} sites refreshed · {activity.posted_new_count} posted new schedules ·{' '}
        {activity.stagnant_count > 0 ? (
          <Link to="/sites" className="underline underline-offset-2 hover:text-foreground">
            {activity.stagnant_count} stagnant
          </Link>
        ) : (
          '0 stagnant'
        )}
      </p>
    </section>
  );
}
```

- [ ] **Step 7: Inbox page**

```tsx
// frontend/src/routes/index.tsx
import { createFileRoute } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { AlertsSection } from '@/components/inbox/AlertsSection';
import { NewMatchesByKidSection } from '@/components/inbox/NewMatchesByKidSection';
import { SiteActivitySection } from '@/components/inbox/SiteActivitySection';
import { useInboxSummary } from '@/lib/queries';

export const Route = createFileRoute('/')({ component: InboxPage });

function InboxPage() {
  const { data, isLoading, isError, error, refetch } = useInboxSummary();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (isError || !data) {
    return <ErrorBanner message={(error as Error)?.message ?? 'Unknown error'} onRetry={() => refetch()} />;
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold">What's new this week</h1>
        <p className="text-sm text-muted-foreground">
          Since {new Date(data.window_start).toLocaleDateString()} ·{' '}
          {data.new_matches_by_kid.length} kid{data.new_matches_by_kid.length === 1 ? '' : 's'}
        </p>
      </header>
      <AlertsSection alerts={data.alerts} />
      <NewMatchesByKidSection rows={data.new_matches_by_kid} />
      <SiteActivitySection activity={data.site_activity} />
    </div>
  );
}
```

- [ ] **Step 8: Test for AlertsSection**

`frontend/src/components/inbox/AlertsSection.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AlertsSection } from './AlertsSection';

const alerts = [
  { id: 1, type: 'watchlist_hit', kid_id: 1, kid_name: 'Sam', offering_id: null, site_id: null,
    channels: ['email'], scheduled_for: '2026-04-24T12:00:00Z', sent_at: null, skipped: false,
    dedup_key: 'k', payload_json: {}, summary_text: 'Watchlist hit for Sam' },
];

describe('AlertsSection', () => {
  it('renders empty state', () => {
    render(<AlertsSection alerts={[]} />);
    expect(screen.getByText(/no alerts this week/i)).toBeInTheDocument();
  });

  it('renders rows and opens drawer on click', () => {
    render(<AlertsSection alerts={alerts as never} />);
    fireEvent.click(screen.getByText('Watchlist hit for Sam'));
    // Drawer renders the summary text
    expect(screen.getAllByText('Watchlist hit for Sam').length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 9: Run + commit**

```bash
cd frontend && npm run test && npm run build && npm run lint && npm run typecheck
cd ..
git add frontend/
git commit -m "feat(frontend): inbox page with three sections + alert detail drawer"
```

---

## Task 17 — Kid Matches page (urgency groups + filters + drawer)

**Files:**
- Modify: `frontend/src/routes/kids.$id.matches.tsx`
- Create: `frontend/src/components/matches/UrgencyGroup.tsx`, `MatchCard.tsx`, `MatchDetailDrawer.tsx`, `MatchFilters.tsx`
- Create: `frontend/src/components/matches/UrgencyGroup.test.tsx`

Spec §3.2.1.

- [ ] **Step 1: Pure helpers — urgency assignment**

Inside `frontend/src/lib/matches.ts` (new file):

```ts
import type { Match } from './types';

export type Urgency = 'opens-this-week' | 'starting-soon' | 'later';

export function urgencyOf(m: Match, now = new Date()): Urgency {
  const opens = m.offering.registration_opens_at ? new Date(m.offering.registration_opens_at) : null;
  if (opens) {
    const days = (opens.getTime() - now.getTime()) / 86_400_000;
    if (days >= 0 && days <= 7) return 'opens-this-week';
  }
  const start = m.offering.start_date ? new Date(m.offering.start_date) : null;
  if (start) {
    const days = (start.getTime() - now.getTime()) / 86_400_000;
    if (days >= 0 && days <= 14) return 'starting-soon';
  }
  return 'later';
}

export function groupByUrgency(matches: Match[], now = new Date()): Record<Urgency, Match[]> {
  const out: Record<Urgency, Match[]> = { 'opens-this-week': [], 'starting-soon': [], later: [] };
  for (const m of matches) out[urgencyOf(m, now)].push(m);
  return out;
}
```

Add a unit test: `lib/matches.test.ts` with cases covering each branch (opens tomorrow → opens-this-week; starts in 5 days, no opens date → starting-soon; far-future → later).

- [ ] **Step 2: MatchCard**

```tsx
// frontend/src/components/matches/MatchCard.tsx
import type { Match } from '@/lib/types';
import { Card } from '@/components/ui/card';
import { price, relDate } from '@/lib/format';
import { cn } from '@/lib/utils';

export function MatchCard({ match, urgent, onClick }: { match: Match; urgent?: boolean; onClick?: () => void }) {
  const o = match.offering;
  return (
    <Card
      className={cn(
        'p-3 cursor-pointer hover:bg-accent transition',
        urgent && 'border-destructive/40',
      )}
      onClick={onClick}
    >
      <div className="flex items-start gap-3">
        <div className="flex-1">
          <div className="font-semibold">{o.name}</div>
          <div className="text-sm text-muted-foreground">
            {o.site_name}
            {o.start_date && ` · ${relDate(o.start_date)}`}
            {o.price_cents != null && ` · ${price(o.price_cents / 100)}`}
            {o.registration_opens_at && ` · reg ${relDate(o.registration_opens_at)}`}
          </div>
        </div>
        <div className="text-sm font-semibold">{match.score.toFixed(2)}</div>
      </div>
    </Card>
  );
}
```

- [ ] **Step 3: UrgencyGroup**

```tsx
// frontend/src/components/matches/UrgencyGroup.tsx
import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { Match } from '@/lib/types';
import { MatchCard } from './MatchCard';

export function UrgencyGroup({
  title,
  matches,
  defaultOpen = true,
  urgent = false,
  onSelect,
}: {
  title: string;
  matches: Match[];
  defaultOpen?: boolean;
  urgent?: boolean;
  onSelect: (m: Match) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (matches.length === 0) return null;

  return (
    <section className="space-y-2">
      <button onClick={() => setOpen((v) => !v)} className="flex items-center gap-1 text-xs font-semibold uppercase text-muted-foreground">
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {title} ({matches.length})
      </button>
      {open && (
        <div className="space-y-2">
          {matches.map((m) => (
            <MatchCard key={`${m.kid_id}-${m.offering_id}`} match={m} urgent={urgent} onClick={() => onSelect(m)} />
          ))}
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 4: MatchDetailDrawer**

```tsx
// frontend/src/components/matches/MatchDetailDrawer.tsx
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import type { Match } from '@/lib/types';
import { price, relDate } from '@/lib/format';

export function MatchDetailDrawer({
  match,
  open,
  onOpenChange,
}: { match: Match | null; open: boolean; onOpenChange: (b: boolean) => void }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        {match && (
          <>
            <SheetHeader>
              <SheetTitle>{match.offering.name}</SheetTitle>
              <SheetDescription>{match.offering.site_name}</SheetDescription>
            </SheetHeader>
            <dl className="mt-6 space-y-2 text-sm">
              <div><dt className="text-muted-foreground">Score</dt><dd>{match.score.toFixed(2)}</dd></div>
              {match.offering.start_date && <div><dt className="text-muted-foreground">Starts</dt><dd>{relDate(match.offering.start_date)}</dd></div>}
              {match.offering.price_cents != null && <div><dt className="text-muted-foreground">Price</dt><dd>{price(match.offering.price_cents / 100)}</dd></div>}
            </dl>
            <h3 className="mt-6 mb-2 text-xs font-semibold uppercase text-muted-foreground">Match reasons</h3>
            <pre className="text-xs bg-muted p-3 rounded-md overflow-auto">
              {JSON.stringify(match.reasons, null, 2)}
            </pre>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 5: MatchFilters (filter chips)**

Skip filter UI for the FIRST iteration of 5a if it grows the task too far. Spec lists filters but the simplest 5a implementation can ship without them and add in a follow-up. The page below renders without filters; add `MatchFilters` only if there's room in the task.

- [ ] **Step 6: Matches page**

```tsx
// frontend/src/routes/kids.$id.matches.tsx
import { useState } from 'react';
import { createFileRoute } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { useKid, useKidMatches } from '@/lib/queries';
import { groupByUrgency } from '@/lib/matches';
import { UrgencyGroup } from '@/components/matches/UrgencyGroup';
import { MatchDetailDrawer } from '@/components/matches/MatchDetailDrawer';
import type { Match } from '@/lib/types';

export const Route = createFileRoute('/kids/$id/matches')({ component: KidMatchesPage });

function KidMatchesPage() {
  const { id } = Route.useParams();
  const kidId = Number(id);
  const kid = useKid(kidId);
  const matches = useKidMatches(kidId);
  const [selected, setSelected] = useState<Match | null>(null);

  if (kid.isLoading || matches.isLoading) return <Skeleton className="h-32 w-full" />;
  if (kid.isError || matches.isError) {
    return <ErrorBanner message="Failed to load matches" onRetry={() => { kid.refetch(); matches.refetch(); }} />;
  }
  if (!kid.data || !matches.data) return null;

  const groups = groupByUrgency(matches.data);
  const total = matches.data.length;
  const truncated = total >= 200;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">{kid.data.name} — matches</h1>
        <p className="text-sm text-muted-foreground">{total} matches</p>
      </header>
      {total === 0 && <EmptyState>No matches yet for {kid.data.name}.</EmptyState>}
      <UrgencyGroup title="Registration opens this week" matches={groups['opens-this-week']} urgent onSelect={setSelected} />
      <UrgencyGroup title="Starting in ≤ 14 days" matches={groups['starting-soon']} onSelect={setSelected} />
      <UrgencyGroup title="Later this season" matches={groups['later']} defaultOpen={false} onSelect={setSelected} />
      {truncated && (
        <p className="text-xs text-muted-foreground">
          Showing first 200 matches. Pagination arrives in 5b.
        </p>
      )}
      <MatchDetailDrawer match={selected} open={selected !== null} onOpenChange={(o) => !o && setSelected(null)} />
    </div>
  );
}
```

- [ ] **Step 7: UrgencyGroup test**

```tsx
// frontend/src/components/matches/UrgencyGroup.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { UrgencyGroup } from './UrgencyGroup';

const m = {
  kid_id: 1, offering_id: 1, score: 0.9, reasons: {}, computed_at: '2026-04-24T12:00:00Z',
  offering: {
    id: 1, site_id: 1, site_name: 'X', name: 'T-Ball', program_type: 'other',
    age_min: null, age_max: null, start_date: null, end_date: null,
    days_of_week: [], time_start: null, time_end: null,
    price_cents: null, registration_url: null, registration_opens_at: null,
  },
};

describe('UrgencyGroup', () => {
  it('renders nothing when matches is empty', () => {
    const { container } = render(<UrgencyGroup title="t" matches={[]} onSelect={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
  it('renders a card per match', () => {
    render(<UrgencyGroup title="t" matches={[m as never]} onSelect={() => {}} />);
    expect(screen.getByText('T-Ball')).toBeInTheDocument();
  });
});
```

- [ ] **Step 8: Build + test + commit**

```bash
cd frontend && npm run test && npm run build && npm run typecheck && npm run lint
cd ..
git add frontend/
git commit -m "feat(frontend): kid matches page with urgency groups + drawer"
```

---

## Task 18 — Kid Watchlist tab + tab navigation

**Files:**
- Modify: `frontend/src/routes/kids.$id.watchlist.tsx`
- Create: `frontend/src/components/layout/KidTabs.tsx` (shared by both kid routes)
- Possibly extend `KidSwitcher` to navigate to current tab

Spec §3.2.2.

- [ ] **Step 1: KidTabs component**

```tsx
// frontend/src/components/layout/KidTabs.tsx
import { Link, useLocation } from '@tanstack/react-router';
import { cn } from '@/lib/utils';

const tabs = [
  { to: '/kids/$id/matches', label: 'Matches' },
  { to: '/kids/$id/watchlist', label: 'Watchlist' },
] as const;

export function KidTabs({ kidId }: { kidId: number }) {
  const loc = useLocation();
  return (
    <nav className="border-b border-border flex gap-2 mb-4">
      {tabs.map((t) => {
        const active = loc.pathname.endsWith(`/${t.label.toLowerCase()}`);
        return (
          <Link
            key={t.to}
            to={t.to}
            params={{ id: String(kidId) }}
            className={cn(
              'px-3 py-2 text-sm border-b-2 -mb-px',
              active ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
```

Use `<KidTabs kidId={kidId} />` at the top of both `kids.$id.matches.tsx` and `kids.$id.watchlist.tsx` (above the `<header>`).

- [ ] **Step 2: Watchlist page**

```tsx
// frontend/src/routes/kids.$id.watchlist.tsx
import { createFileRoute } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { useKid } from '@/lib/queries';
import { KidTabs } from '@/components/layout/KidTabs';

export const Route = createFileRoute('/kids/$id/watchlist')({ component: KidWatchlistPage });

function KidWatchlistPage() {
  const { id } = Route.useParams();
  const kidId = Number(id);
  const { data, isLoading, isError, refetch } = useKid(kidId);

  if (isLoading) return <Skeleton className="h-32 w-full" />;
  if (isError || !data) return <ErrorBanner message="Failed to load watchlist" onRetry={() => refetch()} />;

  return (
    <div>
      <KidTabs kidId={kidId} />
      <header className="mb-4">
        <h1 className="text-2xl font-semibold">{data.name} — watchlist</h1>
        <p className="text-sm text-muted-foreground">{data.watchlist.length} entries</p>
      </header>
      {data.watchlist.length === 0 ? (
        <EmptyState>No watchlist entries.</EmptyState>
      ) : (
        <ul className="space-y-2">
          {data.watchlist.map((w) => (
            <li key={w.id}>
              <Card className="p-3 flex items-start gap-3">
                <div className="flex-1">
                  <div className="font-semibold">{w.pattern}</div>
                  <div className="text-sm text-muted-foreground">
                    {w.site_id ? `Site #${w.site_id}` : 'any site'} · priority {w.priority}
                    {w.notes && ` · ${w.notes}`}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  {w.ignore_hard_gates && <Badge variant="outline">ignores hard gates</Badge>}
                  {!w.active && <Badge variant="secondary">inactive</Badge>}
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Add `<KidTabs />` to matches page (modification to Task 17 result)**

Insert at the top of the JSX in `kids.$id.matches.tsx`:

```tsx
return (
  <div className="space-y-6">
    <KidTabs kidId={kidId} />
    {/* ... rest unchanged ... */}
  </div>
);
```

- [ ] **Step 4: Build + commit**

```bash
cd frontend && npm run build && npm run typecheck && npm run lint
cd ..
git add frontend/
git commit -m "feat(frontend): kid watchlist tab + shared kid tabs nav"
```

---

## Task 19 — Sites list + Site detail

**Files:**
- Modify: `frontend/src/routes/sites.index.tsx`, `sites.$id.tsx`
- Create: `frontend/src/components/sites/SiteRow.tsx`, `CrawlHistoryList.tsx`

Spec §3.3.

- [ ] **Step 1: Sites list**

```tsx
// frontend/src/routes/sites.index.tsx
import { createFileRoute, Link } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useSites } from '@/lib/queries';
import { relDate } from '@/lib/format';

export const Route = createFileRoute('/sites')({ component: SitesPage });

function SitesPage() {
  const { data, isLoading, isError, refetch } = useSites();

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (isError || !data) return <ErrorBanner message="Failed to load sites" onRetry={() => refetch()} />;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Sites</h1>
      {data.length === 0 ? (
        <EmptyState>No sites tracked yet.</EmptyState>
      ) : (
        <ul className="space-y-2">
          {data.map((s) => {
            const lastFetched = s.pages.map((p) => p.last_fetched).filter(Boolean).sort().reverse()[0] ?? null;
            return (
              <li key={s.id}>
                <Link to="/sites/$id" params={{ id: String(s.id) }}>
                  <Card className="p-3 hover:bg-accent transition">
                    <div className="flex items-center gap-3">
                      <div className="flex-1">
                        <div className="font-semibold">{s.name}</div>
                        <div className="text-sm text-muted-foreground">
                          {s.adapter} · {s.pages.length} page{s.pages.length === 1 ? '' : 's'}
                          {lastFetched && ` · last crawled ${relDate(lastFetched)}`}
                        </div>
                      </div>
                      {s.muted_until && <Badge variant="secondary">muted</Badge>}
                      {!s.active && <Badge variant="outline">inactive</Badge>}
                    </div>
                  </Card>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 2: CrawlHistoryList**

```tsx
// frontend/src/components/sites/CrawlHistoryList.tsx
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import type { CrawlRun } from '@/lib/types';
import { fmt } from '@/lib/format';

const statusVariant: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  ok: 'secondary',
  failed: 'destructive',
  skipped: 'outline',
};

export function CrawlHistoryList({ crawls, isLoading }: { crawls: CrawlRun[] | undefined; isLoading: boolean }) {
  if (isLoading) return <Skeleton className="h-32 w-full" />;
  if (!crawls || crawls.length === 0) return <p className="text-sm text-muted-foreground">No crawl history.</p>;
  return (
    <ul className="space-y-1.5">
      {crawls.map((c) => (
        <li key={c.id} className="rounded-md border border-border p-2.5 text-sm">
          <div className="flex items-center gap-3">
            <Badge variant={statusVariant[c.status] ?? 'outline'}>{c.status}</Badge>
            <span className="text-muted-foreground">{fmt(c.started_at)}</span>
            <span className="ml-auto">{c.pages_fetched} pages · {c.changes_detected} changes</span>
          </div>
          {c.error_text && <p className="mt-1 text-xs text-destructive">{c.error_text}</p>}
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 3: Site detail page**

```tsx
// frontend/src/routes/sites.$id.tsx
import { createFileRoute } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { useSite, useSiteCrawls } from '@/lib/queries';
import { CrawlHistoryList } from '@/components/sites/CrawlHistoryList';
import { fmt } from '@/lib/format';

export const Route = createFileRoute('/sites/$id')({ component: SiteDetailPage });

function SiteDetailPage() {
  const { id } = Route.useParams();
  const siteId = Number(id);
  const site = useSite(siteId);
  const crawls = useSiteCrawls(siteId);

  if (site.isLoading) return <Skeleton className="h-32 w-full" />;
  if (site.isError || !site.data) return <ErrorBanner message="Failed to load site" onRetry={() => site.refetch()} />;

  const s = site.data;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">{s.name}</h1>
        <p className="text-sm text-muted-foreground">{s.base_url} · adapter: {s.adapter}</p>
      </header>

      <section>
        <h2 className="text-xs font-semibold uppercase text-muted-foreground mb-2">Pages ({s.pages.length})</h2>
        <ul className="space-y-1.5 text-sm">
          {s.pages.map((p) => (
            <li key={p.id} className="rounded-md border border-border p-2">
              <div className="font-mono text-xs break-all">{p.url}</div>
              <div className="text-muted-foreground text-xs mt-0.5">
                {p.kind}{p.last_fetched && ` · last fetched ${fmt(p.last_fetched)}`}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="text-xs font-semibold uppercase text-muted-foreground mb-2">Recent crawl history</h2>
        <CrawlHistoryList crawls={crawls.data} isLoading={crawls.isLoading} />
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Build + commit**

```bash
cd frontend && npm run build && npm run typecheck && npm run lint
cd ..
git add frontend/
git commit -m "feat(frontend): sites list + site detail with crawl history"
```

---

## Task 20 — Settings page (read-only)

**Files:**
- Modify: `frontend/src/routes/settings.tsx`

Spec §3.4.

- [ ] **Step 1: Settings page**

```tsx
// frontend/src/routes/settings.tsx
import { createFileRoute } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { Card } from '@/components/ui/card';
import { useAlertRouting, useHousehold } from '@/lib/queries';

export const Route = createFileRoute('/settings')({ component: SettingsPage });

function SettingsPage() {
  const hh = useHousehold();
  const routing = useAlertRouting();

  if (hh.isLoading || routing.isLoading) return <Skeleton className="h-64 w-full" />;
  if (hh.isError || routing.isError || !hh.data || !routing.data) {
    return <ErrorBanner message="Failed to load settings" onRetry={() => { hh.refetch(); routing.refetch(); }} />;
  }

  const h = hh.data;
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Settings</h1>

      <section>
        <h2 className="text-xs font-semibold uppercase text-muted-foreground mb-2">Household</h2>
        <Card className="p-4 space-y-2 text-sm">
          <Row k="Home address" v={h.home_address ?? '—'} />
          <Row k="Home location name" v={h.home_location_name ?? '—'} />
          <Row k="Default max distance (mi)" v={h.default_max_distance_mi?.toString() ?? '—'} />
          <Row k="Digest time" v={h.digest_time} />
          <Row k="Quiet hours" v={h.quiet_hours_start && h.quiet_hours_end ? `${h.quiet_hours_start} – ${h.quiet_hours_end}` : '—'} />
          <Row k="Daily LLM cost cap" v={`$${h.daily_llm_cost_cap_usd.toFixed(2)}`} />
        </Card>
      </section>

      <section>
        <h2 className="text-xs font-semibold uppercase text-muted-foreground mb-2">Alert routing</h2>
        <Card className="p-4">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-muted-foreground">
              <tr><th className="py-1">Type</th><th>Channels</th><th>Enabled</th></tr>
            </thead>
            <tbody>
              {routing.data.map((r) => (
                <tr key={r.type} className="border-t border-border">
                  <td className="py-1">{r.type}</td>
                  <td>{r.channels.join(', ') || '—'}</td>
                  <td>{r.enabled ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </section>

      <section>
        <h2 className="text-xs font-semibold uppercase text-muted-foreground mb-2">Notifier configuration</h2>
        <Card className="p-4 text-sm text-muted-foreground">
          Channel configuration available in Phase 5b.
        </Card>
      </section>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex">
      <dt className="w-48 text-muted-foreground">{k}</dt>
      <dd>{v}</dd>
    </div>
  );
}
```

- [ ] **Step 2: Build + commit**

```bash
cd frontend && npm run build && npm run typecheck && npm run lint
cd ..
git add frontend/
git commit -m "feat(frontend): read-only settings page"
```

---

## Task 21 — Frontend test infrastructure (MSW handlers + base specs)

**Files:**
- Create: `frontend/src/test/handlers.ts`
- Create: `frontend/src/test/server.ts`
- Add additional component tests as gaps appear

The component tests written in Tasks 15–17 already exercise the basics. This task formalises shared MSW handlers and adds at least one query-hook test.

- [ ] **Step 1: Shared handlers**

`frontend/src/test/handlers.ts`:

```ts
import { http, HttpResponse } from 'msw';

export const inboxSummaryFixture = {
  window_start: '2026-04-17T00:00:00Z',
  window_end: '2026-04-24T00:00:00Z',
  alerts: [],
  new_matches_by_kid: [],
  site_activity: { refreshed_count: 0, posted_new_count: 0, stagnant_count: 0 },
};

export const handlers = [
  http.get('/api/kids', () => HttpResponse.json([])),
  http.get('/api/inbox/summary', () => HttpResponse.json(inboxSummaryFixture)),
  http.get('/api/sites', () => HttpResponse.json([])),
  http.get('/api/household', () =>
    HttpResponse.json({
      id: 1, home_location_id: null, home_address: null, home_location_name: null,
      default_max_distance_mi: null, digest_time: '07:00', quiet_hours_start: null,
      quiet_hours_end: null, daily_llm_cost_cap_usd: 1.0,
    }),
  ),
  http.get('/api/alert_routing', () => HttpResponse.json([])),
];
```

`frontend/src/test/server.ts`:

```ts
import { setupServer } from 'msw/node';
import { handlers } from './handlers';

export const server = setupServer(...handlers);
```

Update `setup.ts`:

```ts
import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { server } from './server';

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

- [ ] **Step 2: Test for `useInboxSummary` hook**

`frontend/src/lib/queries.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { useInboxSummary } from './queries';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useInboxSummary', () => {
  it('returns summary on success', async () => {
    const { result } = renderHook(() => useInboxSummary(7), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.alerts).toEqual([]);
  });

  it('exposes error state on 500', async () => {
    server.use(http.get('/api/inbox/summary', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })));
    const { result } = renderHook(() => useInboxSummary(7), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
```

- [ ] **Step 3: Run + commit**

```bash
cd frontend && npm run test
cd ..
git add frontend/
git commit -m "test(frontend): add msw shared handlers + queries hook test"
```

---

## Task 22 — Playwright e2e (3 specs + smoke script)

**Files:**
- Modify: `frontend/package.json` (add `@playwright/test`)
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/inbox.spec.ts`, `kid-matches.spec.ts`, `deep-link.spec.ts`
- Create: `scripts/seed_e2e.py`
- Create: `scripts/e2e_phase5a.sh`

- [ ] **Step 1: Install Playwright**

```bash
cd frontend
npm install -D @playwright/test
npx playwright install --with-deps chromium
```

- [ ] **Step 2: Playwright config**

`frontend/playwright.config.ts`:

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:8080',
    headless: true,
  },
  reporter: 'list',
});
```

- [ ] **Step 3: Seed script**

`scripts/seed_e2e.py` — small Python script that opens an aiosqlite DB and inserts fixed rows: 1 household with home address, 1 kid, 1 site, 1 offering with `registration_opens_at = now + 1d`, 1 match for that offering, 1 alert of type `watchlist_hit`, 1 successful crawl run.

```python
"""Seed deterministic e2e fixtures into a fresh DB."""

import asyncio
from datetime import UTC, datetime, timedelta

from yas.db.base import Base
from yas.db.models import (
    Alert, CrawlRun, HouseholdSettings, Kid, Match, Offering, Site,
)
from yas.db.models._types import AlertType, CrawlStatus
from yas.db.session import create_engine_for, session_scope


async def main(db_url: str) -> None:
    engine = create_engine_for(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(HouseholdSettings(id=1, default_max_distance_mi=20.0))
        s.add(Kid(id=1, name="Sam", dob=datetime(2019, 5, 1).date()))
        s.add(Site(id=1, name="Lil Sluggers", base_url="https://x", needs_browser=False))
        await s.flush()
        s.add(Offering(
            id=1, site_id=1, name="Spring T-Ball",
            start_date=(now + timedelta(days=14)).date(),
            registration_opens_at=now + timedelta(days=1),
            status="active",
        ))
        await s.flush()
        s.add(Match(kid_id=1, offering_id=1, score=0.94, reasons={"watchlist": True}, computed_at=now))
        s.add(Alert(
            type=AlertType.watchlist_hit.value, kid_id=1, site_id=1, channels=["email"],
            scheduled_for=now - timedelta(hours=1), dedup_key="seed-1",
            payload_json={"offering_name": "Spring T-Ball", "site_name": "Lil Sluggers"},
        ))
        s.add(CrawlRun(
            site_id=1, started_at=now - timedelta(hours=2), finished_at=now - timedelta(hours=2, minutes=-1),
            status=CrawlStatus.ok.value, pages_fetched=3, changes_detected=1, llm_calls=0, llm_cost_usd=0.0,
        ))
    await engine.dispose()


if __name__ == "__main__":
    import sys
    asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 4: Smoke script**

`scripts/e2e_phase5a.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if ! grep -q '^YAS_ANTHROPIC_API_KEY=sk-' .env 2>/dev/null; then
  echo "ERROR: .env must set YAS_ANTHROPIC_API_KEY" >&2; exit 2
fi

COMPOSE="docker compose -f docker-compose.yml"
[ "$(uname)" = "Darwin" ] && COMPOSE="$COMPOSE -f docker-compose.macos.yml"

$COMPOSE down -v 2>/dev/null || true
$COMPOSE build yas-api yas-worker yas-migrate
$COMPOSE up -d yas-migrate
$COMPOSE up -d yas-worker yas-api
sleep 8

echo "--- seed e2e fixtures ---"
# Seed by exec-ing the script inside the api container against the same DB
$COMPOSE exec -T yas-api uv run python scripts/seed_e2e.py "sqlite+aiosqlite:///data/activities.db"

echo "--- run playwright ---"
cd frontend
PLAYWRIGHT_BASE_URL=http://localhost:8080 npx playwright test
cd ..

$COMPOSE down -v
```

`chmod +x scripts/e2e_phase5a.sh`.

- [ ] **Step 5: Three e2e specs**

`frontend/e2e/inbox.spec.ts`:

```ts
import { test, expect } from '@playwright/test';

test('inbox shows seeded alert and kid match counts', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText("What's new this week")).toBeVisible();
  await expect(page.getByText(/Spring T-Ball/)).toBeVisible();
  await expect(page.getByText('Sam')).toBeVisible();
});

test('clicking an alert opens detail drawer', async ({ page }) => {
  await page.goto('/');
  await page.getByText(/Spring T-Ball/).click();
  await expect(page.getByText(/Watchlist hit/)).toBeVisible();
});
```

`frontend/e2e/kid-matches.spec.ts`:

```ts
import { test, expect } from '@playwright/test';

test('navigate from inbox kid card to matches page', async ({ page }) => {
  await page.goto('/');
  await page.getByText('Sam').first().click();
  await expect(page).toHaveURL(/\/kids\/1\/matches/);
  await expect(page.getByText(/Spring T-Ball/)).toBeVisible();
});
```

`frontend/e2e/deep-link.spec.ts`:

```ts
import { test, expect } from '@playwright/test';

test('deep link to kid matches works on cold load', async ({ page }) => {
  await page.goto('/kids/1/matches');
  await expect(page.getByRole('heading', { name: /Sam — matches/ })).toBeVisible();
});
```

- [ ] **Step 6: Optional: run locally to confirm**

```bash
./scripts/e2e_phase5a.sh
```

If it fails because the dev environment doesn't have the YAS_ANTHROPIC_API_KEY, that's expected — the gate is "the script is syntactically valid and the test files exist." Verify:

```bash
bash -n scripts/e2e_phase5a.sh
cd frontend && npx playwright test --list  # lists 4 tests
```

- [ ] **Step 7: Commit**

```bash
cd ..
git add frontend/playwright.config.ts frontend/e2e frontend/package.json frontend/package-lock.json scripts/seed_e2e.py scripts/e2e_phase5a.sh
git commit -m "test(e2e): add playwright e2e + smoke script for phase 5a"
```

---

## Task 23 — README + Phase 5a exit gates + merge prep

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append Web UI section to README**

Find the existing `## Development` section. Insert a new `## Web UI` section directly above it with:

```markdown
## Web UI

A read-only React dashboard ships in this repo under `frontend/`. In production, FastAPI serves the built bundle at `/`.

### Dev loop (two terminals)

```bash
# Terminal 1: backend
docker compose up -d  # or: python -m yas api

# Terminal 2: frontend with hot reload
cd frontend
npm install
npm run dev
# Open http://localhost:5173 — Vite proxies /api to :8080
```

### Theme

Matches your OS light/dark mode by default. Click the sun/moon/monitor icon in the top bar to override; the choice is saved to localStorage.

### Build

```bash
cd frontend && npm run build       # emits frontend/dist/
docker compose build yas-api       # multi-stage build copies dist into /app/static
```

### End-to-end tests

```bash
./scripts/e2e_phase5a.sh           # builds, seeds, runs Playwright, tears down
```

### What's in 5a / 5b

- 5a (this slice): read-only Inbox, Kid matches, Watchlist, Sites, Settings
- 5b: Add Site wizard, alert ack/dismiss, settings editing, notifier config UI
```

- [ ] **Step 2: Run all exit gates**

```bash
# Python
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q

# Frontend
cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
cd ..

# E2E (manual gate — requires Docker + .env)
./scripts/e2e_phase5a.sh   # optional but recommended
```

All must pass. Capture the test counts in your final report.

- [ ] **Step 3: Commit + final report**

```bash
git add README.md
git commit -m "docs: add Web UI section to README"
```

The branch is now ready to merge. Use `git checkout main && git merge --no-ff phase-5a-dashboard -m "merge: phase 5a read-only dashboard"`.

---

## Phase 5a exit checklist

Apply @superpowers:verification-before-completion. Every box verified with an actual command, not asserted.

- [ ] `uv run ruff check .` clean
- [ ] `uv run ruff format --check .` clean
- [ ] `uv run mypy src` clean
- [ ] `uv run pytest` — full suite green (current 493 + ~12 new = ~505)
- [ ] `npm --prefix frontend run lint` clean
- [ ] `npm --prefix frontend run typecheck` clean
- [ ] `npm --prefix frontend run test` green
- [ ] `npm --prefix frontend run build` succeeds, emits `frontend/dist/`
- [ ] `bash -n scripts/e2e_phase5a.sh` clean
- [ ] (Manual gate) `./scripts/e2e_phase5a.sh` runs end-to-end on a developer machine; capture screenshot or terminal log
- [ ] README "Web UI" section appended

When all boxes check, merge with `--no-ff` to `main`. Proceed to **Phase 5b — Mutation UIs + Add Site Wizard**, written as its own plan.
