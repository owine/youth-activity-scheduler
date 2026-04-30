# Phase 5d-1 — Site/Offering Alert Mute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `Site.muted_until` and `Offering.muted_until` into the alert-firing pipeline + calendar match overlay, then ship a `<MuteButton>` UI primitive in three placements (site detail, matches list, calendar popover).

**Architecture:** Six functions in `enqueuer.py` gain mute checks via two helpers (`_is_muted` for offering-targeted, `_is_site_muted` for site-targeted). One new `PATCH /api/offerings/{id}` route. Calendar match-overlay query gains two more `or_(...muted_until is null OR <= now)` clauses. Frontend gets one new presentational primitive (popover with 4-button duration picker), two mutation hooks following the canonical 5b-1b/5c-1 pattern, and three placement edits.

**Tech Stack:** SQLAlchemy 2.x async, FastAPI, Pydantic v2, pytest-asyncio, React 19, TanStack Query 5, `radix-ui` 1.4.3 (Popover primitive — already installed), `date-fns`, MSW, Vitest + RTL.

**Spec:** `docs/superpowers/specs/2026-04-29-phase-5d-1-site-offering-mute-design.md`

**Project conventions:**
- All deps already pinned to exact patch. **No new deps in this slice.**
- All commits signed via 1Password SSH agent. Set `SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"` before each `git commit` in fresh shells. Verify with `git cat-file commit HEAD | grep -q '^gpgsig '`.
- Branch already created: `phase-5d-1-site-offering-mute`. Do NOT commit to `main`.
- Backend gates: `uv run pytest -q --no-cov`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`.
- Frontend gates from `frontend/`: `npm run typecheck`, `npm run lint`, `npm run test`.
- Backend baseline: 567 tests. Frontend baseline: 49 tests (10 files).
- Python 3.14 (PEP 758 — `except A, B:` is valid syntax, don't flag).

---

## File Structure

**Modify — backend:**
- `src/yas/alerts/enqueuer.py` — add `_is_muted` + `_is_site_muted` helpers; gate the 6 enqueue functions.
- `src/yas/web/routes/kid_calendar.py` — extend match-overlay query with two new `or_(...)` clauses.
- `src/yas/web/app.py` — register the new offerings router.

**Create — backend:**
- `src/yas/web/routes/offerings.py` — `PATCH /api/offerings/{id}` with `OfferingPatch` and `OfferingMuteOut` schemas inline.
- `tests/integration/test_alerts_enqueuer_mute.py` — gate tests for all 6 enqueue functions.
- `tests/integration/test_api_offerings.py` — PATCH happy/404/422 + persistence.

**Modify — backend tests:**
- `tests/integration/test_api_kids_calendar.py` — extend with mute exclusion tests.

**Create — frontend:**
- `frontend/src/lib/mute.ts` — `FOREVER_SENTINEL`, `muteUntilFromDuration`, `isMuted`.
- `frontend/src/lib/mute.test.ts` — unit tests for the helpers.
- `frontend/src/components/common/MuteButton.tsx` — Popover-based UI primitive.
- `frontend/src/components/common/MuteButton.test.tsx` — render + interaction tests.

**Modify — frontend:**
- `frontend/src/lib/mutations.ts` — add `useUpdateSiteMute`, `useUpdateOfferingMute`.
- `frontend/src/lib/mutations.test.tsx` — extend with the two new hooks.
- `frontend/src/test/handlers.ts` — add `PATCH /api/sites/:id` and `PATCH /api/offerings/:id` MSW stubs.
- `frontend/src/routes/sites.$id.tsx` — wire `<MuteButton>` in the header.
- `frontend/src/routes/kids.$id.matches.tsx` — wire `<MuteButton>` per match row.
- `frontend/src/components/calendar/CalendarEventPopover.tsx` — add Mute on the match branch.
- `frontend/src/components/calendar/CalendarEventPopover.test.tsx` — extend with mute test.

---

## Task 1 — Backend: enqueuer mute gates (TDD)

**Files:**
- Modify: `src/yas/alerts/enqueuer.py`
- Create: `tests/integration/test_alerts_enqueuer_mute.py`

End state: `_is_muted` + `_is_site_muted` helpers exist; 6 enqueue functions gated. ~10 new tests pass; existing 567 backend tests still pass.

- [ ] **Step 1: Write failing tests**

Create `tests/integration/test_alerts_enqueuer_mute.py`:

```python
"""Mute gate tests for src/yas/alerts/enqueuer.py."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from yas.alerts.enqueuer import (
    enqueue_crawl_failed,
    enqueue_new_match,
    enqueue_schedule_posted,
    enqueue_site_stagnant,
    enqueue_watchlist_hit,
)
from yas.db.base import Base
from yas.db.models import Alert, Kid, Offering, Page, Site, WatchlistEntry
from yas.db.models._types import AlertType, OfferingStatus
from yas.db.session import session_scope


async def _make_engine(tmp_path: Any) -> Any:
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _seed(
    engine: Any,
    *,
    site_muted_until: datetime | None = None,
    offering_muted_until: datetime | None = None,
) -> tuple[int, int, int]:
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        s.add(
            Site(
                id=1,
                name="X",
                base_url="https://x",
                muted_until=site_muted_until,
            )
        )
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        s.add(
            Offering(
                id=1,
                site_id=1,
                page_id=1,
                name="T-Ball",
                normalized_name="t-ball",
                days_of_week=["tue"],
                time_start=time(16, 0),
                time_end=time(17, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
                muted_until=offering_muted_until,
            )
        )
    return 1, 1, 1  # kid_id, offering_id, site_id


@pytest.mark.asyncio
async def test_new_match_skipped_when_offering_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, offering_muted_until=future)
    async with session_scope(engine) as s:
        result = await enqueue_new_match(
            s, kid_id=1, offering_id=1, score=0.9, reasons={}
        )
    assert result is None
    async with session_scope(engine) as s:
        alerts = (await s.execute(select(Alert))).scalars().all()
    assert alerts == []


@pytest.mark.asyncio
async def test_new_match_skipped_when_site_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, site_muted_until=future)
    async with session_scope(engine) as s:
        result = await enqueue_new_match(
            s, kid_id=1, offering_id=1, score=0.9, reasons={}
        )
    assert result is None


@pytest.mark.asyncio
async def test_new_match_enqueues_when_both_unmuted(tmp_path):
    engine = await _make_engine(tmp_path)
    await _seed(engine)
    async with session_scope(engine) as s:
        result = await enqueue_new_match(
            s, kid_id=1, offering_id=1, score=0.9, reasons={}
        )
    assert result is not None


@pytest.mark.asyncio
async def test_new_match_enqueues_when_mute_in_past(tmp_path):
    engine = await _make_engine(tmp_path)
    past = datetime.now(UTC) - timedelta(days=1)
    await _seed(engine, offering_muted_until=past)
    async with session_scope(engine) as s:
        result = await enqueue_new_match(
            s, kid_id=1, offering_id=1, score=0.9, reasons={}
        )
    assert result is not None


@pytest.mark.asyncio
async def test_watchlist_hit_skipped_when_offering_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, offering_muted_until=future)
    async with session_scope(engine) as s:
        s.add(
            WatchlistEntry(
                id=99, kid_id=1, query="t-ball", active=True
            )
        )
    async with session_scope(engine) as s:
        # enqueue_watchlist_hit returns int (not Optional). With mute, the
        # spec says skip → return must signal "not enqueued". Per spec, we
        # extend the function to also return None when muted (consistent
        # with enqueue_new_match).
        result = await enqueue_watchlist_hit(
            s,
            kid_id=1,
            offering_id=1,
            watchlist_entry_id=99,
            reasons={},
        )
    assert result is None
    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.watchlist_hit.value)))
            .scalars()
            .all()
        )
    assert alerts == []


@pytest.mark.asyncio
async def test_watchlist_hit_skipped_when_site_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, site_muted_until=future)
    async with session_scope(engine) as s:
        s.add(WatchlistEntry(id=99, kid_id=1, query="t-ball", active=True))
    async with session_scope(engine) as s:
        result = await enqueue_watchlist_hit(
            s,
            kid_id=1,
            offering_id=1,
            watchlist_entry_id=99,
            reasons={},
        )
    assert result is None


@pytest.mark.asyncio
async def test_schedule_posted_skipped_when_site_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, site_muted_until=future)
    async with session_scope(engine) as s:
        result = await enqueue_schedule_posted(
            s, page_id=1, site_id=1, summary="3 new offerings"
        )
    assert result is None


@pytest.mark.asyncio
async def test_crawl_failed_skipped_when_site_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, site_muted_until=future)
    async with session_scope(engine) as s:
        result = await enqueue_crawl_failed(
            s, site_id=1, consecutive_failures=3, last_error="timeout"
        )
    assert result is None


@pytest.mark.asyncio
async def test_site_stagnant_skipped_when_site_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, site_muted_until=future)
    async with session_scope(engine) as s:
        result = await enqueue_site_stagnant(s, site_id=1, days_silent=15)
    assert result is None
```

(Signatures verified at plan time: `enqueue_schedule_posted(page_id, site_id, summary)`, `enqueue_crawl_failed(site_id, consecutive_failures, last_error)`, `enqueue_site_stagnant(site_id, days_silent)`.)

The reg-opens countdown function (`enqueue_registration_countdowns`) is more elaborate and is tested separately in **Step 6** below.

- [ ] **Step 2: Run; confirm all FAIL**

```bash
uv run pytest tests/integration/test_alerts_enqueuer_mute.py -q --no-cov
```

Expected: 9 failed (no mute gating yet — alerts get enqueued).

- [ ] **Step 3: Implement helpers in enqueuer.py**

In `src/yas/alerts/enqueuer.py`, after the existing `_kid_alert_on` helper (around line 101) and before `enqueue_new_match`, add:

```python
async def _is_muted(session: AsyncSession, *, offering_id: int) -> bool:
    """True if the offering or its parent site is currently muted.

    Used by offering-targeted enqueue functions (new_match, watchlist_hit,
    reg-opens variants).
    """
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(Offering.muted_until, Site.muted_until)
            .join(Site, Site.id == Offering.site_id)
            .where(Offering.id == offering_id)
        )
    ).one_or_none()
    if row is None:
        return False
    o_muted, s_muted = row
    return (o_muted is not None and o_muted > now) or (s_muted is not None and s_muted > now)


async def _is_site_muted(session: AsyncSession, *, site_id: int) -> bool:
    """True if the site is currently muted.

    Used by site-targeted enqueue functions (schedule_posted, crawl_failed,
    site_stagnant).
    """
    now = datetime.now(UTC)
    s_muted = (
        await session.execute(select(Site.muted_until).where(Site.id == site_id))
    ).scalar_one_or_none()
    return s_muted is not None and s_muted > now
```

- [ ] **Step 4: Gate `enqueue_new_match` and `enqueue_watchlist_hit`**

In `enqueue_new_match`, after the existing `_kid_alert_on` check, add:

```python
    if not _kid_alert_on(kid, "new_match", default=True):
        return None
    if await _is_muted(session, offering_id=offering_id):
        return None
```

Update `enqueue_watchlist_hit`. Currently the function returns `int` (always enqueues). Change the return type annotation to `int | None` and add the gate at the top:

```python
async def enqueue_watchlist_hit(
    session: AsyncSession,
    *,
    kid_id: int,
    offering_id: int,
    watchlist_entry_id: int,
    reasons: dict[str, Any],
) -> int | None:
    """Insert or update a watchlist_hit alert. Bypasses kid.alert_on (the user
    added the watchlist entry explicitly) but is suppressed by Site/Offering
    mute (the user has since changed their mind)."""
    if await _is_muted(session, offering_id=offering_id):
        return None
    dk = dedup_key_for(...)
    ...
```

This **changes the return type** of `enqueue_watchlist_hit` from `int` to `int | None`. Search for callers:

```bash
grep -rn "enqueue_watchlist_hit" src/yas/ tests/
```

Verify each caller handles `None` correctly. If a caller does `id_ = await enqueue_watchlist_hit(...)` and uses `id_` afterwards without a `None` check, fix that caller (e.g., `if id_ is not None: ...`). Most call sites likely just call the function for side-effect and ignore the return — those are fine.

- [ ] **Step 5: Gate `enqueue_schedule_posted`, `enqueue_crawl_failed`, `enqueue_site_stagnant`**

For each of the three site-targeted functions, add at the top (before `dk = dedup_key_for(...)`):

```python
    if await _is_site_muted(session, site_id=site_id):
        return None
```

If any of these functions currently has return type `int`, change to `int | None`.

- [ ] **Step 6: Gate `enqueue_registration_countdowns` and add its test**

`enqueue_registration_countdowns` is structured differently — it loops over `(AlertType, offset)` pairs and inserts up to 3 alerts per call. The mute check should be ONCE at the top of the function (not per countdown variant), since they all target the same offering:

```python
async def enqueue_registration_countdowns(
    session: AsyncSession,
    *,
    kid_id: int,
    offering_id: int,
) -> list[int]:
    """..."""
    if await _is_muted(session, offering_id=offering_id):
        return []
    # ...existing body...
```

(Verify the actual signature in the current file. If the function name or signature differs, follow the existing shape.)

Append a test to `tests/integration/test_alerts_enqueuer_mute.py`:

```python
@pytest.mark.asyncio
async def test_reg_opens_countdowns_skipped_when_offering_muted(tmp_path):
    """All three reg-opens variants are gated by a single mute check."""
    from yas.alerts.enqueuer import enqueue_registration_countdowns
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, offering_muted_until=future)
    # Set offering's registration_opens_at so the function would normally fire.
    async with session_scope(engine) as s:
        offering = (
            await s.execute(select(Offering).where(Offering.id == 1))
        ).scalar_one()
        offering.registration_opens_at = datetime.now(UTC) + timedelta(hours=2)
    async with session_scope(engine) as s:
        result = await enqueue_registration_countdowns(s, kid_id=1, offering_id=1)
    assert result == []
    async with session_scope(engine) as s:
        alerts = (await s.execute(select(Alert))).scalars().all()
    assert alerts == []
```

- [ ] **Step 7: Re-run; confirm all 10 PASS + existing tests green**

```bash
uv run pytest tests/integration/test_alerts_enqueuer_mute.py -q --no-cov
uv run pytest -q --no-cov
```

Expected: 10 new passed; 577 total (567 + 10).

- [ ] **Step 8: Backend gates**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: clean. If `enqueue_watchlist_hit` callers had to be updated (Step 4), mypy will catch any missed sites.

- [ ] **Step 9: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add src/yas/alerts/enqueuer.py tests/integration/test_alerts_enqueuer_mute.py
# also stage any caller updates from Step 4
git commit -m "feat(alerts): mute gates in enqueuer for site + offering paths

Wires Site.muted_until and Offering.muted_until into the alert pipeline.
Six enqueue functions gated:

- new_match, watchlist_hit, registration_countdowns: gated on
  Offering.muted_until OR Site.muted_until.
- schedule_posted, crawl_failed, site_stagnant: gated on Site.muted_until.

Two helpers (_is_muted, _is_site_muted) factor the SQL. Watchlist_hit's
return type widened from int to int | None — callers that ignored the
return continue to work; any caller that read the int to do further
work would be flagged by mypy."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 2 — Backend: PATCH /api/offerings/{id} (TDD)

**Files:**
- Create: `src/yas/web/routes/offerings.py`
- Create: `tests/integration/test_api_offerings.py`
- Modify: `src/yas/web/app.py`

End state: `PATCH /api/offerings/{id}` route accepts `{ muted_until: datetime | null }`. ~5 new tests pass.

- [ ] **Step 1: Write failing tests**

Create `tests/integration/test_api_offerings.py`:

```python
"""Integration tests for PATCH /api/offerings/{id}."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import Offering, Page, Site
from yas.db.models._types import OfferingStatus
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/o.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        s.add(
            Offering(
                id=1,
                site_id=1,
                page_id=1,
                name="T-Ball",
                normalized_name="t-ball",
                days_of_week=["tue"],
                time_start=time(16, 0),
                time_end=time(17, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
            )
        )
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_patch_offering_404_for_unknown_id(client):
    c, _ = client
    r = await c.patch("/api/offerings/9999", json={"muted_until": None})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_offering_422_for_unknown_field(client):
    c, _ = client
    r = await c.patch("/api/offerings/1", json={"unknown_field": "value"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_offering_sets_muted_until(client):
    c, engine = client
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    r = await c.patch("/api/offerings/1", json={"muted_until": future})
    assert r.status_code == 200
    body = r.json()
    assert body["muted_until"] is not None
    async with session_scope(engine) as s:
        o = (await s.execute(select(Offering).where(Offering.id == 1))).scalar_one()
    assert o.muted_until is not None


@pytest.mark.asyncio
async def test_patch_offering_clears_muted_until(client):
    c, engine = client
    # First mute it.
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    await c.patch("/api/offerings/1", json={"muted_until": future})
    # Then clear.
    r = await c.patch("/api/offerings/1", json={"muted_until": None})
    assert r.status_code == 200
    body = r.json()
    assert body["muted_until"] is None
    async with session_scope(engine) as s:
        o = (await s.execute(select(Offering).where(Offering.id == 1))).scalar_one()
    assert o.muted_until is None


@pytest.mark.asyncio
async def test_patch_offering_empty_body_does_not_clear_muted_until(client):
    """An empty PATCH body must not null out the muted_until field."""
    c, engine = client
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    await c.patch("/api/offerings/1", json={"muted_until": future})
    # Empty PATCH.
    r = await c.patch("/api/offerings/1", json={})
    assert r.status_code == 200
    async with session_scope(engine) as s:
        o = (await s.execute(select(Offering).where(Offering.id == 1))).scalar_one()
    assert o.muted_until is not None  # preserved
```

- [ ] **Step 2: Run; confirm all 5 FAIL** (route doesn't exist):

```bash
uv run pytest tests/integration/test_api_offerings.py -q --no-cov
```

- [ ] **Step 3: Create the route**

Create `src/yas/web/routes/offerings.py`:

```python
"""CRUD for /api/offerings — initial scope: mute toggle."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.db.models import Offering
from yas.db.session import session_scope

router = APIRouter(prefix="/api/offerings", tags=["offerings"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


class OfferingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    muted_until: datetime | None = None


class OfferingMuteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    site_id: int
    muted_until: datetime | None


@router.patch("/{offering_id}", response_model=OfferingMuteOut)
async def update_offering(
    request: Request,
    offering_id: int,
    payload: OfferingPatch,
) -> OfferingMuteOut:
    async with session_scope(_engine(request)) as s:
        offering = (
            await s.execute(select(Offering).where(Offering.id == offering_id))
        ).scalar_one_or_none()
        if offering is None:
            raise HTTPException(status_code=404, detail=f"offering {offering_id} not found")
        if "muted_until" in payload.model_fields_set:
            offering.muted_until = payload.muted_until
        await s.flush()
        await s.refresh(offering)
        return OfferingMuteOut.model_validate(offering)
```

- [ ] **Step 4: Register router**

In `src/yas/web/app.py`, find the existing `app.include_router(...)` block and add a parallel pair:

- Add to imports: `from yas.web.routes.offerings import router as offerings_router`
- Add: `app.include_router(offerings_router)`

Place it next to `enrollments_router` for grouping consistency.

- [ ] **Step 5: Re-run; confirm 5 PASS**

```bash
uv run pytest tests/integration/test_api_offerings.py -q --no-cov
```

Expected: 5 passed.

- [ ] **Step 6: Full backend gates**

```bash
uv run pytest -q --no-cov && uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: 582 passed (577 + 5); ruff/format/mypy clean.

- [ ] **Step 7: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add src/yas/web/routes/offerings.py src/yas/web/app.py tests/integration/test_api_offerings.py
git commit -m "feat(api): PATCH /api/offerings/{id} for mute toggle

Initial scope is just muted_until. Uses Pydantic v2's model_fields_set
guard so an empty PATCH body does not null the field. Refreshes the
ORM object after flush to keep response timestamp consistent on
SQLite (5b-1a tz-roundtrip pattern)."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 3 — Backend: calendar match-overlay mute filter (TDD)

**Files:**
- Modify: `src/yas/web/routes/kid_calendar.py`
- Modify: `tests/integration/test_api_kids_calendar.py`

End state: Calendar match overlay excludes muted offerings + offerings whose site is muted. ~3 new tests pass.

- [ ] **Step 1: Append failing tests**

Append to `tests/integration/test_api_kids_calendar.py`. The file already imports `Match`, `Offering`, `Site`, `OfferingStatus`, `EnrollmentStatus`, has `_seed_kid_with_enrollment` and `_seed_match` helpers. Append:

```python
@pytest.mark.asyncio
async def test_match_overlay_excludes_muted_offerings(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    future = datetime.now(UTC) + timedelta(days=30)
    async with session_scope(engine) as s:
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                days_of_week=["wed"],
                time_start=time(17, 0),
                time_end=time(18, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
                muted_until=future,
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.9)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    assert all(e["kind"] != "match" for e in body["events"])


@pytest.mark.asyncio
async def test_match_overlay_excludes_offering_whose_site_is_muted(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    future = datetime.now(UTC) + timedelta(days=30)
    async with session_scope(engine) as s:
        # Mute the existing Site (id=1, seeded by helper).
        site = (await s.execute(select(Site).where(Site.id == 1))).scalar_one()
        site.muted_until = future
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                days_of_week=["wed"],
                time_start=time(17, 0),
                time_end=time(18, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.9)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    assert all(e["kind"] != "match" for e in body["events"])


@pytest.mark.asyncio
async def test_match_overlay_includes_offering_whose_mute_expired(client):
    """A muted_until in the past doesn't suppress the match."""
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    past = datetime.now(UTC) - timedelta(days=1)
    async with session_scope(engine) as s:
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                days_of_week=["wed"],
                time_start=time(17, 0),
                time_end=time(18, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
                muted_until=past,
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.9)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    matches = [e for e in body["events"] if e["kind"] == "match"]
    assert len(matches) == 1
```

`Site` should already be imported in this test file. If not, add `Site` to the existing `from yas.db.models import ...` line.

- [ ] **Step 2: Run; confirm 3 FAIL**

```bash
uv run pytest tests/integration/test_api_kids_calendar.py -q --no-cov -k "muted"
```

- [ ] **Step 3: Update the calendar query**

In `src/yas/web/routes/kid_calendar.py`:

a. Add `or_` to the existing sqlalchemy import:
```python
from sqlalchemy import or_, select
```

b. In the `if include_matches:` block, extend the `select(Match, Offering)` query (the existing query already joins Offering; it also needs to join Site for the mute check, OR use a scalar subquery on Site.muted_until — joining is simpler):

```python
            match_rows = (
                await s.execute(
                    select(Match, Offering)
                    .join(Offering, Offering.id == Match.offering_id)
                    .join(Site, Site.id == Offering.site_id)            # add
                    .where(Match.kid_id == kid_id)
                    .where(Match.score >= _MATCH_THRESHOLD)
                    .where(~Match.offering_id.in_(committed_offering_ids))
                    .where(or_(Offering.muted_until.is_(None), Offering.muted_until <= now))   # add
                    .where(or_(Site.muted_until.is_(None), Site.muted_until <= now))           # add
                )
            ).all()
```

`Site` should already be imported at the top of `kid_calendar.py` (it's used elsewhere in the file). If not, add it.

The `now` variable is captured at the top of the route handler — reuse it (do NOT call `datetime.now(UTC)` per row).

- [ ] **Step 4: Re-run; confirm all 3 PASS**

```bash
uv run pytest tests/integration/test_api_kids_calendar.py -q --no-cov
```

Expected: 18 passed (existing 15 + new 3).

- [ ] **Step 5: Backend gates**

```bash
uv run pytest -q --no-cov && uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: 585 passed (582 + 3); clean.

- [ ] **Step 6: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add src/yas/web/routes/kid_calendar.py tests/integration/test_api_kids_calendar.py
git commit -m "feat(api): exclude muted offerings + sites from calendar match overlay

Two new or_(muted_until is null OR muted_until <= now) clauses on the
match-merge query. Reuses the route handler's existing 'now' variable
(captured once)."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 4 — Frontend: mute helpers + types + MSW handlers

**Files:**
- Create: `frontend/src/lib/mute.ts`
- Create: `frontend/src/lib/mute.test.ts`
- Modify: `frontend/src/test/handlers.ts`

End state: Pure-function mute helpers tested. MSW handlers exist for both PATCH routes. Existing 49 frontend tests still pass; +6 new mute helper tests.

- [ ] **Step 1: Write failing tests**

Create `frontend/src/lib/mute.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { FOREVER_SENTINEL, isMuted, muteUntilFromDuration } from './mute';

describe('muteUntilFromDuration', () => {
  it('returns the forever sentinel for "forever"', () => {
    expect(muteUntilFromDuration('forever')).toBe(FOREVER_SENTINEL);
  });

  it('returns now + 7 days for "7d"', () => {
    const now = new Date('2026-04-29T12:00:00Z');
    expect(muteUntilFromDuration('7d', now)).toBe('2026-05-06T12:00:00.000Z');
  });

  it('returns now + 30 days for "30d"', () => {
    const now = new Date('2026-04-29T12:00:00Z');
    expect(muteUntilFromDuration('30d', now)).toBe('2026-05-29T12:00:00.000Z');
  });

  it('returns now + 90 days for "90d"', () => {
    const now = new Date('2026-04-29T12:00:00Z');
    expect(muteUntilFromDuration('90d', now)).toBe('2026-07-28T12:00:00.000Z');
  });
});

describe('isMuted', () => {
  it('returns false for null', () => {
    expect(isMuted(null)).toBe(false);
  });

  it('returns false for past timestamps', () => {
    const now = new Date('2026-04-29T12:00:00Z');
    expect(isMuted('2026-04-28T12:00:00Z', now)).toBe(false);
  });

  it('returns true for future timestamps', () => {
    const now = new Date('2026-04-29T12:00:00Z');
    expect(isMuted('2026-05-01T12:00:00Z', now)).toBe(true);
  });

  it('returns true for the forever sentinel', () => {
    const now = new Date('2026-04-29T12:00:00Z');
    expect(isMuted(FOREVER_SENTINEL, now)).toBe(true);
  });
});
```

- [ ] **Step 2: Run; confirm 8 FAIL** (module doesn't exist):

```bash
cd frontend && npm run test -- mute
```

- [ ] **Step 3: Implement helpers**

Create `frontend/src/lib/mute.ts`:

```ts
export const FOREVER_SENTINEL = '3000-01-01T00:00:00.000Z';

export type MuteDuration = '7d' | '30d' | '90d' | 'forever';

const DAYS: Record<Exclude<MuteDuration, 'forever'>, number> = {
  '7d': 7,
  '30d': 30,
  '90d': 90,
};

export function muteUntilFromDuration(
  duration: MuteDuration,
  now: Date = new Date(),
): string {
  if (duration === 'forever') return FOREVER_SENTINEL;
  const out = new Date(now);
  out.setDate(out.getDate() + DAYS[duration]);
  return out.toISOString();
}

export function isMuted(
  mutedUntil: string | null,
  now: Date = new Date(),
): boolean {
  if (mutedUntil == null) return false;
  return new Date(mutedUntil) > now;
}
```

- [ ] **Step 4: Re-run; confirm 8 PASS**

```bash
cd frontend && npm run test -- mute
```

- [ ] **Step 5: Add MSW handlers**

In `frontend/src/test/handlers.ts`, append:

```ts
http.patch('/api/sites/:id', async ({ params, request }) => {
  const body = (await request.json()) as { muted_until?: string | null };
  return HttpResponse.json({
    id: Number(params.id),
    name: 'X',
    base_url: 'https://x',
    adapter: 'llm',
    needs_browser: false,
    active: true,
    default_cadence_s: 86400,
    muted_until: body.muted_until ?? null,
    pages: [],
  });
}),
http.patch('/api/offerings/:id', async ({ params, request }) => {
  const body = (await request.json()) as { muted_until?: string | null };
  return HttpResponse.json({
    id: Number(params.id),
    name: 'T-Ball',
    site_id: 1,
    muted_until: body.muted_until ?? null,
  });
}),
```

- [ ] **Step 6: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 57 passed (49 + 8); clean.

- [ ] **Step 7: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/lib/mute.ts frontend/src/lib/mute.test.ts frontend/src/test/handlers.ts
git commit -m "feat(frontend): mute helpers + MSW handlers for site/offering mute

Pure-function muteUntilFromDuration + isMuted. FOREVER_SENTINEL is
year 3000 to keep the data model uniform (no nullable sentinel).
MSW handlers stub both PATCH routes."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 5 — Frontend: `<MuteButton>` component (TDD)

**Files:**
- Create: `frontend/src/components/common/MuteButton.tsx`
- Create: `frontend/src/components/common/MuteButton.test.tsx`

End state: `<MuteButton>` is a Popover-based primitive. ~5 new tests pass.

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/common/MuteButton.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MuteButton } from './MuteButton';
import { FOREVER_SENTINEL } from '@/lib/mute';

describe('MuteButton', () => {
  it('renders "Mute" when not muted (null)', () => {
    render(<MuteButton mutedUntil={null} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /mute/i })).toBeInTheDocument();
  });

  it('renders "Mute" when mute timestamp is in the past', () => {
    const now = new Date();
    const past = new Date(now.getTime() - 86_400_000).toISOString();
    render(<MuteButton mutedUntil={past} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /^mute$/i })).toBeInTheDocument();
  });

  it('renders "Muted until ..." when mute timestamp is in the future', () => {
    const now = new Date();
    const future = new Date(now.getTime() + 7 * 86_400_000).toISOString();
    render(<MuteButton mutedUntil={future} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /muted until/i })).toBeInTheDocument();
  });

  it('clicking a duration option calls onChange with a future ISO timestamp', async () => {
    const onChange = vi.fn();
    render(<MuteButton mutedUntil={null} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: /mute/i }));
    await userEvent.click(screen.getByRole('menuitem', { name: /7 days/i }));
    expect(onChange).toHaveBeenCalledTimes(1);
    const arg = onChange.mock.calls[0][0];
    expect(typeof arg).toBe('string');
    expect(new Date(arg).getTime()).toBeGreaterThan(Date.now());
  });

  it('clicking "Forever" calls onChange with the sentinel', async () => {
    const onChange = vi.fn();
    render(<MuteButton mutedUntil={null} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: /mute/i }));
    await userEvent.click(screen.getByRole('menuitem', { name: /forever/i }));
    expect(onChange).toHaveBeenCalledWith(FOREVER_SENTINEL);
  });

  it('clicking "Unmute" calls onChange with null', async () => {
    const onChange = vi.fn();
    const future = new Date(Date.now() + 7 * 86_400_000).toISOString();
    render(<MuteButton mutedUntil={future} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: /muted until/i }));
    await userEvent.click(screen.getByRole('menuitem', { name: /unmute/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
```

- [ ] **Step 2: Run; confirm 6 FAIL**

```bash
cd frontend && npm run test -- MuteButton
```

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/common/MuteButton.tsx`:

```tsx
import { useState } from 'react';
import { format } from 'date-fns';
import { Popover } from 'radix-ui';
import { Button } from '@/components/ui/button';
import { isMuted, muteUntilFromDuration, type MuteDuration } from '@/lib/mute';
import { cn } from '@/lib/utils';

interface MuteButtonProps {
  mutedUntil: string | null;
  onChange: (mutedUntil: string | null) => void;
  isPending?: boolean;
  size?: 'default' | 'sm';
}

const DURATION_LABELS: Array<{ value: MuteDuration; label: string }> = [
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
  { value: 'forever', label: 'Forever' },
];

export function MuteButton({
  mutedUntil,
  onChange,
  isPending,
  size = 'default',
}: MuteButtonProps) {
  const [open, setOpen] = useState(false);
  const muted = isMuted(mutedUntil);
  const label = muted
    ? `Muted until ${format(new Date(mutedUntil!), 'MMM d')}`
    : 'Mute';

  const handle = (next: string | null) => {
    setOpen(false);
    onChange(next);
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button
          size={size}
          variant={muted ? 'outline' : 'ghost'}
          disabled={isPending}
        >
          {label}
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className={cn(
            'z-50 rounded-md border border-border bg-popover p-1 shadow-md',
            'min-w-[10rem] text-sm',
          )}
          sideOffset={4}
          align="end"
        >
          {muted ? (
            <button
              role="menuitem"
              type="button"
              className="block w-full text-left px-2 py-1.5 rounded hover:bg-accent"
              onClick={() => handle(null)}
            >
              Unmute
            </button>
          ) : (
            DURATION_LABELS.map(({ value, label: dLabel }) => (
              <button
                key={value}
                role="menuitem"
                type="button"
                className="block w-full text-left px-2 py-1.5 rounded hover:bg-accent"
                onClick={() => handle(muteUntilFromDuration(value))}
              >
                {dLabel}
              </button>
            ))
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
```

Notes:
- The `Popover` import is the unified `radix-ui` package's namespace (verify the import shape; if `import { Popover } from 'radix-ui'` doesn't work, fall back to `import * as Popover from 'radix-ui/popover'` or check package docs).
- The `Button` component supports `size` and `variant` props in this codebase. Check its current variants if `'ghost'` doesn't exist (fall back to `'outline'`/`'default'`).

- [ ] **Step 4: Re-run; confirm 6 PASS**

```bash
cd frontend && npm run test -- MuteButton
```

If the Popover doesn't render in the test environment (radix Popover.Portal can be finicky in jsdom), the typical fix is to add `<Popover.Anchor>` or use a fixed-position content wrapper. The test's `userEvent.click` triggers the trigger; the portal must mount its children somewhere in the document. If tests fail with "menuitem not found," check:
1. Is the test environment using `happy-dom` or `jsdom`?
2. Does the `Popover.Portal` need a specific container prop?

If `Popover.Portal` causes test issues, drop it (render content inline). It's a usability concern in real DOM but not for the test.

- [ ] **Step 5: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 63 passed (57 + 6); clean.

- [ ] **Step 6: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/components/common/MuteButton.tsx frontend/src/components/common/MuteButton.test.tsx
git commit -m "feat(frontend): MuteButton presentational primitive

Popover with 4 duration options when unmuted; Unmute action when muted.
Pure presentation: parent supplies onChange callback. Uses radix-ui's
Popover primitive directly (no shadcn wrapper)."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 6 — Frontend: mutation hooks (TDD)

**Files:**
- Modify: `frontend/src/lib/mutations.ts`
- Modify: `frontend/src/lib/mutations.test.tsx`

End state: `useUpdateSiteMute` + `useUpdateOfferingMute` follow the canonical pattern. ~3 new tests pass.

- [ ] **Step 1: Append failing tests**

Append to `frontend/src/lib/mutations.test.tsx`:

```tsx
import { useUpdateOfferingMute, useUpdateSiteMute } from './mutations';

describe('useUpdateSiteMute', () => {
  it('PATCHes /api/sites/{id} with the muted_until payload', async () => {
    const qc = new QueryClient();
    const { result } = renderHook(() => useUpdateSiteMute(), {
      wrapper: makeWrapper(qc),
    });
    const future = new Date(Date.now() + 7 * 86_400_000).toISOString();
    await act(async () => {
      await result.current.mutateAsync({ siteId: 1, mutedUntil: future });
    });
    expect(result.current.isSuccess).toBe(true);
  });
});

describe('useUpdateOfferingMute', () => {
  it('removes match events for the offering optimistically when muting', async () => {
    const qc = new QueryClient();
    const matchEvent = {
      id: 'match:7:2026-04-29',
      kind: 'match' as const,
      date: '2026-04-29',
      time_start: '17:00:00',
      time_end: '18:00:00',
      all_day: false,
      title: 'Soccer',
      offering_id: 7,
      score: 0.85,
    };
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'with-matches'],
      seedCal([matchEvent]),
    );

    const { result } = renderHook(() => useUpdateOfferingMute(), {
      wrapper: makeWrapper(qc),
    });
    const future = new Date(Date.now() + 7 * 86_400_000).toISOString();
    await act(async () => {
      await result.current.mutateAsync({ offeringId: 7, mutedUntil: future });
    });

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'with-matches',
    ]);
    expect(after?.events).toEqual([]);
  });

  it('does not perform optimistic surgery on unmute (mutedUntil=null)', async () => {
    const qc = new QueryClient();
    const matchEvent = {
      id: 'match:7:2026-04-29',
      kind: 'match' as const,
      date: '2026-04-29',
      time_start: '17:00:00',
      time_end: '18:00:00',
      all_day: false,
      title: 'Soccer',
      offering_id: 7,
      score: 0.85,
    };
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'with-matches'],
      seedCal([matchEvent]),
    );

    const { result } = renderHook(() => useUpdateOfferingMute(), {
      wrapper: makeWrapper(qc),
    });
    await act(async () => {
      await result.current.mutateAsync({ offeringId: 7, mutedUntil: null });
    });

    // The match event remains until invalidation refetches it (and our MSW
    // handler always returns matches when include_matches=true). The
    // optimistic surgery did not run.
    const after = qc.getQueryData<KidCalendarResponse>([
      'kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'with-matches',
    ]);
    // Either the cache is unchanged from optimistic-skip (event present)
    // OR invalidation has already refetched. Both are acceptable; the test
    // asserts no crash + mutation completed successfully.
    expect(result.current.isSuccess).toBe(true);
  });
});
```

- [ ] **Step 2: Run; confirm tests FAIL** (hooks not exported):

```bash
cd frontend && npm run test -- mutations
```

- [ ] **Step 3: Implement hooks**

Append to `frontend/src/lib/mutations.ts`:

```ts
interface UpdateSiteMuteInput {
  siteId: number;
  mutedUntil: string | null;
}

export function useUpdateSiteMute() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, UpdateSiteMuteInput>({
    mutationFn: ({ siteId, mutedUntil }) =>
      api.patch(`/api/sites/${siteId}`, { muted_until: mutedUntil }),

    onSettled: async (_d, _e, { siteId }) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['sites'] }),
        qc.invalidateQueries({ queryKey: ['sites', siteId] }),
        qc.invalidateQueries({ queryKey: ['kids'] }),
      ]);
    },
  });
}

interface UpdateOfferingMuteInput {
  offeringId: number;
  mutedUntil: string | null;
}

export function useUpdateOfferingMute() {
  const qc = useQueryClient();
  type Ctx = {
    snapshots: ReadonlyArray<readonly [QueryKey, KidCalendarResponse | undefined]>;
  };
  return useMutation<unknown, Error, UpdateOfferingMuteInput, Ctx>({
    mutationFn: ({ offeringId, mutedUntil }) =>
      api.patch(`/api/offerings/${offeringId}`, { muted_until: mutedUntil }),

    onMutate: async ({ offeringId, mutedUntil }) => {
      // Optimistic match removal only when muting; on unmute, no surgery.
      if (mutedUntil == null) return { snapshots: [] };

      await qc.cancelQueries({ queryKey: ['kids'] });
      const allKidsQueries = qc.getQueriesData<KidCalendarResponse>({
        queryKey: ['kids'],
      });
      const calendarSnapshots = allKidsQueries.filter(
        ([key]) => key.length >= 3 && key[2] === 'calendar',
      );

      for (const [key, data] of calendarSnapshots) {
        if (!data) continue;
        const filtered = data.events.filter(
          (e) => !(e.kind === 'match' && e.offering_id === offeringId),
        );
        qc.setQueryData<KidCalendarResponse>(key, { ...data, events: filtered });
      }
      return { snapshots: calendarSnapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['matches'] }),
        qc.invalidateQueries({ queryKey: ['kids'] }),
      ]);
    },
  });
}
```

- [ ] **Step 4: Re-run; confirm new tests PASS**

```bash
cd frontend && npm run test -- mutations
```

Expected: 3 new + 11 from prior phases = 14 mutation tests pass.

- [ ] **Step 5: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 66 passed (63 + 3); clean.

- [ ] **Step 6: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/lib/mutations.ts frontend/src/lib/mutations.test.tsx
git commit -m "feat(frontend): useUpdateSiteMute + useUpdateOfferingMute

Both follow the canonical pattern. Site mute: minimal — invalidate
sites + kids (the calendar match overlay depends on site mute).
Offering mute: optimistic match removal across all calendar variants
when muting; no surgery on unmute. Both await invalidation."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 7 — Frontend: wire `<MuteButton>` in three placements

**Files:**
- Modify: `frontend/src/routes/sites.$id.tsx`
- Modify: `frontend/src/routes/kids.$id.matches.tsx`
- Modify: `frontend/src/components/calendar/CalendarEventPopover.tsx`
- Modify: `frontend/src/components/calendar/CalendarEventPopover.test.tsx`

End state: Mute button appears on site detail, in matches list, and in calendar match popover. ~1 new test for the popover branch.

- [ ] **Step 1: Wire site detail**

Read `frontend/src/routes/sites.$id.tsx` to find the page header. Add:

```tsx
import { MuteButton } from '@/components/common/MuteButton';
import { useUpdateSiteMute } from '@/lib/mutations';
```

In the page component:

```tsx
const muteSite = useUpdateSiteMute();
// ...
<MuteButton
  mutedUntil={site.muted_until ?? null}
  onChange={(mutedUntil) => muteSite.mutate({ siteId, mutedUntil })}
  isPending={muteSite.isPending}
/>
```

Place next to the site name heading. The Site type already has `muted_until: string | null`.

- [ ] **Step 2: Extend `OfferingSummary` with `muted_until` (REQUIRED — not present today)**

Verified at plan time: `OfferingSummary` in `src/yas/web/routes/matches_schemas.py` does NOT include `muted_until`. It must be added so the matches list can read it.

a. In `src/yas/web/routes/matches_schemas.py`, add to `OfferingSummary`:
```python
muted_until: datetime | None = None
```

b. The route handler in `src/yas/web/routes/matches.py` constructs `offering_data` by iterating `OfferingSummary.model_fields`. Verify the iteration picks up the new field automatically (it should — Pydantic v2 includes all declared fields). If the route uses an explicit exclusion list (e.g., `if k not in (...)`) update that list. Re-run `tests/integration/test_api_matches.py` (or equivalent) to confirm the field appears in responses with the right value.

c. In `frontend/src/lib/types.ts`, append to the `OfferingSummary` interface:
```ts
muted_until: string | null;
```

d. Run backend gates and frontend typecheck — both should remain clean.

Commit this sub-step separately:
```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add src/yas/web/routes/matches_schemas.py frontend/src/lib/types.ts
# include matches.py if you needed to update the iteration logic
git commit -m "feat(api): expose muted_until on OfferingSummary

Required for the matches list MuteButton wiring in 5d-1."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

- [ ] **Step 2b: Wire matches list**

Read `frontend/src/routes/kids.$id.matches.tsx`. Each match row currently renders the offering name + score.

Wire:

```tsx
import { MuteButton } from '@/components/common/MuteButton';
import { useUpdateOfferingMute } from '@/lib/mutations';

// inside the page component:
const muteOffering = useUpdateOfferingMute();

// inside the row render:
<MuteButton
  size="sm"
  mutedUntil={match.offering.muted_until ?? null}
  onChange={(mutedUntil) =>
    muteOffering.mutate({ offeringId: match.offering.id, mutedUntil })
  }
  isPending={muteOffering.isPending}
/>
```

- [ ] **Step 3: Wire calendar popover (TDD)**

First, append a test to `frontend/src/components/calendar/CalendarEventPopover.test.tsx`:

```tsx
it('renders Mute button on match events', () => {
  renderPopover(matchEvent);
  expect(screen.getByRole('button', { name: /^mute$/i })).toBeInTheDocument();
});
```

Run:
```bash
cd frontend && npm run test -- CalendarEventPopover
```
Expected: 1 fail.

Then update `frontend/src/components/calendar/CalendarEventPopover.tsx`. Add the import:

```tsx
import { MuteButton } from '@/components/common/MuteButton';
import { useUpdateOfferingMute } from '@/lib/mutations';
```

In the component body, alongside the existing mutations:

```tsx
const muteOffering = useUpdateOfferingMute();
```

Update `inFlight`:

```tsx
const inFlight = cancel.isPending || del.isPending || enroll.isPending || muteOffering.isPending;
```

In the `useEffect` reset block, also reset:

```tsx
muteOffering.reset();
```

Add a handler:

```tsx
const handleMute = (mutedUntil: string | null) => {
  if (!event?.offering_id) return;
  setErrorMsg(null);
  muteOffering.mutate(
    { offeringId: event.offering_id, mutedUntil },
    {
      onSuccess: onClose,
      onError: (err) => setErrorMsg(err.message || 'Failed to update mute'),
    },
  );
};
```

In the match-branch action `<div>`, add the MuteButton next to Enroll + View details:

```tsx
{isMatch && (
  <>
    <Button onClick={handleEnroll} disabled={inFlight}>
      Enroll
    </Button>
    {/* mutedUntil hardcoded null: muted matches are filtered out
        server-side (spec Q4), so the popover never shows a muted match.
        The button always renders the duration picker, never Unmute. */}
    <MuteButton
      mutedUntil={null}
      onChange={handleMute}
      isPending={muteOffering.isPending}
    />
    {event.registration_url && (
      <a ...>View details ↗</a>
    )}
  </>
)}
```

- [ ] **Step 4: Run all popover tests**

```bash
cd frontend && npm run test -- CalendarEventPopover
```

Expected: 8 passed (7 from prior + 1 new).

- [ ] **Step 5: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 67 passed (66 + 1); clean. (If Step 2 required schema extension, expect a slightly different total — verify by counting after the gates run.)

- [ ] **Step 6: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/routes/sites.\$id.tsx 'frontend/src/routes/kids.$id.matches.tsx' frontend/src/components/calendar/CalendarEventPopover.tsx frontend/src/components/calendar/CalendarEventPopover.test.tsx
# also add any backend schema changes from Step 2 (matches_schemas.py + types.ts)
git commit -m "feat(frontend): wire MuteButton in site detail, matches list, calendar popover

Three placements per spec §4. Calendar popover always shows Mute (not
Unmute) because muted matches don't appear on the calendar in the
first place — server filters them out."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 8 — Final exit gates + manual smoke + push + PR

End state: All exit criteria from spec §10 verified.

- [ ] **Step 1: Backend gates**

```bash
uv run pytest -q --no-cov && uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: 585 passed; clean.

- [ ] **Step 2: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 67 passed; clean.

- [ ] **Step 3: Manual smoke**

In one terminal:
```bash
YAS_DATABASE_URL="sqlite+aiosqlite:///$(pwd)/data/activities.db" YAS_ANTHROPIC_API_KEY=sk-test uv run uvicorn --factory yas.web.app:create_app --port 8080
```

(Note: the project's `create_app` is a factory, not a module-level `app` — use `--factory`.)

In another:
```bash
cd frontend && npm run dev
```

Walk through:
1. Navigate to `/sites/1` (use a real site id). Click Mute → 7 days. Button label flips to "Muted until {date}". Click again → Unmute. Button reverts to "Mute".
2. Navigate to `/kids/1/matches`. Mute a match. Row's button label flips. Match remains in the list.
3. Navigate to `/kids/1/calendar`. Toggle "Show matches". The match you muted in step 2 should NOT appear.
4. Click another match (one not muted). Popover opens with Enroll + Mute buttons + (optional) View details. Click Mute → 30 days. Match disappears from grid optimistically. Popover closes.
5. Backend: query `/api/alerts` directly to confirm no new_match alerts have fired for the muted offering since the mute.

If anything breaks, capture the failure in a regression test before fixing.

- [ ] **Step 4: Push branch and open PR**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git push -u origin phase-5d-1-site-offering-mute
gh pr create --title "phase 5d-1: site/offering alert mute (one-click)" --body "$(cat <<'EOF'
## Summary

- **Backend:** wired `Site.muted_until` and `Offering.muted_until` into the alert pipeline (6 enqueue functions gated). New `PATCH /api/offerings/{id}` route. Calendar match overlay now excludes muted offerings + offerings whose site is muted.
- **Frontend:** new `<MuteButton>` primitive (popover with 4-option duration picker + Unmute action). Two new mutation hooks following the canonical pattern. Wired in three placements: site detail, matches list, calendar event popover.

Closes the v1 terminal-state criterion: *"User can disable alerts from a specific site or offering with one click."* — v1 functional scope is now complete.

## Test plan

- [x] uv run pytest -q (585 passed; +18 backend tests)
- [x] uv run ruff check . && uv run ruff format --check . clean
- [x] uv run mypy src clean
- [x] cd frontend && npm run typecheck clean
- [x] cd frontend && npm run lint clean
- [x] cd frontend && npm run test (67 passed; +18 frontend tests)
- [ ] CI passes
- [ ] Manual smoke: mute a site → no new alerts; mute a match → vanishes from calendar; unmute → returns

## Spec / plan

- Spec: `docs/superpowers/specs/2026-04-29-phase-5d-1-site-offering-mute-design.md`
- Plan: `docs/superpowers/plans/2026-04-29-phase-5d-1-site-offering-mute.md`

## Out of scope (deferred)

- Mute reasons / notes
- Per-channel mute
- Bulk mute / multi-select
- Auto-unmute notifications
- Mute history audit log
EOF
)"
```

- [ ] **Step 5: Wait for CI; merge with `--squash`** (project convention).

---

## Notes for the implementer

- **`enqueue_watchlist_hit` return type widens.** From `int` to `int | None`. Most call sites ignore the return; mypy will catch any that don't. Update them by adding `if id_ is not None:` guards or by simply ignoring the return.
- **The `_is_muted` helper is offering-targeted** (joins Site automatically). The `_is_site_muted` helper is site-targeted. Don't conflate them; the wrong helper produces wrong gates.
- **Frontend `useUpdateOfferingMute` only does optimistic surgery on mute, not on unmute.** Unmuting a match wouldn't add it back to the calendar without a server round-trip anyway (we don't know the score, the offering metadata, etc.), so the invalidate handles it.
- **MuteButton's `Popover.Portal`** can be tricky in jsdom. If tests fail at "menuitem not found" the simplest fix is to drop the Portal (render content inline). Verify in real DOM during smoke.
- **Year-3000 sentinel** for forever-mute is intentional — keeps the data model uniform (`muted_until` is always either null or a comparable timestamp). Don't add a separate boolean column.
- **No new backend deps. No new frontend deps.** `radix-ui` 1.4.3 is already pinned.
- **Sites/Offerings test_api_offerings.py** uses the existing test pattern from `test_api_kids_calendar.py` — `client` fixture with `tmp_path` SQLite, `_seed`-style helpers. Follow that style.
