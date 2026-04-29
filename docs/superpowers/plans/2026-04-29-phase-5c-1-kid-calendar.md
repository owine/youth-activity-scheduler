# Phase 5c-1 — Per-kid Calendar View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a per-kid calendar view (`/kids/$id/calendar`) that renders enrollments + unavailability blocks on a week or month grid, with click-to-cancel/delete via popover. One new aggregated backend endpoint plus two mutation hooks reusing the canonical 5b-1b pattern.

**Architecture:** Backend grows a pure-function recurring-expansion helper (`src/yas/calendar/occurrences.py`), an aggregated read endpoint (`GET /api/kids/{id}/calendar`), and one `KidCalendarOut` Pydantic model. Frontend installs `react-big-calendar`, adds a route + `CalendarView` + `CalendarEventPopover`, two new TanStack Query mutations (`useCancelEnrollment`, `useDeleteUnavailability`) following 5b-1b's optimistic + rollback pattern. KidTabs gains a Calendar entry.

**Tech Stack:** SQLAlchemy 2.x async, FastAPI, Pydantic v2, pytest-asyncio, React 19, TanStack Query 5, TanStack Router, `react-big-calendar` (new), `date-fns`, MSW, Vitest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-04-29-phase-5c-1-kid-calendar-design.md`

**Project conventions to maintain:**
- Backend deps already pinned to exact patch in `pyproject.toml`. No new backend deps in this slice.
- Frontend deps pinned to exact patch in `frontend/package.json` (no `^`/`~`). Use `npm install --save-exact react-big-calendar@<latest-stable>` for the new dep.
- All commits signed via 1Password SSH agent. Set `SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"` before each `git commit` in fresh shells (subagents do NOT inherit it). After each commit verify with `git cat-file commit HEAD | grep -q '^gpgsig '`.
- Branch already created: `phase-5c-1-kid-calendar`. Do NOT commit to `main`.
- Backend gates: `uv run pytest -q --no-cov`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`.
- Frontend gates from `frontend/`: `npm run typecheck`, `npm run lint`, `npm run test`. (`format:check` has pre-existing failures — don't introduce new ones; only assert the files you touch are clean.)
- Backend baseline: 543 tests. Frontend baseline: 31 tests (8 files).
- Hand-maintained types in `frontend/src/lib/types.ts` mirror Pydantic schemas; keep them in sync.

---

## File Structure

**Create — backend:**
- `src/yas/calendar/__init__.py` — empty package marker.
- `src/yas/calendar/occurrences.py` — pure-function `expand_recurring` helper.
- `src/yas/web/routes/kid_calendar.py` — `GET /api/kids/{kid_id}/calendar` handler (separate from `kids.py` to keep that file from growing).
- `src/yas/web/routes/kid_calendar_schemas.py` — `KidCalendarOut`, `CalendarEventOut` Pydantic models.
- `tests/unit/test_calendar_occurrences.py` — pure-function tests for `expand_recurring`.
- `tests/integration/test_api_kids_calendar.py` — endpoint integration tests.

**Modify — backend:**
- `src/yas/web/app.py` — register the new router.

**Create — frontend:**
- `frontend/src/components/calendar/CalendarView.tsx` — wraps `react-big-calendar`.
- `frontend/src/components/calendar/CalendarEventPopover.tsx` — popover with action.
- `frontend/src/components/calendar/CalendarView.test.tsx`
- `frontend/src/components/calendar/CalendarEventPopover.test.tsx`
- `frontend/src/components/calendar/calendar-overrides.css` — minimal Tailwind v4-friendly overrides for `react-big-calendar`'s base styles.
- `frontend/src/routes/kids.$id.calendar.tsx` — TanStack Router route.

**Modify — frontend:**
- `frontend/package.json` — add `react-big-calendar` (exact patch).
- `frontend/src/lib/types.ts` — add `CalendarEvent`, `KidCalendarResponse`.
- `frontend/src/lib/queries.ts` — add `useKidCalendar`.
- `frontend/src/lib/mutations.ts` — add `useCancelEnrollment`, `useDeleteUnavailability`.
- `frontend/src/lib/mutations.test.tsx` — tests for the two new mutations.
- `frontend/src/test/handlers.ts` — MSW handlers for the new endpoint and mutation routes.
- `frontend/src/components/layout/KidTabs.tsx` — add Calendar tab.

---

## Task 1 — Pure-function recurring expansion (TDD, backend, isolated)

**Files:**
- Create: `src/yas/calendar/__init__.py`
- Create: `src/yas/calendar/occurrences.py`
- Create: `tests/unit/test_calendar_occurrences.py`

End state: `expand_recurring(...)` is implemented and exhaustively unit-tested. No HTTP, no DB. ~10 unit tests.

- [ ] **Step 1: Create the package marker**

```bash
mkdir -p src/yas/calendar
touch src/yas/calendar/__init__.py
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_calendar_occurrences.py`:

```python
"""Pure-function tests for the calendar recurring-expansion helper."""

from __future__ import annotations

from datetime import date, time

from yas.calendar.occurrences import Occurrence, expand_recurring


def _occ(d: tuple[int, int, int], start: tuple[int, int] | None, end: tuple[int, int] | None) -> Occurrence:
    return Occurrence(
        date=date(*d),
        time_start=time(*start) if start else None,
        time_end=time(*end) if end else None,
        all_day=start is None and end is None,
    )


def test_weekly_recurring_within_range_returns_correct_dates():
    # Mon 2026-04-27, Wed 2026-04-29, Fri 2026-05-01.
    out = list(
        expand_recurring(
            days_of_week=["mon", "wed", "fri"],
            time_start=time(16, 0),
            time_end=time(17, 0),
            date_start=None,
            date_end=None,
            range_from=date(2026, 4, 27),
            range_to=date(2026, 5, 4),
        )
    )
    assert out == [
        _occ((2026, 4, 27), (16, 0), (17, 0)),
        _occ((2026, 4, 29), (16, 0), (17, 0)),
        _occ((2026, 5, 1), (16, 0), (17, 0)),
    ]


def test_date_start_clips_lower_bound():
    out = list(
        expand_recurring(
            days_of_week=["tue"],
            time_start=time(10, 0),
            time_end=time(11, 0),
            date_start=date(2026, 4, 28),
            date_end=None,
            range_from=date(2026, 4, 21),
            range_to=date(2026, 5, 5),
        )
    )
    # Tue 2026-04-21 is excluded by date_start; Tue 2026-04-28 and 2026-05-05 (out of range) excluded.
    assert [o.date for o in out] == [date(2026, 4, 28)]


def test_date_end_clips_upper_bound_inclusive():
    out = list(
        expand_recurring(
            days_of_week=["tue"],
            time_start=time(10, 0),
            time_end=time(11, 0),
            date_start=None,
            date_end=date(2026, 4, 28),
            range_from=date(2026, 4, 21),
            range_to=date(2026, 5, 12),
        )
    )
    # date_end is inclusive; Tue 2026-04-21 and 2026-04-28 included; 2026-05-05 excluded.
    assert [o.date for o in out] == [date(2026, 4, 21), date(2026, 4, 28)]


def test_range_to_is_exclusive():
    out = list(
        expand_recurring(
            days_of_week=["mon"],
            time_start=time(9, 0),
            time_end=time(10, 0),
            date_start=None,
            date_end=None,
            range_from=date(2026, 4, 27),
            range_to=date(2026, 4, 27),  # empty half-open range
        )
    )
    assert out == []


def test_all_day_when_both_times_none():
    out = list(
        expand_recurring(
            days_of_week=["sat"],
            time_start=None,
            time_end=None,
            date_start=None,
            date_end=None,
            range_from=date(2026, 4, 25),
            range_to=date(2026, 4, 26),
        )
    )
    assert len(out) == 1
    assert out[0].all_day is True
    assert out[0].time_start is None
    assert out[0].time_end is None


def test_empty_days_of_week_returns_no_occurrences():
    out = list(
        expand_recurring(
            days_of_week=[],
            time_start=time(9, 0),
            time_end=time(10, 0),
            date_start=None,
            date_end=None,
            range_from=date(2026, 4, 27),
            range_to=date(2026, 5, 4),
        )
    )
    assert out == []


def test_days_of_week_case_insensitive():
    out = list(
        expand_recurring(
            days_of_week=["MON", "Wed"],
            time_start=time(9, 0),
            time_end=time(10, 0),
            date_start=None,
            date_end=None,
            range_from=date(2026, 4, 27),
            range_to=date(2026, 5, 4),
        )
    )
    assert [o.date for o in out] == [date(2026, 4, 27), date(2026, 4, 29)]


def test_source_outside_request_window_returns_no_occurrences():
    out = list(
        expand_recurring(
            days_of_week=["mon"],
            time_start=time(9, 0),
            time_end=time(10, 0),
            date_start=date(2026, 1, 1),
            date_end=date(2026, 1, 31),
            range_from=date(2026, 4, 27),
            range_to=date(2026, 5, 4),
        )
    )
    assert out == []


def test_malformed_partial_time_skipped():
    """time_start without time_end (or vice versa) is malformed; helper skips."""
    out = list(
        expand_recurring(
            days_of_week=["mon"],
            time_start=time(9, 0),
            time_end=None,
            date_start=None,
            date_end=None,
            range_from=date(2026, 4, 27),
            range_to=date(2026, 5, 4),
        )
    )
    assert out == []
```

- [ ] **Step 3: Run the tests; confirm they FAIL**

```bash
uv run pytest tests/unit/test_calendar_occurrences.py -q --no-cov
```

Expected: ImportError (module doesn't exist yet) → all 9 tests fail at collection.

- [ ] **Step 4: Implement `expand_recurring`**

Create `src/yas/calendar/occurrences.py`:

```python
"""Pure-function expansion of recurring weekly patterns into per-date occurrences.

No DB, no HTTP — call sites pass the row's pattern fields and a request window
and get back concrete occurrences within the intersection.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, time, timedelta

# Map weekday name → date.weekday() value (Mon=0..Sun=6).
_WEEKDAY: dict[str, int] = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


@dataclass(frozen=True, slots=True)
class Occurrence:
    """A concrete dated event derived from a recurring pattern."""

    date: date
    time_start: time | None
    time_end: time | None
    all_day: bool


def expand_recurring(
    *,
    days_of_week: list[str],
    time_start: time | None,
    time_end: time | None,
    date_start: date | None,
    date_end: date | None,
    range_from: date,
    range_to: date,
) -> Iterator[Occurrence]:
    """Yield occurrences for each weekday in `days_of_week` within the
    intersection of [range_from, range_to) (half-open) and
    [date_start, date_end] (closed, both endpoints inclusive when set).

    A row with both `time_start` and `time_end` set produces timed
    occurrences; both None produces all-day occurrences. A partial
    (one set, one None) is treated as malformed and yields nothing.
    """

    # Validate time pairing.
    if (time_start is None) != (time_end is None):
        return
    all_day = time_start is None and time_end is None

    # Normalize weekday names; silently skip unknown values.
    target_weekdays = {
        _WEEKDAY[name.lower()]
        for name in days_of_week
        if name.lower() in _WEEKDAY
    }
    if not target_weekdays:
        return

    # Clip the iteration range against the source's date_start/date_end.
    lo = range_from
    if date_start is not None and date_start > lo:
        lo = date_start
    hi = range_to  # exclusive
    if date_end is not None:
        # date_end is inclusive on the source row; convert to exclusive
        # by adding one day so the half-open `lo..hi` loop works uniformly.
        hi_from_source = date_end + timedelta(days=1)
        if hi_from_source < hi:
            hi = hi_from_source

    cursor = lo
    while cursor < hi:
        if cursor.weekday() in target_weekdays:
            yield Occurrence(
                date=cursor,
                time_start=time_start,
                time_end=time_end,
                all_day=all_day,
            )
        cursor += timedelta(days=1)
```

- [ ] **Step 5: Re-run tests; confirm all 9 PASS**

```bash
uv run pytest tests/unit/test_calendar_occurrences.py -q --no-cov
```

Expected: 9 passed.

- [ ] **Step 6: Run full backend gates**

```bash
uv run pytest -q --no-cov && uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: 552 passed (543 + 9); ruff/format/mypy clean.

- [ ] **Step 7: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add src/yas/calendar/__init__.py src/yas/calendar/occurrences.py tests/unit/test_calendar_occurrences.py
git commit -m "feat(calendar): expand_recurring helper for date-range occurrences

Pure-function expansion of (days_of_week + time_start/end + date bounds)
into concrete date occurrences within a half-open request window.
Foundation for the calendar route in the next task."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 2 — Calendar API endpoint (TDD, backend)

**Files:**
- Create: `src/yas/web/routes/kid_calendar_schemas.py`
- Create: `src/yas/web/routes/kid_calendar.py`
- Create: `tests/integration/test_api_kids_calendar.py`
- Modify: `src/yas/web/app.py`

End state: `GET /api/kids/{kid_id}/calendar?from=&to=` is wired and tested. ~8 integration tests covering the spec §2.1 boundary semantics.

- [ ] **Step 1: Write the schemas**

Create `src/yas/web/routes/kid_calendar_schemas.py`:

```python
"""Pydantic models for GET /api/kids/{kid_id}/calendar."""

from __future__ import annotations

from datetime import date, time
from typing import Literal

from pydantic import BaseModel, Field


class CalendarEventOut(BaseModel):
    id: str  # composite "kind:source-id:date" — see spec §2.1
    kind: Literal["enrollment", "unavailability"]
    date: date
    time_start: time | None = None
    time_end: time | None = None
    all_day: bool
    title: str
    # enrollment-only:
    enrollment_id: int | None = None
    offering_id: int | None = None
    location_id: int | None = None
    status: str | None = None
    # unavailability-only:
    block_id: int | None = None
    source: str | None = None
    from_enrollment_id: int | None = None


class KidCalendarOut(BaseModel):
    """Python's `from` keyword conflict resolved via Pydantic alias.

    `from_` is the Python attribute; FastAPI emits `from` on the wire
    because the route handler uses `response_model_by_alias=True`.
    """

    model_config = {"populate_by_name": True}

    kid_id: int
    from_: date = Field(alias="from")
    to: date
    events: list[CalendarEventOut]
```

- [ ] **Step 2: Write the failing integration tests**

Create `tests/integration/test_api_kids_calendar.py`:

```python
"""Integration tests for GET /api/kids/{kid_id}/calendar."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import (
    Enrollment,
    Kid,
    Offering,
    Page,
    Site,
    UnavailabilityBlock,
)
from yas.db.models._types import (
    EnrollmentStatus,
    OfferingStatus,
    UnavailabilitySource,
)
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


async def _seed_kid_with_enrollment(engine, *, kid_id=1, offering_id=1):
    async with session_scope(engine) as s:
        s.add(Kid(id=kid_id, name="Sam", dob=date(2019, 5, 1)))
        s.add(Site(id=1, name="X", base_url="https://x"))
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        s.add(
            Offering(
                id=offering_id,
                site_id=1,
                page_id=1,
                name="T-Ball",
                normalized_name="t-ball",
                days_of_week=["tue", "thu"],
                time_start=time(16, 0),
                time_end=time(17, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
            )
        )
        await s.flush()
        s.add(
            Enrollment(
                id=10,
                kid_id=kid_id,
                offering_id=offering_id,
                status=EnrollmentStatus.enrolled.value,
                enrolled_at=datetime.now(UTC),
            )
        )


@pytest.mark.asyncio
async def test_returns_404_for_unknown_kid(client):
    c, _ = client
    r = await c.get("/api/kids/9999/calendar?from=2026-04-27&to=2026-05-04")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_returns_422_when_from_not_before_to(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    r = await c.get("/api/kids/1/calendar?from=2026-05-04&to=2026-04-27")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_returns_422_when_range_exceeds_90_days(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    r = await c.get("/api/kids/1/calendar?from=2026-01-01&to=2026-04-15")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_returns_enrolled_offering_occurrences(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    assert r.status_code == 200
    body = r.json()
    assert body["kid_id"] == 1
    assert body["from"] == "2026-04-27"
    assert body["to"] == "2026-05-04"
    enrollment_events = [e for e in body["events"] if e["kind"] == "enrollment"]
    # Tue 2026-04-28 + Thu 2026-04-30; offering's date range is broader.
    assert len(enrollment_events) == 2
    dates = sorted(e["date"] for e in enrollment_events)
    assert dates == ["2026-04-28", "2026-04-30"]
    e = enrollment_events[0]
    assert e["enrollment_id"] == 10
    assert e["offering_id"] == 1
    assert e["status"] == "enrolled"
    assert e["title"] == "T-Ball"
    assert e["time_start"] == "16:00:00"
    assert e["all_day"] is False


@pytest.mark.asyncio
async def test_excludes_cancelled_enrollments(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    async with session_scope(engine) as s:
        from sqlalchemy import select
        e = (await s.execute(select(Enrollment).where(Enrollment.id == 10))).scalar_one()
        e.status = EnrollmentStatus.cancelled.value
    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    body = r.json()
    assert [e for e in body["events"] if e["kind"] == "enrollment"] == []


@pytest.mark.asyncio
async def test_returns_unavailability_blocks_with_from_enrollment_id(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    async with session_scope(engine) as s:
        s.add(
            UnavailabilityBlock(
                id=20,
                kid_id=1,
                source=UnavailabilitySource.school.value,
                label="School",
                days_of_week=["mon", "tue", "wed", "thu", "fri"],
                time_start=time(8, 30),
                time_end=time(15, 0),
                date_start=date(2026, 1, 1),
                date_end=date(2026, 6, 30),
                active=True,
            )
        )
        s.add(
            UnavailabilityBlock(
                id=21,
                kid_id=1,
                source=UnavailabilitySource.enrollment.value,
                label="T-Ball",
                days_of_week=["tue", "thu"],
                time_start=time(16, 0),
                time_end=time(17, 0),
                date_start=date(2026, 4, 1),
                date_end=date(2026, 6, 30),
                active=True,
                source_enrollment_id=10,
            )
        )
    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    body = r.json()
    school = [e for e in body["events"] if e["kind"] == "unavailability" and e["block_id"] == 20]
    assert len(school) == 5  # Mon..Fri
    assert school[0]["from_enrollment_id"] is None
    enrollment_block = [
        e for e in body["events"] if e["kind"] == "unavailability" and e["block_id"] == 21
    ]
    assert len(enrollment_block) == 2  # Tue, Thu
    assert enrollment_block[0]["from_enrollment_id"] == 10


@pytest.mark.asyncio
async def test_excludes_inactive_blocks(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    async with session_scope(engine) as s:
        s.add(
            UnavailabilityBlock(
                id=22,
                kid_id=1,
                source=UnavailabilitySource.manual.value,
                days_of_week=["wed"],
                time_start=time(13, 0),
                time_end=time(14, 0),
                date_start=date(2026, 4, 1),
                date_end=date(2026, 6, 30),
                active=False,
            )
        )
    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    body = r.json()
    assert all(e.get("block_id") != 22 for e in body["events"])


@pytest.mark.asyncio
async def test_excludes_other_kids_events(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    async with session_scope(engine) as s:
        s.add(Kid(id=2, name="Riley", dob=date(2017, 3, 1)))
        await s.flush()
        s.add(
            Enrollment(
                id=11,
                kid_id=2,
                offering_id=1,
                status=EnrollmentStatus.enrolled.value,
            )
        )
    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    body = r.json()
    assert all(e.get("enrollment_id") != 11 for e in body["events"])
```

- [ ] **Step 3: Run tests; confirm FAIL**

```bash
uv run pytest tests/integration/test_api_kids_calendar.py -q --no-cov
```

Expected: tests fail at route resolution (404 from FastAPI's not-found-route, not our 404) or at import.

- [ ] **Step 4: Implement the route**

Create `src/yas/web/routes/kid_calendar.py`:

```python
"""GET /api/kids/{kid_id}/calendar — aggregated per-kid event view."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.calendar.occurrences import expand_recurring
from yas.db.models import Enrollment, Kid, Offering, UnavailabilityBlock
from yas.db.models._types import EnrollmentStatus
from yas.db.session import session_scope
from yas.web.routes.kid_calendar_schemas import CalendarEventOut, KidCalendarOut

router = APIRouter(prefix="/api/kids", tags=["kids"])

_MAX_RANGE_DAYS = 90


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


@router.get("/{kid_id}/calendar", response_model=KidCalendarOut, response_model_by_alias=True)
async def get_kid_calendar(
    request: Request,
    kid_id: int,
    from_: Annotated[date, Query(alias="from")],
    to: Annotated[date, Query()],
) -> KidCalendarOut:
    if from_ >= to:
        raise HTTPException(status_code=422, detail="from must be before to")
    if (to - from_).days > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"range exceeds {_MAX_RANGE_DAYS}-day cap",
        )

    async with session_scope(_engine(request)) as s:
        kid = (await s.execute(select(Kid).where(Kid.id == kid_id))).scalar_one_or_none()
        if kid is None:
            raise HTTPException(status_code=404, detail=f"kid {kid_id} not found")

        events: list[CalendarEventOut] = []

        # 1. Active enrollments + offering join.
        enrollment_rows = (
            await s.execute(
                select(Enrollment, Offering)
                .join(Offering, Offering.id == Enrollment.offering_id)
                .where(Enrollment.kid_id == kid_id)
                .where(Enrollment.status == EnrollmentStatus.enrolled.value)
            )
        ).all()
        for enrollment, offering in enrollment_rows:
            for occ in expand_recurring(
                days_of_week=list(offering.days_of_week or []),
                time_start=offering.time_start,
                time_end=offering.time_end,
                date_start=offering.start_date,
                date_end=offering.end_date,
                range_from=from_,
                range_to=to,
            ):
                events.append(
                    CalendarEventOut(
                        id=f"enrollment:{enrollment.id}:{occ.date.isoformat()}",
                        kind="enrollment",
                        date=occ.date,
                        time_start=occ.time_start,
                        time_end=occ.time_end,
                        all_day=occ.all_day,
                        title=offering.name,
                        enrollment_id=enrollment.id,
                        offering_id=offering.id,
                        location_id=offering.location_id,
                        status=enrollment.status,
                    )
                )

        # 2. Active unavailability blocks.
        block_rows = (
            (
                await s.execute(
                    select(UnavailabilityBlock)
                    .where(UnavailabilityBlock.kid_id == kid_id)
                    .where(UnavailabilityBlock.active.is_(True))
                )
            )
            .scalars()
            .all()
        )
        for block in block_rows:
            for occ in expand_recurring(
                days_of_week=list(block.days_of_week or []),
                time_start=block.time_start,
                time_end=block.time_end,
                date_start=block.date_start,
                date_end=block.date_end,
                range_from=from_,
                range_to=to,
            ):
                events.append(
                    CalendarEventOut(
                        id=f"unavailability:{block.id}:{occ.date.isoformat()}",
                        kind="unavailability",
                        date=occ.date,
                        time_start=occ.time_start,
                        time_end=occ.time_end,
                        all_day=occ.all_day,
                        title=block.label or block.source,
                        block_id=block.id,
                        source=block.source,
                        from_enrollment_id=block.source_enrollment_id,
                    )
                )

        events.sort(key=lambda e: (e.date, e.time_start or ""))
        return KidCalendarOut(kid_id=kid_id, from_=from_, to=to, events=events)
```

- [ ] **Step 5: Register the router**

In `src/yas/web/app.py`, find where other routers are included (look for `app.include_router(...)` calls). Add:

```python
from yas.web.routes import kid_calendar  # add to imports

app.include_router(kid_calendar.router)
```

- [ ] **Step 6: Re-run integration tests; confirm all PASS**

```bash
uv run pytest tests/integration/test_api_kids_calendar.py -q --no-cov
```

Expected: 8 passed.

- [ ] **Step 7: Run full backend gates**

```bash
uv run pytest -q --no-cov && uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: 560 passed (552 + 8); ruff/format/mypy clean.

- [ ] **Step 8: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add src/yas/web/routes/kid_calendar.py src/yas/web/routes/kid_calendar_schemas.py tests/integration/test_api_kids_calendar.py src/yas/web/app.py
git commit -m "feat(api): GET /api/kids/{kid_id}/calendar

Aggregated per-kid view of enrollment occurrences (active enrollments
+ joined offering) and unavailability blocks within a half-open
[from, to) date range. Caps range at 90 days defensively.

Reuses the expand_recurring helper from the previous commit."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 3 — Frontend types + query hook + MSW handlers (no UI yet)

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/queries.ts`
- Modify: `frontend/src/test/handlers.ts`

End state: TypeScript types match the backend response, `useKidCalendar` exists and is tested via MSW. No visible UI yet.

- [ ] **Step 1: Add frontend types**

In `frontend/src/lib/types.ts`, append:

```ts
export type CalendarEventKind = 'enrollment' | 'unavailability';

export interface CalendarEvent {
  id: string;            // composite "kind:source-id:date"
  kind: CalendarEventKind;
  date: string;          // YYYY-MM-DD
  time_start: string | null;   // "HH:MM:SS" or null for all-day
  time_end: string | null;
  all_day: boolean;
  title: string;
  // enrollment-only:
  enrollment_id?: number | null;
  offering_id?: number | null;
  location_id?: number | null;
  status?: string | null;
  // unavailability-only:
  block_id?: number | null;
  source?: string | null;
  from_enrollment_id?: number | null;
}

export interface KidCalendarResponse {
  kid_id: number;
  from: string;  // YYYY-MM-DD
  to: string;
  events: CalendarEvent[];
}
```

- [ ] **Step 2: Add `useKidCalendar` to `lib/queries.ts`**

Append:

```ts
export function useKidCalendar({
  kidId,
  from,
  to,
}: {
  kidId: number;
  from: string;
  to: string;
}) {
  return useQuery({
    queryKey: ['kids', kidId, 'calendar', from, to],
    queryFn: () =>
      api.get<KidCalendarResponse>(
        `/api/kids/${kidId}/calendar?from=${from}&to=${to}`,
      ),
    enabled: Number.isFinite(kidId) && !!from && !!to,
  });
}
```

(Add `KidCalendarResponse` to the import block at the top of the file.)

- [ ] **Step 3: Add MSW handlers**

In `frontend/src/test/handlers.ts`, append to the `handlers` array:

```ts
http.get('/api/kids/:id/calendar', ({ params, request }) => {
  const url = new URL(request.url);
  return HttpResponse.json({
    kid_id: Number(params.id),
    from: url.searchParams.get('from'),
    to: url.searchParams.get('to'),
    events: [],
  });
}),
http.patch('/api/enrollments/:id', async ({ params, request }) => {
  const body = (await request.json()) as { status?: string };
  return HttpResponse.json({
    id: Number(params.id),
    kid_id: 1,
    offering_id: 1,
    status: body.status ?? 'cancelled',
    enrolled_at: null,
    notes: null,
    created_at: '2026-04-29T12:00:00Z',
  });
}),
http.delete('/api/unavailability/:id', () => new HttpResponse(null, { status: 204 })),
```

- [ ] **Step 4: Run frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: all clean (no new tests yet, but types compile and existing tests pass).

- [ ] **Step 5: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/lib/types.ts frontend/src/lib/queries.ts frontend/src/test/handlers.ts
git commit -m "feat(frontend): types + useKidCalendar hook + MSW handlers

Mirrors the backend KidCalendarOut shape. Adds MSW handlers for the
new GET endpoint and the two existing routes the calendar will
mutate (PATCH /api/enrollments/{id}, DELETE /api/unavailability/{id})
so subsequent tasks can test against them."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 4 — Mutation hooks: `useCancelEnrollment` + `useDeleteUnavailability` (TDD)

**Files:**
- Modify: `frontend/src/lib/mutations.ts`
- Modify: `frontend/src/lib/mutations.test.tsx`

End state: Two new mutation hooks following the canonical 5b-1b shape. ~5 new tests covering optimistic remove + rollback for both.

- [ ] **Step 1: Append failing tests to `mutations.test.tsx`**

Append at the bottom of `frontend/src/lib/mutations.test.tsx`:

```tsx
import { useCancelEnrollment, useDeleteUnavailability } from './mutations';
import type { KidCalendarResponse } from './types';

const seedCal = (events: KidCalendarResponse['events']): KidCalendarResponse => ({
  kid_id: 1,
  from: '2026-04-27',
  to: '2026-05-04',
  events,
});

describe('useCancelEnrollment', () => {
  it('removes all enrollment occurrences and linked-block occurrences for that enrollment', async () => {
    const qc = new QueryClient();
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04'],
      seedCal([
        {
          id: 'enrollment:42:2026-04-28',
          kind: 'enrollment',
          date: '2026-04-28',
          time_start: '16:00:00',
          time_end: '17:00:00',
          all_day: false,
          title: 'T-Ball',
          enrollment_id: 42,
          offering_id: 7,
          status: 'enrolled',
        },
        {
          id: 'unavailability:21:2026-04-28',
          kind: 'unavailability',
          date: '2026-04-28',
          time_start: '16:00:00',
          time_end: '17:00:00',
          all_day: false,
          title: 'T-Ball',
          block_id: 21,
          source: 'enrollment',
          from_enrollment_id: 42,
        },
        {
          id: 'unavailability:20:2026-04-28',
          kind: 'unavailability',
          date: '2026-04-28',
          time_start: '08:30:00',
          time_end: '15:00:00',
          all_day: false,
          title: 'School',
          block_id: 20,
          source: 'school',
          from_enrollment_id: null,
        },
      ]),
    );

    const { result } = renderHook(() => useCancelEnrollment(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, enrollmentId: 42 });
    });

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids', 1, 'calendar', '2026-04-27', '2026-05-04',
    ]);
    // Only the school block remains.
    expect(after?.events).toHaveLength(1);
    expect(after?.events[0].block_id).toBe(20);
  });

  it('rolls back on server error', async () => {
    server.use(
      http.patch('/api/enrollments/:id', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const original = seedCal([
      {
        id: 'enrollment:42:2026-04-28',
        kind: 'enrollment',
        date: '2026-04-28',
        time_start: '16:00:00',
        time_end: '17:00:00',
        all_day: false,
        title: 'T-Ball',
        enrollment_id: 42,
        offering_id: 7,
        status: 'enrolled',
      },
    ]);
    qc.setQueryData(['kids', 1, 'calendar', '2026-04-27', '2026-05-04'], original);

    const { result } = renderHook(() => useCancelEnrollment(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current
        .mutateAsync({ kidId: 1, enrollmentId: 42 })
        .catch(() => {});
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids', 1, 'calendar', '2026-04-27', '2026-05-04',
    ]);
    expect(after?.events).toHaveLength(1);
    expect(after?.events[0].enrollment_id).toBe(42);
  });
});

describe('useDeleteUnavailability', () => {
  it('removes the matching unavailability event from cache', async () => {
    const qc = new QueryClient();
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04'],
      seedCal([
        {
          id: 'unavailability:20:2026-04-28',
          kind: 'unavailability',
          date: '2026-04-28',
          time_start: '08:30:00',
          time_end: '15:00:00',
          all_day: false,
          title: 'School',
          block_id: 20,
          source: 'school',
          from_enrollment_id: null,
        },
      ]),
    );

    const { result } = renderHook(() => useDeleteUnavailability(), {
      wrapper: makeWrapper(qc),
    });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, blockId: 20 });
    });

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids', 1, 'calendar', '2026-04-27', '2026-05-04',
    ]);
    expect(after?.events).toEqual([]);
  });

  it('rolls back on server error', async () => {
    server.use(
      http.delete('/api/unavailability/:id', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const original = seedCal([
      {
        id: 'unavailability:20:2026-04-28',
        kind: 'unavailability',
        date: '2026-04-28',
        time_start: '08:30:00',
        time_end: '15:00:00',
        all_day: false,
        title: 'School',
        block_id: 20,
        source: 'school',
        from_enrollment_id: null,
      },
    ]);
    qc.setQueryData(['kids', 1, 'calendar', '2026-04-27', '2026-05-04'], original);

    const { result } = renderHook(() => useDeleteUnavailability(), {
      wrapper: makeWrapper(qc),
    });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, blockId: 20 }).catch(() => {});
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids', 1, 'calendar', '2026-04-27', '2026-05-04',
    ]);
    expect(after?.events).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run tests; confirm FAIL**

```bash
cd frontend && npm run test -- mutations
```

Expected: hooks not exported yet → fail.

- [ ] **Step 3: Implement the two hooks**

Append to `frontend/src/lib/mutations.ts`:

```ts
import type { KidCalendarResponse } from './types';

interface CancelEnrollmentInput {
  kidId: number;
  enrollmentId: number;
}

export function useCancelEnrollment() {
  const qc = useQueryClient();
  type Ctx = {
    snapshots: ReadonlyArray<readonly [QueryKey, KidCalendarResponse | undefined]>;
  };
  return useMutation<unknown, Error, CancelEnrollmentInput, Ctx>({
    mutationFn: ({ enrollmentId }) =>
      api.patch(`/api/enrollments/${enrollmentId}`, { status: 'cancelled' }),

    onMutate: async ({ kidId, enrollmentId }) => {
      await qc.cancelQueries({ queryKey: ['kids', kidId, 'calendar'] });
      const snapshots = qc.getQueriesData<KidCalendarResponse>({
        queryKey: ['kids', kidId, 'calendar'],
      });

      for (const [key, data] of snapshots) {
        if (!data) continue;
        const filtered = data.events.filter(
          (e) =>
            e.enrollment_id !== enrollmentId &&
            e.from_enrollment_id !== enrollmentId,
        );
        qc.setQueryData<KidCalendarResponse>(key, { ...data, events: filtered });
      }
      return { snapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: async (_data, _err, { kidId }) => {
      await qc.invalidateQueries({ queryKey: ['kids', kidId, 'calendar'] });
    },
  });
}

interface DeleteUnavailabilityInput {
  kidId: number;
  blockId: number;
}

export function useDeleteUnavailability() {
  const qc = useQueryClient();
  type Ctx = {
    snapshots: ReadonlyArray<readonly [QueryKey, KidCalendarResponse | undefined]>;
  };
  return useMutation<unknown, Error, DeleteUnavailabilityInput, Ctx>({
    mutationFn: ({ blockId }) => api.delete(`/api/unavailability/${blockId}`),

    onMutate: async ({ kidId, blockId }) => {
      await qc.cancelQueries({ queryKey: ['kids', kidId, 'calendar'] });
      const snapshots = qc.getQueriesData<KidCalendarResponse>({
        queryKey: ['kids', kidId, 'calendar'],
      });

      for (const [key, data] of snapshots) {
        if (!data) continue;
        const filtered = data.events.filter((e) => e.block_id !== blockId);
        qc.setQueryData<KidCalendarResponse>(key, { ...data, events: filtered });
      }
      return { snapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: async (_data, _err, { kidId }) => {
      await qc.invalidateQueries({ queryKey: ['kids', kidId, 'calendar'] });
    },
  });
}
```

- [ ] **Step 4: Add `patch` and `delete` to `api`**

In `frontend/src/lib/api.ts`, extend the `api` object:

```ts
export const api = {
  get<T>(path: string) {
    return request<T>(path);
  },
  post<T>(path: string, body?: unknown) {
    return request<T>(path, {
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },
  patch<T>(path: string, body?: unknown) {
    return request<T>(path, {
      method: 'PATCH',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },
  delete<T = void>(path: string) {
    return request<T>(path, { method: 'DELETE' });
  },
};
```

**Required: handle 204 in `request()`.** The existing `request<T>()` calls `r.json()` unconditionally and will throw on `DELETE /api/unavailability/{id}`'s empty 204 response. Add this guard inside `request()` before the JSON parse:

```ts
if (r.status === 204) {
  return undefined as T;
}
return r.json() as Promise<T>;
```

Verify by reading `frontend/src/lib/api.ts` first; the existing fn body ends with `return r.json() as Promise<T>;` and the guard goes immediately above that line.

- [ ] **Step 5: Re-run all mutation tests; confirm they pass**

```bash
cd frontend && npm run test -- mutations
```

Expected: 9 passed (5 from 5b-1b + 4 new).

- [ ] **Step 6: Run all frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 35 passed total (31 + 4).

- [ ] **Step 7: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/lib/mutations.ts frontend/src/lib/mutations.test.tsx frontend/src/lib/api.ts
git commit -m "feat(frontend): useCancelEnrollment + useDeleteUnavailability

Both follow the canonical 5b-1b mutation pattern (cancelQueries +
snapshot + optimistic setQueryData + onError rollback + awaited
invalidate). useCancelEnrollment also strips linked-block events
from the cache so the UI doesn't briefly show an orphaned block.

Adds api.patch / api.delete helpers (delete handles 204 responses)."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 5 — `react-big-calendar` install + `CalendarView` component (TDD)

**Files:**
- Modify: `frontend/package.json` (and lockfile)
- Create: `frontend/src/components/calendar/CalendarView.tsx`
- Create: `frontend/src/components/calendar/CalendarView.test.tsx`
- Create: `frontend/src/components/calendar/calendar-overrides.css`

End state: `<CalendarView>` renders events on week or month grid, calls `onSelectEvent` on click. ~3 tests.

- [ ] **Step 1: Install the dependency**

```bash
cd frontend && npm install --save-exact react-big-calendar @types/react-big-calendar
```

Verify the version in `package.json` is pinned (no `^`/`~`).

- [ ] **Step 2: Write failing tests**

Create `frontend/src/components/calendar/CalendarView.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CalendarView } from './CalendarView';
import type { CalendarEvent } from '@/lib/types';

const events: CalendarEvent[] = [
  {
    id: 'enrollment:1:2026-04-29',
    kind: 'enrollment',
    date: '2026-04-29',
    time_start: '16:00:00',
    time_end: '17:00:00',
    all_day: false,
    title: 'T-Ball',
    enrollment_id: 1,
    offering_id: 7,
    status: 'enrolled',
  },
];

describe('CalendarView', () => {
  it('renders an event title in the grid', () => {
    render(
      <CalendarView
        events={events}
        view="week"
        onView={vi.fn()}
        date={new Date('2026-04-29T12:00:00Z')}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
      />,
    );
    expect(screen.getByText(/T-Ball/i)).toBeInTheDocument();
  });

  it('calls onSelectEvent when an event is clicked', async () => {
    const onSelectEvent = vi.fn();
    render(
      <CalendarView
        events={events}
        view="week"
        onView={vi.fn()}
        date={new Date('2026-04-29T12:00:00Z')}
        onNavigate={vi.fn()}
        onSelectEvent={onSelectEvent}
      />,
    );
    await userEvent.click(screen.getByText(/T-Ball/i));
    expect(onSelectEvent).toHaveBeenCalledTimes(1);
    expect(onSelectEvent.mock.calls[0][0].id).toBe('enrollment:1:2026-04-29');
  });

  it('renders the same events in month view', () => {
    render(
      <CalendarView
        events={events}
        view="month"
        onView={vi.fn()}
        date={new Date('2026-04-29T12:00:00Z')}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
      />,
    );
    expect(screen.getByText(/T-Ball/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run; confirm FAIL**

```bash
npm run test -- CalendarView
```

Expected: component doesn't exist.

- [ ] **Step 4: Implement `CalendarView.tsx`**

Create `frontend/src/components/calendar/CalendarView.tsx`:

```tsx
import { Calendar, dateFnsLocalizer, Views, type View } from 'react-big-calendar';
import { format, parse, startOfWeek, getDay } from 'date-fns';
import { enUS } from 'date-fns/locale';
import type { CalendarEvent } from '@/lib/types';
import 'react-big-calendar/lib/css/react-big-calendar.css';
import './calendar-overrides.css';

const locales = { 'en-US': enUS };
const localizer = dateFnsLocalizer({ format, parse, startOfWeek, getDay, locales });

interface RbcEvent {
  title: string;
  start: Date;
  end: Date;
  allDay: boolean;
  resource: CalendarEvent;
}

function toRbc(e: CalendarEvent): RbcEvent {
  // Build a Date from "YYYY-MM-DD" + "HH:MM:SS". For all-day, span the whole day.
  const [y, m, d] = e.date.split('-').map(Number);
  if (e.all_day) {
    const start = new Date(y, m - 1, d, 0, 0, 0);
    const end = new Date(y, m - 1, d + 1, 0, 0, 0);
    return { title: e.title, start, end, allDay: true, resource: e };
  }
  const [sh, sm] = (e.time_start ?? '00:00:00').split(':').map(Number);
  const [eh, em] = (e.time_end ?? '23:59:59').split(':').map(Number);
  const start = new Date(y, m - 1, d, sh, sm, 0);
  const end = new Date(y, m - 1, d, eh, em, 0);
  return { title: e.title, start, end, allDay: false, resource: e };
}

export function CalendarView({
  events,
  view,
  onView,
  date,
  onNavigate,
  onSelectEvent,
}: {
  events: CalendarEvent[];
  view: View;
  onView: (v: View) => void;
  date: Date;
  onNavigate: (d: Date) => void;
  onSelectEvent: (e: CalendarEvent) => void;
}) {
  const rbcEvents = events.map(toRbc);
  return (
    <div className="h-[70vh]">
      <Calendar
        localizer={localizer}
        events={rbcEvents}
        views={[Views.WEEK, Views.MONTH]}
        view={view}
        onView={onView}
        date={date}
        onNavigate={onNavigate}
        min={new Date(0, 0, 0, 6, 0, 0)}
        max={new Date(0, 0, 0, 22, 0, 0)}
        onSelectEvent={(rbc) => onSelectEvent((rbc as RbcEvent).resource)}
        eventPropGetter={(rbc) => ({
          className:
            (rbc as RbcEvent).resource.kind === 'enrollment'
              ? 'rbc-event-enrollment'
              : 'rbc-event-unavailability',
        })}
      />
    </div>
  );
}
```

- [ ] **Step 5: Add the CSS overrides**

Create `frontend/src/components/calendar/calendar-overrides.css`:

```css
/* Minimal Tailwind-friendly overrides for react-big-calendar's base styles. */

.rbc-event-enrollment {
  background-color: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  border: none;
}

.rbc-event-unavailability {
  background-color: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
  border: none;
}

.rbc-today {
  background-color: hsl(var(--accent));
}

.rbc-toolbar button {
  color: hsl(var(--foreground));
}

.rbc-toolbar button.rbc-active {
  background-color: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
}
```

If during implementation the rendered calendar still has visually broken styling (e.g., header text invisible against the theme), append targeted fixes here. Don't try to override more than necessary.

- [ ] **Step 6: Re-run; confirm 3 PASS**

```bash
npm run test -- CalendarView
```

Expected: 3 passed.

- [ ] **Step 7: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 38 passed (35 + 3); typecheck clean, lint clean.

- [ ] **Step 8: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/package.json frontend/package-lock.json frontend/src/components/calendar/CalendarView.tsx frontend/src/components/calendar/CalendarView.test.tsx frontend/src/components/calendar/calendar-overrides.css
git commit -m "feat(frontend): CalendarView wrapping react-big-calendar

Week + month views with controlled view/date, fixed 6:00–22:00 time
range, event class dispatch by kind. Maps our flat CalendarEvent
shape to react-big-calendar's {start,end,allDay,resource} model."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 6 — `CalendarEventPopover` + mutation wiring (TDD)

**Files:**
- Create: `frontend/src/components/calendar/CalendarEventPopover.tsx`
- Create: `frontend/src/components/calendar/CalendarEventPopover.test.tsx`

End state: Popover renders enrollment or unavailability details, dispatches the right mutation, suppresses delete on enrollment-linked blocks. ~4 tests.

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/calendar/CalendarEventPopover.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CalendarEventPopover } from './CalendarEventPopover';
import type { CalendarEvent } from '@/lib/types';

const enrollment: CalendarEvent = {
  id: 'enrollment:42:2026-04-29',
  kind: 'enrollment',
  date: '2026-04-29',
  time_start: '16:00:00',
  time_end: '17:00:00',
  all_day: false,
  title: 'T-Ball',
  enrollment_id: 42,
  offering_id: 7,
  status: 'enrolled',
};

const enrollmentLinkedBlock: CalendarEvent = {
  id: 'unavailability:21:2026-04-29',
  kind: 'unavailability',
  date: '2026-04-29',
  time_start: '16:00:00',
  time_end: '17:00:00',
  all_day: false,
  title: 'T-Ball',
  block_id: 21,
  source: 'enrollment',
  from_enrollment_id: 42,
};

const standaloneBlock: CalendarEvent = {
  id: 'unavailability:20:2026-04-29',
  kind: 'unavailability',
  date: '2026-04-29',
  time_start: '08:30:00',
  time_end: '15:00:00',
  all_day: false,
  title: 'School',
  block_id: 20,
  source: 'school',
  from_enrollment_id: null,
};

function renderPopover(event: CalendarEvent | null, onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CalendarEventPopover kidId={1} event={event} open={event !== null} onClose={onClose} />
    </QueryClientProvider>,
  );
}

describe('CalendarEventPopover', () => {
  it('renders enrollment details + Cancel enrollment button', () => {
    renderPopover(enrollment);
    expect(screen.getByText(/T-Ball/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel enrollment/i })).toBeInTheDocument();
  });

  it('renders standalone block details + Delete block button', () => {
    renderPopover(standaloneBlock);
    expect(screen.getByText(/School/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /delete block/i })).toBeInTheDocument();
  });

  it('suppresses Delete on enrollment-linked blocks and shows hint', () => {
    renderPopover(enrollmentLinkedBlock);
    expect(screen.queryByRole('button', { name: /delete block/i })).not.toBeInTheDocument();
    expect(screen.getByText(/cancel the enrollment/i)).toBeInTheDocument();
  });

  it('calls onClose after a successful Cancel enrollment', async () => {
    const onClose = vi.fn();
    renderPopover(enrollment, onClose);
    await userEvent.click(screen.getByRole('button', { name: /cancel enrollment/i }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
```

- [ ] **Step 2: Run; confirm FAIL**

```bash
npm run test -- CalendarEventPopover
```

- [ ] **Step 3: Implement the popover**

Create `frontend/src/components/calendar/CalendarEventPopover.tsx`:

```tsx
import { useState, useEffect } from 'react';
import { Popover, PopoverContent } from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import type { CalendarEvent } from '@/lib/types';
import { useCancelEnrollment, useDeleteUnavailability } from '@/lib/mutations';

export function CalendarEventPopover({
  kidId,
  event,
  open,
  onClose,
}: {
  kidId: number;
  event: CalendarEvent | null;
  open: boolean;
  onClose: () => void;
}) {
  const cancel = useCancelEnrollment();
  const del = useDeleteUnavailability();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const inFlight = cancel.isPending || del.isPending;

  useEffect(() => {
    setErrorMsg(null);
    cancel.reset();
    del.reset();
    // event identity is the only stable signal we're showing a different event;
    // mutation refs are recreated each render so they cannot be in deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event?.id]);

  if (!event) return null;

  const handleCancel = () => {
    setErrorMsg(null);
    cancel.mutate(
      { kidId, enrollmentId: event.enrollment_id! },
      {
        onSuccess: onClose,
        onError: (err) => setErrorMsg(err.message || 'Failed to cancel enrollment'),
      },
    );
  };

  const handleDelete = () => {
    setErrorMsg(null);
    del.mutate(
      { kidId, blockId: event.block_id! },
      {
        onSuccess: onClose,
        onError: (err) => setErrorMsg(err.message || 'Failed to delete block'),
      },
    );
  };

  const isEnrollment = event.kind === 'enrollment';
  const isLinkedBlock =
    event.kind === 'unavailability' && event.from_enrollment_id != null;

  return (
    <Popover open={open} onOpenChange={(o) => !o && !inFlight && onClose()}>
      <PopoverContent className="w-80 space-y-3">
        <div>
          <div className="font-medium">{event.title}</div>
          <div className="text-xs text-muted-foreground">
            {event.all_day
              ? 'All day'
              : `${event.time_start?.slice(0, 5)}–${event.time_end?.slice(0, 5)}`}
          </div>
          {event.kind === 'unavailability' && (
            <div className="text-xs text-muted-foreground">Source: {event.source}</div>
          )}
        </div>

        {errorMsg && <ErrorBanner message={errorMsg} />}

        {isEnrollment && (
          <Button onClick={handleCancel} disabled={inFlight} variant="destructive">
            Cancel enrollment
          </Button>
        )}
        {!isEnrollment && !isLinkedBlock && (
          <Button onClick={handleDelete} disabled={inFlight} variant="destructive">
            Delete block
          </Button>
        )}
        {isLinkedBlock && (
          <p className="text-xs text-muted-foreground">
            This block was created by your enrollment. Cancel the enrollment to remove it.
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}
```

(Verify `@/components/ui/popover` exists; if not, run `npx shadcn@latest add popover` from `frontend/`. Most shadcn projects include it; check `frontend/src/components/ui/` first.)

- [ ] **Step 4: Re-run; confirm PASS**

```bash
npm run test -- CalendarEventPopover
```

Expected: 4 passed.

- [ ] **Step 5: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 42 passed (38 + 4).

- [ ] **Step 6: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/components/calendar/CalendarEventPopover.tsx frontend/src/components/calendar/CalendarEventPopover.test.tsx
git commit -m "feat(frontend): CalendarEventPopover with cancel/delete actions

Click an enrollment → Cancel enrollment; click a standalone
unavailability block → Delete block; click an enrollment-linked
block → no destructive action, helper text directs to cancel the
enrollment instead. Inline ErrorBanner on mutation failure."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 7 — Route wiring + KidTabs entry

**Files:**
- Create: `frontend/src/routes/kids.$id.calendar.tsx`
- Modify: `frontend/src/components/layout/KidTabs.tsx`

End state: `/kids/$id/calendar` renders. KidTabs has a Calendar tab.

- [ ] **Step 1: Add the Calendar tab to KidTabs**

In `frontend/src/components/layout/KidTabs.tsx`, extend the `tabs` array:

```ts
const tabs = [
  { to: '/kids/$id/matches', label: 'Matches' },
  { to: '/kids/$id/watchlist', label: 'Watchlist' },
  { to: '/kids/$id/calendar', label: 'Calendar' },
] as const;
```

- [ ] **Step 2: Implement the route**

Create `frontend/src/routes/kids.$id.calendar.tsx`:

```tsx
import { useState, useMemo } from 'react';
import { createFileRoute } from '@tanstack/react-router';
import { startOfWeek, addDays, startOfMonth, endOfMonth, format } from 'date-fns';
import type { View } from 'react-big-calendar';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { useKid, useKidCalendar } from '@/lib/queries';
import { KidTabs } from '@/components/layout/KidTabs';
import { CalendarView } from '@/components/calendar/CalendarView';
import { CalendarEventPopover } from '@/components/calendar/CalendarEventPopover';
import type { CalendarEvent } from '@/lib/types';

export const Route = createFileRoute('/kids/$id/calendar')({ component: KidCalendarPage });

const BUFFER_DAYS = 3;

function rangeFor(view: View, cursor: Date): { from: string; to: string } {
  if (view === 'month') {
    const monthStart = startOfMonth(cursor);
    const monthEnd = endOfMonth(cursor);
    const weekStart = startOfWeek(monthStart, { weekStartsOn: 0 });
    return {
      from: format(addDays(weekStart, -BUFFER_DAYS), 'yyyy-MM-dd'),
      to: format(addDays(monthEnd, 7 + BUFFER_DAYS), 'yyyy-MM-dd'),
    };
  }
  // week
  const weekStart = startOfWeek(cursor, { weekStartsOn: 0 });
  return {
    from: format(addDays(weekStart, -BUFFER_DAYS), 'yyyy-MM-dd'),
    to: format(addDays(weekStart, 7 + BUFFER_DAYS), 'yyyy-MM-dd'),
  };
}

function KidCalendarPage() {
  const { id } = Route.useParams();
  const kidId = Number(id);
  const kid = useKid(kidId);

  const [view, setView] = useState<View>('week');
  const [cursor, setCursor] = useState<Date>(new Date());
  const { from, to } = useMemo(() => rangeFor(view, cursor), [view, cursor]);

  const calendar = useKidCalendar({ kidId, from, to });
  const [selected, setSelected] = useState<CalendarEvent | null>(null);

  if (kid.isLoading) return <Skeleton className="h-32 w-full" />;
  if (kid.isError) {
    return <ErrorBanner message={(kid.error as Error).message} onRetry={() => kid.refetch()} />;
  }
  if (!kid.data) return null;

  return (
    <div>
      <h1 className="text-xl font-semibold mb-2">{kid.data.name}'s calendar</h1>
      <KidTabs kidId={kidId} />
      {calendar.isError && (
        <ErrorBanner
          message={(calendar.error as Error).message}
          onRetry={() => calendar.refetch()}
        />
      )}
      <CalendarView
        events={calendar.data?.events ?? []}
        view={view}
        onView={setView}
        date={cursor}
        onNavigate={setCursor}
        onSelectEvent={setSelected}
      />
      <CalendarEventPopover
        kidId={kidId}
        event={selected}
        open={selected !== null}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}
```

Note on `routeTree.gen.ts`: TanStack Router's plugin regenerates this file when the dev server runs or via `npm run build`. Check `frontend/vite.config.ts` for the `tanstackRouterVite` plugin — it generates the route tree automatically. After creating the file, run `npm run build` once to trigger regeneration if not running the dev server.

- [ ] **Step 3: Run frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: still 42 passed (no new tests, but typecheck must succeed against the new route — including its codegen).

If typecheck fails complaining about `'/kids/$id/calendar'` not being a known route, regenerate manually:

```bash
npm run build  # triggers TanStack Router codegen
# then re-run typecheck
```

- [ ] **Step 4: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/routes/kids.\$id.calendar.tsx frontend/src/routeTree.gen.ts frontend/src/components/layout/KidTabs.tsx
git commit -m "feat(frontend): /kids/\$id/calendar route + KidTabs entry

Route owns view (week/month) and cursor date as local state, derives
from/to with a small lookback buffer, and feeds CalendarView +
CalendarEventPopover. KidTabs gains the Calendar tab."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 8 — Final exit gates + manual smoke + push + PR

End state: All exit criteria from spec §8 verified. Branch ready to merge.

- [ ] **Step 1: Backend gates**

```bash
uv run pytest -q --no-cov && uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: 560 passed; lint/format/type clean.

- [ ] **Step 2: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 42 passed; typecheck and lint clean.

- [ ] **Step 3: Manual smoke**

Backend in one terminal:

```bash
uv run uvicorn yas.web.app:app --reload --port 8000
```

Frontend in another:

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173/kids/1/calendar` (substitute a real kid id from your local DB; create one via the UI if needed). Walk through:

1. The week grid renders, 6am–10pm.
2. If the kid has an active enrollment, an event appears on the right weekdays at the right time.
3. Click an enrollment event → popover with details + Cancel enrollment.
4. Click Cancel enrollment → row vanishes optimistically and popover closes. Refresh: still gone (server confirmed).
5. Toggle view (top-right) to month → events shift to month layout.
6. Navigate forward a month → new events load.
7. If the kid has a school block, click it → Delete block button. Don't actually click it unless you mean to.
8. If an enrollment-linked block exists (created by an active enrollment), click it → no Delete button; helper text shown.

If any step breaks, capture the failure in a regression test before fixing.

- [ ] **Step 4: Push branch and open PR**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git push -u origin phase-5c-1-kid-calendar
gh pr create --title "phase 5c-1: per-kid calendar view (week + month)" --body "$(cat <<'EOF'
## Summary
- New backend endpoint GET /api/kids/{kid_id}/calendar?from=&to= aggregating enrollment + unavailability occurrences within a half-open date window
- New pure-function expand_recurring helper at src/yas/calendar/occurrences.py
- Frontend /kids/$id/calendar route with week + month toggle, fixed 6am–10pm time range, click-to-popover affordance
- Two new mutations following the canonical 5b-1b pattern: useCancelEnrollment + useDeleteUnavailability
- New dep: react-big-calendar (~25KB), exact-pinned

Satisfies the v1 terminal-state criterion: "calendar page renders a week view containing offerings, enrollments, and unavailability for a single kid within 1s on a realistic dataset."

## Test plan
- [x] uv run pytest -q (560 passed; +9 unit + +8 integration)
- [x] uv run ruff check . && uv run ruff format --check . clean
- [x] uv run mypy src clean
- [x] cd frontend && npm run typecheck clean
- [x] cd frontend && npm run lint clean
- [x] cd frontend && npm run test (42 passed; +11 new across mutations + CalendarView + CalendarEventPopover)
- [x] Manual smoke: enrollment cancel → row vanishes optimistically; month toggle works; enrollment-linked block can't be deleted from popover
- [ ] CI passes

## Spec / plan
- Spec: docs/superpowers/specs/2026-04-29-phase-5c-1-kid-calendar-design.md
- Plan: docs/superpowers/plans/2026-04-29-phase-5c-1-kid-calendar.md

## Out of scope (deferred)
- Match overlay + click-to-enroll (5c-2)
- Multi-kid combined view
- Drag-and-drop reschedule, ICS export, edit-in-place
EOF
)"
```

- [ ] **Step 5: Wait for CI; merge with `--squash`** (project convention).

---

## Notes for the implementer

- **The 5b-1b mutation pattern is canonical.** Both new mutations in Task 4 follow the same shape: `cancelQueries` → snapshot → optimistic `setQueryData` → `onError` restore → awaited `onSettled` invalidate. Don't reinvent.
- **react-big-calendar's CSS bleeds into the page**. The override file in Task 5 Step 5 is intentionally minimal. If something visually looks wrong during manual smoke, add only the targeted overrides needed — don't rewrite the library's stylesheet.
- **TanStack Router codegen** can lag during dev. If the typecheck fails after creating the route, run `npm run build` once to regenerate `routeTree.gen.ts`.
- **Boundary semantics matter** (spec §2.1 callout). The request window is half-open (`[from, to)`); source-row `date_start`/`date_end` are closed (both endpoints inclusive). The `expand_recurring` helper handles the conversion in one place — don't duplicate the math at call sites.
- **`api.delete` 204 handling** in Task 4 Step 4 — verify the existing `request<T>()` doesn't blow up on an empty body. If it does, add a `if (r.status === 204) return undefined as T;` guard.
- **No new backend deps**. Frontend gets exactly one new dep: `react-big-calendar` (and `@types/react-big-calendar` as devDep).
