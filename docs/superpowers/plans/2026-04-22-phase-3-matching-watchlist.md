# Phase 3 — Matching & Watchlist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use @superpowers:subagent-driven-development (recommended) or @superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Follow @superpowers:test-driven-development throughout. Apply @superpowers:verification-before-completion before marking any task done.

**Goal:** Extracted offerings become per-kid matches. Register a kid → the matcher runs hard gates (age evaluated at offering start_date, distance, interests, status, no-conflict with unavailability), writes `matches` rows with explainable `reasons` JSON, and re-runs on every mutation (offering new/updated, kid edit, unavailability change, enrollment change) plus a daily sweep. Watchlist hits bypass all hard gates. Nominatim geocodes offering locations so distance is a real number.

**Architecture:** Matcher split into pure gate/scoring functions and an async orchestrator; event-driven rematch hooks at each mutation site; two new worker `TaskGroup` tasks (daily sweep, geocode enricher); one Alembic migration (`geocode_attempts` negative-cache table). Watchlist trusts the user's manual verification and bypasses gates unconditionally.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 async, Pydantic V2, httpx (reused for Nominatim), pytest + pytest-asyncio + respx, fnmatch (stdlib) for glob patterns.

**Reference spec:** `docs/superpowers/specs/2026-04-22-phase-3-matching-watchlist-design.md`. Parent spec: `docs/superpowers/specs/2026-04-21-youth-activity-scheduler-design.md`.

---

## Deliverables (phase exit criteria)

- `uv run pytest` green with all new unit + integration + API tests, including the named-scenario suite (age-at-start-date, summer-offering-passes-school, holiday carve-out, watchlist bypass, enrollment blocking siblings, one-rematch-per-PATCH, immediate-geocode on household save)
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` clean
- `alembic upgrade head` on a fresh DB applies the `geocode_attempts` migration
- Docker Compose end-to-end smoke (with macOS overlay locally): create household with home address → home location geocoded; create a kid with DOB + school schedule + interests; register Lil Sluggers (Phase 2 URL); wait for scheduler + crawl + extract + rematch; `GET /api/matches?kid_id=1` returns rows whose `reasons` contains populated score breakdown and gate outcomes; distance is a real non-null number
- Watchlist with wildcard pattern produces an alert-worthy match even on an age-mismatched offering
- Enrolling a kid in an offering removes any other matches that would collide time-wise

## Conventions

- **Branch:** `phase-3-matching-watchlist` off `main`. Final merge with `--no-ff`.
- **TDD discipline throughout.** Red → green → commit.
- **Conventional commits.** One commit per task unless a reviewer-driven fix justifies a second.
- **Pydantic V2:** `ConfigDict(extra="forbid")` on write schemas; `from_attributes=True` on response models.
- **Timestamps:** tz-aware UTC; never naive datetimes in Python.
- **Mypy strict:** if a `# type: ignore[...]` is flagged unused, remove it. If strict complains on SQLAlchemy idioms, prefer real types to `Any`.
- **1Password-signed commits:** if `git commit` fails with "1Password: failed to fill whole buffer", surface as BLOCKED — do not retry.
- **No new system deps.** `httpx` and `fnmatch` are already available. No Playwright changes.

---

## File structure (target)

```
src/yas/
├── matching/                          # NEW
│   ├── __init__.py
│   ├── gates.py                       # pure sync hard-gate functions
│   ├── scoring.py                     # pure sync scoring + ScoreBreakdown
│   ├── aliases.py                     # INTEREST_ALIASES dict
│   ├── watchlist.py                   # pure sync pattern matching
│   └── matcher.py                     # async orchestrator; writes matches
├── unavailability/                    # NEW
│   ├── __init__.py
│   ├── school_materializer.py
│   └── enrollment_materializer.py
├── geo/                               # NEW
│   ├── __init__.py
│   ├── distance.py                    # great_circle_miles (pure)
│   ├── client.py                      # Geocoder protocol + NominatimClient
│   └── enricher.py                    # enrich function + loop
├── web/routes/
│   ├── kids.py                        # NEW
│   ├── kids_schemas.py                # NEW
│   ├── watchlist.py                   # NEW
│   ├── watchlist_schemas.py           # NEW
│   ├── unavailability.py              # NEW
│   ├── unavailability_schemas.py      # NEW
│   ├── enrollments.py                 # NEW
│   ├── enrollments_schemas.py         # NEW
│   ├── matches.py                     # NEW
│   ├── matches_schemas.py             # NEW
│   ├── household.py                   # NEW
│   └── household_schemas.py           # NEW
├── crawl/pipeline.py                  # MODIFIED — call rematch_offering after reconcile
├── worker/runner.py                   # MODIFIED — add daily_sweep + geocode_enricher tasks
├── web/app.py                         # MODIFIED — register new routers + attach Geocoder to AppState
├── web/deps.py                        # MODIFIED — AppState gains geocoder
├── __main__.py                        # MODIFIED — construct geocoder in _run_all
├── config.py                          # MODIFIED — geocode + sweep settings
└── db/models/watchlist.py             # MODIFIED — docstring on ignore_hard_gates

alembic/versions/
└── 0002_geocode_attempts.py           # NEW

tests/
├── fakes/
│   └── geocoder.py                    # NEW
├── unit/
│   ├── test_gates.py
│   ├── test_scoring.py
│   ├── test_watchlist_matcher.py
│   ├── test_aliases.py
│   ├── test_distance.py
│   ├── test_nominatim_client.py
│   ├── test_school_materializer.py
│   └── test_enrollment_materializer.py
└── integration/
    ├── test_matcher.py
    ├── test_enricher.py
    ├── test_api_kids.py
    ├── test_api_watchlist.py
    ├── test_api_unavailability.py
    ├── test_api_enrollments.py
    ├── test_api_matches.py
    └── test_api_household.py
```

---

## Task 1 — Branch, config, migration, docstring

**Files:**
- Modify: `src/yas/config.py`
- Modify: `.env.example`
- Create: `alembic/versions/0002_geocode_attempts.py`
- Modify: `src/yas/db/models/watchlist.py` (docstring only)
- Modify: `tests/unit/test_config.py` (two new tests)
- Modify: `tests/integration/test_migrations.py` (expected-tables set)

- [ ] **Step 1: Cut the branch**

```bash
cd /Users/owine/Git/youth-activity-scheduler
git checkout main
git checkout -b phase-3-matching-watchlist
```

- [ ] **Step 2: Add config tests (failing)**

Append to `tests/unit/test_config.py`:

```python
def test_geocode_settings_defaults(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = _settings()
    assert s.geocode_enabled is True
    assert s.geocode_tick_s == 300
    assert s.geocode_batch_size == 20
    assert s.geocode_nominatim_min_interval_s == 1.0


def test_sweep_settings_defaults(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = _settings()
    assert s.sweep_enabled is True
    assert s.sweep_time_utc == "07:00"
```

Run: `uv run pytest tests/unit/test_config.py -v` — expect two failures (`AttributeError`).

- [ ] **Step 3: Implement the settings**

Append to `Settings` in `src/yas/config.py`:

```python
    # Geocoder
    geocode_enabled: bool = True
    geocode_tick_s: int = 300
    geocode_batch_size: int = 20
    geocode_nominatim_min_interval_s: float = 1.0

    # Daily sweep
    sweep_enabled: bool = True
    sweep_time_utc: str = "07:00"
```

- [ ] **Step 4: Update `.env.example`**

Append:
```
# Geocoder
# YAS_GEOCODE_ENABLED=true
# YAS_GEOCODE_TICK_S=300
# YAS_GEOCODE_BATCH_SIZE=20
# YAS_GEOCODE_NOMINATIM_MIN_INTERVAL_S=1.0

# Daily sweep
# YAS_SWEEP_ENABLED=true
# YAS_SWEEP_TIME_UTC=07:00
```

- [ ] **Step 5: Update the watchlist column docstring**

Edit `src/yas/db/models/watchlist.py`. On the `ignore_hard_gates` line, add a docstring-style comment (either above the column or in the class docstring — consistent with the file style). Minimum:

```python
    # Reserved for a future "strict mode" opt-in. Not consulted by the matcher
    # in Phase 3 — watchlist hits unconditionally bypass all hard gates.
    ignore_hard_gates: Mapped[bool] = mapped_column(default=False)
```

- [ ] **Step 6: Generate the migration**

```bash
export YAS_ANTHROPIC_API_KEY=sk-test-nonop
mkdir -p data
uv run alembic revision -m "geocode_attempts" --rev-id 0002
```

This creates `alembic/versions/0002_geocode_attempts.py` with an empty upgrade/downgrade. Replace the body so the file looks like:

```python
"""geocode_attempts

Revision ID: 0002
Revises: 0001_initial
Create Date: 2026-04-22 ...
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geocode_attempts",
        sa.Column("address_norm", sa.String(), primary_key=True),
        sa.Column("last_tried", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("geocode_attempts")
```

> The auto-generated filename may be `0002_geocode_attempts.py` or `0002_<slug>.py` depending on your `file_template`; rename to `0002_geocode_attempts.py` for consistency. Inside the file, `revision = "0002"` is what matters.

- [ ] **Step 7: Extend the migrations integration test**

Edit `tests/integration/test_migrations.py`. Add `"geocode_attempts"` to the `EXPECTED_TABLES` set.

- [ ] **Step 8: Verify**

```bash
uv run pytest tests/unit/test_config.py tests/integration/test_migrations.py -v
uv run pytest
uv run ruff check .
uv run mypy src
```

All green.

- [ ] **Step 9: Commit**

```bash
git add src/yas/config.py src/yas/db/models/watchlist.py .env.example \
    alembic/versions/0002_geocode_attempts.py \
    tests/unit/test_config.py tests/integration/test_migrations.py
git commit -m "chore: add phase-3 config, geocode_attempts migration, and watchlist comment"
```

---

## Task 2 — Pure hard gates

**Files:**
- Create: `src/yas/matching/__init__.py`
- Create: `src/yas/matching/gates.py`
- Create: `tests/unit/test_gates.py`

Implements all five gates as pure sync functions returning `GateResult`. Comprehensive test cases pin the semantically tricky cases from the spec.

- [ ] **Step 1: Write the failing test file**

`tests/unit/test_gates.py`:

```python
from dataclasses import dataclass
from datetime import date, time

import pytest

from yas.db.models._types import OfferingStatus, ProgramType, UnavailabilitySource
from yas.matching.gates import (
    GateResult,
    age_fits,
    distance_fits,
    interests_overlap,
    no_conflict_with_unavailability,
    offering_active_and_not_ended,
)


# Lightweight ORM-shaped stand-ins so the gates stay testable without a DB.
@dataclass
class _Kid:
    id: int = 1
    dob: date = date(2019, 5, 1)
    interests: list[str] = None
    max_distance_mi: float | None = None
    school_holidays: list[str] = None

    def __post_init__(self):
        if self.interests is None:
            self.interests = []
        if self.school_holidays is None:
            self.school_holidays = []


@dataclass
class _Offering:
    id: int = 1
    site_id: int = 1
    name: str = ""
    description: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    program_type: ProgramType = ProgramType.unknown
    start_date: date | None = None
    end_date: date | None = None
    days_of_week: list[str] = None
    time_start: time | None = None
    time_end: time | None = None
    status: str = OfferingStatus.active.value
    location_id: int | None = None

    def __post_init__(self):
        if self.days_of_week is None:
            self.days_of_week = []


@dataclass
class _Block:
    id: int = 1
    kid_id: int = 1
    source: str = UnavailabilitySource.school.value
    days_of_week: list[str] = None
    time_start: time | None = None
    time_end: time | None = None
    date_start: date | None = None
    date_end: date | None = None
    active: bool = True

    def __post_init__(self):
        if self.days_of_week is None:
            self.days_of_week = []


ALIASES = {
    "soccer": ["soccer", "futbol", "kickers"],
    "baseball": ["baseball", "t-ball", "tball", "coach pitch"],
}


# --- age gate -----------------------------------------------------------------

def test_age_uses_offering_start_date_not_today():
    kid = _Kid(dob=date(2021, 5, 1))
    offering = _Offering(start_date=date(2026, 5, 15), age_min=5, age_max=6)
    today = date(2026, 4, 22)
    # today's age = 4; age at start = 5
    r = age_fits(kid, offering, today=today)
    assert r.passed, r.detail
    assert "5" in r.detail


def test_age_just_missed_rejects():
    kid = _Kid(dob=date(2021, 5, 1))
    offering = _Offering(start_date=date(2026, 4, 25), age_min=5)  # before birthday
    today = date(2026, 4, 22)
    r = age_fits(kid, offering, today=today)
    assert not r.passed
    assert r.code == "too_young"


def test_age_upper_bound_inclusive():
    kid = _Kid(dob=date(2019, 1, 1))
    offering = _Offering(start_date=date(2026, 6, 1), age_max=7)
    today = date(2026, 4, 22)
    r = age_fits(kid, offering, today=today)
    assert r.passed


def test_age_falls_back_to_today_when_no_start_date():
    kid = _Kid(dob=date(2019, 5, 1))
    offering = _Offering(start_date=None, age_min=6)
    today = date(2026, 4, 22)  # age 6
    r = age_fits(kid, offering, today=today)
    assert r.passed


def test_age_unspecified_range_passes():
    kid = _Kid(dob=date(2019, 5, 1))
    offering = _Offering(start_date=date(2026, 6, 1))  # no age_min/max
    today = date(2026, 4, 22)
    r = age_fits(kid, offering, today=today)
    assert r.passed


# --- distance gate ------------------------------------------------------------

def test_distance_unknown_fails_open():
    kid = _Kid(max_distance_mi=15.0)
    offering = _Offering(location_id=None)
    r = distance_fits(kid, offering, distance_mi=None, household_default=None)
    assert r.passed
    assert r.code == "distance_unknown"


def test_distance_under_cap_passes():
    kid = _Kid(max_distance_mi=15.0)
    offering = _Offering(location_id=7)
    r = distance_fits(kid, offering, distance_mi=5.0, household_default=None)
    assert r.passed


def test_distance_over_cap_fails():
    kid = _Kid(max_distance_mi=15.0)
    offering = _Offering(location_id=7)
    r = distance_fits(kid, offering, distance_mi=20.0, household_default=None)
    assert not r.passed
    assert r.code == "too_far"


def test_distance_falls_back_to_household_default():
    kid = _Kid(max_distance_mi=None)
    offering = _Offering(location_id=7)
    r = distance_fits(kid, offering, distance_mi=10.0, household_default=20.0)
    assert r.passed


def test_distance_no_cap_set_passes():
    kid = _Kid(max_distance_mi=None)
    offering = _Offering(location_id=7)
    r = distance_fits(kid, offering, distance_mi=100.0, household_default=None)
    assert r.passed
    assert r.code == "distance_unlimited"


# --- interests gate -----------------------------------------------------------

def test_interests_match_via_program_type():
    kid = _Kid(interests=["soccer"])
    offering = _Offering(program_type=ProgramType.soccer, name="Spring Soccer")
    r = interests_overlap(kid, offering, ALIASES)
    assert r.passed


def test_interests_match_via_alias_in_name():
    kid = _Kid(interests=["baseball"])
    offering = _Offering(program_type=ProgramType.multisport, name="T-Ball Program")
    r = interests_overlap(kid, offering, ALIASES)
    assert r.passed


def test_interests_no_match_rejects():
    kid = _Kid(interests=["swim"])
    offering = _Offering(program_type=ProgramType.soccer, name="Spring Soccer")
    r = interests_overlap(kid, offering, ALIASES)
    assert not r.passed


def test_interests_empty_list_rejects():
    kid = _Kid(interests=[])
    offering = _Offering(program_type=ProgramType.soccer, name="Spring Soccer")
    r = interests_overlap(kid, offering, ALIASES)
    assert not r.passed


# --- status gate --------------------------------------------------------------

def test_offering_active_passes():
    offering = _Offering(status=OfferingStatus.active.value, end_date=date(2027, 1, 1))
    today = date(2026, 4, 22)
    r = offering_active_and_not_ended(offering, today=today)
    assert r.passed


def test_offering_ended_rejects():
    offering = _Offering(status=OfferingStatus.active.value, end_date=date(2026, 1, 1))
    today = date(2026, 4, 22)
    r = offering_active_and_not_ended(offering, today=today)
    assert not r.passed
    assert r.code == "ended"


def test_offering_withdrawn_rejects():
    offering = _Offering(status=OfferingStatus.withdrawn.value)
    today = date(2026, 4, 22)
    r = offering_active_and_not_ended(offering, today=today)
    assert not r.passed
    assert r.code == "not_active"


# --- no-conflict gate ---------------------------------------------------------

def _school_block():
    return _Block(
        source=UnavailabilitySource.school.value,
        days_of_week=["mon", "tue", "wed", "thu", "fri"],
        time_start=time(8, 0),
        time_end=time(15, 0),
        date_start=date(2026, 9, 2),
        date_end=date(2027, 6, 14),
    )


def test_summer_offering_passes_school_year_gate():
    """A summer program (Jun-Aug) should pass even though school weekday 8-3 is blocked."""
    block = _school_block()
    offering = _Offering(
        start_date=date(2026, 6, 15),
        end_date=date(2026, 8, 15),
        days_of_week=["mon", "wed"],
        time_start=time(9, 0),
        time_end=time(12, 0),
    )
    r = no_conflict_with_unavailability(offering, [block], school_holidays=set(), today=date(2026, 4, 22))
    assert r.passed, r.detail


def test_during_school_year_conflicts_with_school():
    block = _school_block()
    offering = _Offering(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 11, 1),
        days_of_week=["tue"],
        time_start=time(10, 0),   # overlaps 08-15
        time_end=time(11, 0),
    )
    r = no_conflict_with_unavailability(offering, [block], school_holidays=set(), today=date(2026, 4, 22))
    assert not r.passed


def test_after_school_during_school_year_passes():
    block = _school_block()
    offering = _Offering(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 11, 1),
        days_of_week=["tue"],
        time_start=time(16, 0),
        time_end=time(17, 0),
    )
    r = no_conflict_with_unavailability(offering, [block], school_holidays=set(), today=date(2026, 4, 22))
    assert r.passed


def test_school_holiday_carves_exception_on_specific_date():
    """Offering lands on a listed school holiday → school block skipped for that date."""
    block = _school_block()
    # MLK Day 2027-01-18 is a Monday during the school year
    offering = _Offering(
        start_date=date(2027, 1, 18),
        end_date=date(2027, 1, 18),
        days_of_week=["mon"],
        time_start=time(10, 0),
        time_end=time(11, 0),
    )
    r = no_conflict_with_unavailability(
        offering, [block],
        school_holidays={date(2027, 1, 18)},
        today=date(2026, 4, 22),
    )
    assert r.passed, r.detail


def test_partial_schedule_fails_open():
    block = _school_block()
    offering = _Offering(start_date=None, end_date=None, days_of_week=[], time_start=None, time_end=None)
    r = no_conflict_with_unavailability(offering, [block], school_holidays=set(), today=date(2026, 4, 22))
    assert r.passed
    assert r.code == "schedule_partial"


def test_enrollment_block_blocks_overlapping_offering():
    block = _Block(
        source=UnavailabilitySource.enrollment.value,
        days_of_week=["sat"],
        time_start=time(9, 0),
        time_end=time(10, 0),
        date_start=date(2026, 5, 1),
        date_end=date(2026, 7, 1),
    )
    offering = _Offering(
        start_date=date(2026, 5, 10),
        end_date=date(2026, 6, 20),
        days_of_week=["sat"],
        time_start=time(9, 30),   # overlaps
        time_end=time(10, 30),
    )
    r = no_conflict_with_unavailability(offering, [block], school_holidays=set(), today=date(2026, 4, 22))
    assert not r.passed
```

- [ ] **Step 2: Run to verify all fail**

`uv run pytest tests/unit/test_gates.py -v` — expect import errors.

- [ ] **Step 3: Create the package**

`src/yas/matching/__init__.py`: empty.

- [ ] **Step 4: Implement `src/yas/matching/gates.py`**

```python
"""Pure sync hard-gate functions.

Each returns a GateResult namedtuple. No I/O. No DB access. Every input is
already-loaded ORM rows or primitives. This keeps the matcher's hot path fast
and the gates trivially unit-testable."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, NamedTuple

from yas.crawl.normalize import normalize_name
from yas.db.models._types import OfferingStatus


class GateResult(NamedTuple):
    passed: bool
    code: str
    detail: str


def _age_on(dob: date, reference: date) -> int:
    """Whole years between dob and reference."""
    years = reference.year - dob.year
    if (reference.month, reference.day) < (dob.month, dob.day):
        years -= 1
    return max(years, 0)


def age_fits(kid: Any, offering: Any, *, today: date) -> GateResult:
    reference = offering.start_date or today
    age = _age_on(kid.dob, reference)
    if offering.age_min is None and offering.age_max is None:
        return GateResult(True, "age_unspecified", "offering has no age range")
    if offering.age_min is not None and age < offering.age_min:
        return GateResult(False, "too_young",
                          f"age {age} on {reference.isoformat()} < min {offering.age_min}")
    if offering.age_max is not None and age > offering.age_max:
        return GateResult(False, "too_old",
                          f"age {age} on {reference.isoformat()} > max {offering.age_max}")
    return GateResult(True, "age_ok",
                      f"age {age} on {reference.isoformat()} fits [{offering.age_min}, {offering.age_max}]")


def distance_fits(
    kid: Any, offering: Any, *, distance_mi: float | None, household_default: float | None,
) -> GateResult:
    cap = kid.max_distance_mi if kid.max_distance_mi is not None else household_default
    if cap is None:
        return GateResult(True, "distance_unlimited", "no distance cap configured")
    if offering.location_id is None or distance_mi is None:
        return GateResult(True, "distance_unknown", "location not geocoded")
    if distance_mi <= cap:
        return GateResult(True, "distance_ok", f"{distance_mi:.1f}mi of {cap:.1f}mi max")
    return GateResult(False, "too_far", f"{distance_mi:.1f}mi > {cap:.1f}mi max")


def interests_overlap(kid: Any, offering: Any, aliases: dict[str, list[str]]) -> GateResult:
    if not kid.interests:
        return GateResult(False, "no_kid_interests", "kid has no interests configured")
    needle_hay = normalize_name(f"{offering.name or ''} {offering.description or ''}")
    program_type_val = getattr(offering.program_type, "value", offering.program_type)
    for interest in kid.interests:
        interest = interest.lower()
        if program_type_val == interest:
            return GateResult(True, "interest_program_type_match",
                              f"kid interest '{interest}' == program_type")
        terms = aliases.get(interest, [interest])
        for term in terms:
            if normalize_name(term) in needle_hay:
                return GateResult(True, "interest_text_match",
                                  f"kid interest '{interest}' matched via '{term}' in name/description")
    return GateResult(False, "no_interest_match",
                      f"no kid interest ({', '.join(kid.interests)}) matched offering")


def offering_active_and_not_ended(offering: Any, *, today: date) -> GateResult:
    status = getattr(offering.status, "value", offering.status)
    if status != OfferingStatus.active.value:
        return GateResult(False, "not_active", f"offering status = {status}")
    if offering.end_date is not None and offering.end_date < today:
        return GateResult(False, "ended", f"offering ended {offering.end_date.isoformat()}")
    return GateResult(True, "active", "offering is active and not ended")


_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _weekday_name(d: date) -> str:
    return _DAY_NAMES[d.weekday()]


def _offering_has_full_schedule(offering: Any) -> bool:
    return (
        offering.start_date is not None
        and offering.end_date is not None
        and offering.days_of_week
        and offering.time_start is not None
        and offering.time_end is not None
    )


def _time_overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def no_conflict_with_unavailability(
    offering: Any,
    blocks: list[Any],
    school_holidays: set[date],
    *,
    today: date,
) -> GateResult:
    if not _offering_has_full_schedule(offering):
        return GateResult(True, "schedule_partial", "offering schedule incomplete; cannot verify no-conflict")

    offering_days = {d.lower() for d in (getattr(d, "value", d) for d in offering.days_of_week)}
    active_blocks = [b for b in blocks if b.active]
    if not active_blocks:
        return GateResult(True, "no_blocks", "no active unavailability blocks")

    # Iterate each date in the offering's date range.
    cur = offering.start_date
    end = offering.end_date
    while cur <= end:
        weekday = _weekday_name(cur)
        if weekday in offering_days:
            for block in active_blocks:
                source = getattr(block.source, "value", block.source)
                if source == "school" and cur in school_holidays:
                    continue
                if block.date_start is not None and cur < block.date_start:
                    continue
                if block.date_end is not None and cur > block.date_end:
                    continue
                block_days = {d.lower() for d in (getattr(d, "value", d) for d in (block.days_of_week or []))}
                if block_days and weekday not in block_days:
                    continue
                if block.time_start is None or block.time_end is None:
                    # Whole-day block on this date → conflict.
                    return GateResult(False, "conflict",
                                      f"all-day block on {cur.isoformat()} ({source})")
                if _time_overlaps(offering.time_start, offering.time_end, block.time_start, block.time_end):
                    return GateResult(False, "conflict",
                                      f"conflict on {cur.isoformat()} ({source})")
        cur += timedelta(days=1)
    return GateResult(True, "no_conflict",
                      f"no overlap with {len(active_blocks)} active block(s)")
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_gates.py -v
uv run pytest
uv run ruff check .
uv run mypy src
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/yas/matching/__init__.py src/yas/matching/gates.py tests/unit/test_gates.py
git commit -m "feat(matching): add pure hard-gate functions with age-at-start-date semantics"
```

---

## Task 3 — Pure scoring

**Files:**
- Create: `src/yas/matching/scoring.py`
- Create: `tests/unit/test_scoring.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_scoring.py`:

```python
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import pytest

from yas.matching.scoring import ScoreBreakdown, compute_score


@dataclass
class _Kid:
    availability: dict = field(default_factory=dict)
    max_distance_mi: float | None = None


@dataclass
class _Offering:
    days_of_week: list[str] = field(default_factory=list)
    time_start: time | None = None
    time_end: time | None = None
    start_date: date | None = None
    end_date: date | None = None
    registration_opens_at: datetime | None = None
    price_cents: int | None = None
    first_seen: datetime | None = None


TODAY = date(2026, 4, 22)


def test_score_breakdown_weighted_sum():
    bd = ScoreBreakdown(
        availability=1.0, distance=1.0, price=1.0,
        registration_timing=1.0, freshness=1.0,
    )
    assert bd.score == pytest.approx(1.0)


def test_score_all_zeros():
    bd = ScoreBreakdown(
        availability=0.0, distance=0.0, price=0.0,
        registration_timing=0.0, freshness=0.0,
    )
    assert bd.score == 0.0


def test_availability_default_on_missing():
    kid = _Kid(availability={})
    offering = _Offering()
    _score, reasons = compute_score(
        kid, offering, distance_mi=None, household_max_distance_mi=None, today=TODAY,
    )
    assert reasons["availability"] == pytest.approx(0.5)


def test_distance_full_credit_under_cap():
    kid = _Kid(max_distance_mi=10.0)
    offering = _Offering()
    _score, reasons = compute_score(
        kid, offering, distance_mi=2.0, household_max_distance_mi=None, today=TODAY,
    )
    # 2mi < 30% of 10 (=3mi) → full credit
    assert reasons["distance"] == pytest.approx(1.0)


def test_distance_linear_decay():
    kid = _Kid(max_distance_mi=10.0)
    offering = _Offering()
    _score, reasons = compute_score(
        kid, offering, distance_mi=6.5, household_max_distance_mi=None, today=TODAY,
    )
    # between 3 and 10; partial
    assert 0.0 < reasons["distance"] < 1.0


def test_distance_zero_at_cap():
    kid = _Kid(max_distance_mi=10.0)
    offering = _Offering()
    _score, reasons = compute_score(
        kid, offering, distance_mi=10.0, household_max_distance_mi=None, today=TODAY,
    )
    assert reasons["distance"] == pytest.approx(0.0)


def test_price_full_when_unset():
    kid = _Kid()
    offering = _Offering(price_cents=99999)
    _score, reasons = compute_score(
        kid, offering, distance_mi=None, household_max_distance_mi=None, today=TODAY,
    )
    assert reasons["price"] == pytest.approx(1.0)


def test_registration_timing_open_now():
    kid = _Kid()
    offering = _Offering(registration_opens_at=datetime(2026, 4, 1, tzinfo=UTC))
    _score, reasons = compute_score(
        kid, offering, distance_mi=None, household_max_distance_mi=None, today=TODAY,
    )
    assert reasons["registration_timing"] == pytest.approx(1.0)


def test_registration_timing_closed():
    kid = _Kid()
    offering = _Offering(
        registration_opens_at=datetime(2026, 4, 1, tzinfo=UTC),
        end_date=date(2026, 4, 15),   # already ended
    )
    _score, reasons = compute_score(
        kid, offering, distance_mi=None, household_max_distance_mi=None, today=TODAY,
    )
    # end_date < today interpreted as "registration closed"
    assert reasons["registration_timing"] == pytest.approx(0.0)


def test_registration_timing_unknown_defaults_half():
    kid = _Kid()
    offering = _Offering(registration_opens_at=None)
    _score, reasons = compute_score(
        kid, offering, distance_mi=None, household_max_distance_mi=None, today=TODAY,
    )
    assert reasons["registration_timing"] == pytest.approx(0.5)


def test_freshness_recent_full():
    kid = _Kid()
    offering = _Offering(first_seen=datetime.now(UTC))
    _score, reasons = compute_score(
        kid, offering, distance_mi=None, household_max_distance_mi=None, today=TODAY,
    )
    assert reasons["freshness"] > 0.95


def test_freshness_old_zero():
    kid = _Kid()
    offering = _Offering(first_seen=datetime.now(UTC) - timedelta(days=120))
    _score, reasons = compute_score(
        kid, offering, distance_mi=None, household_max_distance_mi=None, today=TODAY,
    )
    assert reasons["freshness"] == pytest.approx(0.0)


def test_score_is_weighted_combination():
    kid = _Kid(max_distance_mi=10.0)
    offering = _Offering(first_seen=datetime.now(UTC))
    score, reasons = compute_score(
        kid, offering, distance_mi=2.0, household_max_distance_mi=None, today=TODAY,
    )
    # weighted sum with distance=1.0, freshness≈1.0, availability=0.5, price=1.0, reg=0.5
    # 0.5*0.4 + 1.0*0.2 + 1.0*0.1 + 0.5*0.2 + 1.0*0.1 = 0.2 + 0.2 + 0.1 + 0.1 + 0.1 = 0.7
    assert score == pytest.approx(0.7, abs=0.02)
```

- [ ] **Step 2: Run — expect ImportError**

`uv run pytest tests/unit/test_scoring.py -v`

- [ ] **Step 3: Implement `src/yas/matching/scoring.py`**

```python
"""Pure sync scoring of (kid, offering) pairs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any


_W_AVAILABILITY = 0.4
_W_DISTANCE = 0.2
_W_PRICE = 0.1
_W_REGISTRATION = 0.2
_W_FRESHNESS = 0.1

_FRESHNESS_DAYS = 60


@dataclass(frozen=True)
class ScoreBreakdown:
    availability: float
    distance: float
    price: float
    registration_timing: float
    freshness: float

    @property
    def score(self) -> float:
        total = (
            self.availability * _W_AVAILABILITY
            + self.distance * _W_DISTANCE
            + self.price * _W_PRICE
            + self.registration_timing * _W_REGISTRATION
            + self.freshness * _W_FRESHNESS
        )
        return max(0.0, min(1.0, total))

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def compute_score(
    kid: Any,
    offering: Any,
    *,
    distance_mi: float | None,
    household_max_distance_mi: float | None,
    today: date,
) -> tuple[float, dict[str, Any]]:
    availability = _availability_signal(kid, offering)
    distance = _distance_signal(kid, offering, distance_mi, household_max_distance_mi)
    price = _price_signal(kid, offering)
    registration = _registration_signal(offering, today=today)
    freshness = _freshness_signal(offering, today=today)

    bd = ScoreBreakdown(availability, distance, price, registration, freshness)
    return bd.score, bd.as_dict()


def _availability_signal(kid: Any, offering: Any) -> float:
    # Availability is a JSON dict with day→list of time windows. Without a richer
    # schema here the minimum viable signal is: if the offering schedule is fully
    # specified and intersects any kid availability window, 1.0; if the kid has no
    # availability configured, 0.5; otherwise 0.0.
    windows = getattr(kid, "availability", None) or {}
    if not windows:
        return 0.5
    if not (offering.days_of_week and offering.time_start and offering.time_end):
        return 0.5
    offering_days = {str(getattr(d, "value", d)).lower() for d in offering.days_of_week}
    for day, slots in windows.items():
        if day.lower() not in offering_days:
            continue
        for slot in slots or []:
            ws = slot.get("start")
            we = slot.get("end")
            if not (ws and we):
                continue
            if offering.time_start.isoformat() >= ws and offering.time_end.isoformat() <= we:
                return 1.0
    return 0.0


def _distance_signal(
    kid: Any, offering: Any,
    distance_mi: float | None,
    household_default: float | None,
) -> float:
    cap = kid.max_distance_mi if kid.max_distance_mi is not None else household_default
    if distance_mi is None or cap is None or cap <= 0:
        return 0.5
    threshold = cap * 0.3
    if distance_mi <= threshold:
        return 1.0
    if distance_mi >= cap:
        return 0.0
    # linear decay from 1.0 at threshold to 0.0 at cap
    return max(0.0, 1.0 - (distance_mi - threshold) / (cap - threshold))


def _price_signal(kid: Any, offering: Any) -> float:
    max_price = getattr(kid, "max_price_cents", None)
    if max_price is None:
        return 1.0
    if offering.price_cents is None:
        return 1.0  # unknown price → don't penalize
    if offering.price_cents <= max_price:
        return 1.0
    if offering.price_cents >= 2 * max_price:
        return 0.0
    return max(0.0, 1.0 - (offering.price_cents - max_price) / max_price)


def _registration_signal(offering: Any, *, today: date) -> float:
    # If end_date < today, treat as closed.
    if offering.end_date is not None and offering.end_date < today:
        return 0.0
    opens = offering.registration_opens_at
    if opens is None:
        return 0.5
    opens_date = opens.date() if isinstance(opens, datetime) else opens
    delta = (opens_date - today).days
    if delta <= 0:
        return 1.0
    if delta <= 7:
        return 0.8
    if delta <= 30:
        return 0.6
    return 0.4


def _freshness_signal(offering: Any, *, today: date) -> float:
    first_seen = offering.first_seen
    if first_seen is None:
        return 0.5
    if isinstance(first_seen, datetime):
        first_seen_date = first_seen.date()
    else:
        first_seen_date = first_seen
    age_days = (today - first_seen_date).days
    if age_days <= 0:
        return 1.0
    if age_days >= _FRESHNESS_DAYS:
        return 0.0
    return 1.0 - (age_days / _FRESHNESS_DAYS)
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/unit/test_scoring.py -v
uv run pytest
uv run ruff check .
uv run mypy src
git add src/yas/matching/scoring.py tests/unit/test_scoring.py
git commit -m "feat(matching): add pure scoring with per-signal reasons"
```

---

## Task 4 — Aliases + watchlist pattern matcher

**Files:**
- Create: `src/yas/matching/aliases.py`
- Create: `src/yas/matching/watchlist.py`
- Create: `tests/unit/test_aliases.py`
- Create: `tests/unit/test_watchlist_matcher.py`

- [ ] **Step 1: Failing tests**

`tests/unit/test_aliases.py`:

```python
from yas.db.models._types import ProgramType
from yas.matching.aliases import INTEREST_ALIASES


def test_every_program_type_has_alias_entry():
    for pt in ProgramType:
        if pt == ProgramType.unknown:
            continue
        assert pt.value in INTEREST_ALIASES, f"{pt.value} missing from INTEREST_ALIASES"


def test_aliases_are_lowercase_no_punctuation_clones():
    for _key, values in INTEREST_ALIASES.items():
        for v in values:
            assert v == v.lower(), f"alias '{v}' is not lowercase"
```

`tests/unit/test_watchlist_matcher.py`:

```python
from dataclasses import dataclass

import pytest

from yas.db.models._types import WatchlistPriority
from yas.matching.watchlist import WatchlistHit, matches_watchlist


@dataclass
class _Entry:
    id: int
    pattern: str
    site_id: int | None = None
    priority: str = WatchlistPriority.normal.value
    active: bool = True


@dataclass
class _Offering:
    id: int = 1
    site_id: int = 1
    name: str = ""


def test_substring_match():
    e = _Entry(id=1, pattern="kickers")
    o = _Offering(name="Little Kickers Saturday")
    hit = matches_watchlist(o, [e], site_id=1)
    assert hit is not None
    assert hit.reason == "substring"


def test_substring_case_insensitive():
    e = _Entry(id=1, pattern="KICKERS")
    o = _Offering(name="Little Kickers Saturday")
    hit = matches_watchlist(o, [e], site_id=1)
    assert hit is not None


def test_glob_match():
    e = _Entry(id=1, pattern="little *")
    o = _Offering(name="Little Sluggers Spring")
    hit = matches_watchlist(o, [e], site_id=1)
    assert hit is not None
    assert hit.reason == "glob"


def test_fnmatch_requires_full_string_match_not_substring():
    # Pins a gotcha: fnmatchcase matches the WHOLE string, not a substring.
    # `t?ball` (normalized to `t ball`) does NOT match `t ball coach pitch`
    # because fnmatch requires the pattern to cover the whole name. Users who
    # want substring semantics with wildcards should write `*t*ball*`.
    e = _Entry(id=1, pattern="t?ball")
    o = _Offering(name="T-ball Coach Pitch")  # normalized: "t ball coach pitch"
    assert matches_watchlist(o, [e], site_id=1) is None


def test_glob_wildcards_are_substring_equivalent_when_bracketed():
    e = _Entry(id=1, pattern="*kickers*")
    o = _Offering(name="Little Kickers Saturday")
    hit = matches_watchlist(o, [e], site_id=1)
    assert hit is not None
    assert hit.reason == "glob"


def test_site_id_scope_matches_across_sites_when_null():
    e = _Entry(id=1, pattern="soccer", site_id=None)
    o1 = _Offering(site_id=1, name="Spring Soccer")
    o2 = _Offering(site_id=2, name="Summer Soccer")
    assert matches_watchlist(o1, [e], site_id=1) is not None
    assert matches_watchlist(o2, [e], site_id=2) is not None


def test_site_id_scope_rejects_wrong_site():
    e = _Entry(id=1, pattern="soccer", site_id=5)
    o = _Offering(site_id=1, name="Spring Soccer")
    assert matches_watchlist(o, [e], site_id=1) is None


def test_priority_high_beats_normal():
    e_high = _Entry(id=2, pattern="kickers", priority=WatchlistPriority.high.value)
    e_normal = _Entry(id=1, pattern="kickers", priority=WatchlistPriority.normal.value)
    o = _Offering(name="Little Kickers")
    hit = matches_watchlist(o, [e_normal, e_high], site_id=1)
    assert hit is not None
    assert hit.entry.id == 2   # high wins


def test_among_same_priority_lowest_id_wins():
    e1 = _Entry(id=1, pattern="kickers")
    e2 = _Entry(id=2, pattern="kickers")
    o = _Offering(name="Little Kickers")
    hit = matches_watchlist(o, [e2, e1], site_id=1)
    assert hit.entry.id == 1


def test_inactive_entries_ignored():
    e = _Entry(id=1, pattern="kickers", active=False)
    o = _Offering(name="Little Kickers")
    assert matches_watchlist(o, [e], site_id=1) is None


def test_no_match_returns_none():
    e = _Entry(id=1, pattern="baseball")
    o = _Offering(name="Spring Soccer")
    assert matches_watchlist(o, [e], site_id=1) is None
```

- [ ] **Step 2: Run to verify fails**

- [ ] **Step 3: Implement `src/yas/matching/aliases.py`**

```python
"""Interest-name alias map, keyed by ProgramType value."""

from __future__ import annotations

INTEREST_ALIASES: dict[str, list[str]] = {
    # Team sports
    "soccer":     ["soccer", "futbol", "kickers"],
    "baseball":   ["baseball", "t ball", "tball", "t-ball", "coach pitch", "little league", "sluggers"],
    "softball":   ["softball", "fastpitch"],
    "basketball": ["basketball", "hoops"],
    "hockey":     ["hockey", "ice hockey", "learn to skate"],
    "football":   ["football", "flag football"],
    # Individual / other sports
    "swim":         ["swim", "swimming", "aquatics", "learn to swim"],
    "martial_arts": ["martial arts", "karate", "taekwondo", "tae kwon do", "judo", "jiu jitsu", "bjj"],
    "gymnastics":   ["gymnastics", "tumbling"],
    "dance":        ["dance", "ballet", "jazz dance", "hip hop", "tap"],
    "gym":          ["gym", "gymnastics", "tumbling", "fitness", "parkour"],
    # Enrichment
    "art":      ["art", "painting", "drawing", "ceramics", "pottery", "crafts"],
    "music":    ["music", "piano", "guitar", "violin", "orchestra", "chorus", "singing"],
    "stem":     ["stem", "science", "coding", "robotics", "engineering", "math"],
    "academic": ["academic", "tutoring", "reading", "writing", "language", "spanish"],
    # Umbrella
    "multisport":   ["multisport", "multi sport", "sports sampler"],
    "outdoor":      ["outdoor", "nature", "hiking", "camping"],
    "camp_general": ["camp", "summer camp", "day camp"],
}
```

- [ ] **Step 4: Implement `src/yas/matching/watchlist.py`**

```python
"""Pure watchlist pattern matching — substring OR glob (no regex)."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any, Literal

from yas.crawl.normalize import normalize_name
from yas.db.models._types import WatchlistPriority


@dataclass(frozen=True)
class WatchlistHit:
    entry: Any
    reason: Literal["substring", "glob"]


def _is_glob(pattern: str) -> bool:
    return "*" in pattern or "?" in pattern


def _priority_rank(priority_val: str) -> int:
    # high before normal; unknown priorities sort last.
    if priority_val == WatchlistPriority.high.value:
        return 0
    if priority_val == WatchlistPriority.normal.value:
        return 1
    return 2


def matches_watchlist(offering: Any, entries: list[Any], *, site_id: int) -> WatchlistHit | None:
    normalized_name = normalize_name(offering.name or "")

    # Stable order: priority then id asc.
    def _key(e: Any) -> tuple[int, int]:
        prio = getattr(e.priority, "value", e.priority)
        return (_priority_rank(prio), e.id)

    for entry in sorted(entries, key=_key):
        if not entry.active:
            continue
        if entry.site_id is not None and entry.site_id != site_id:
            continue
        pattern_norm = normalize_name(entry.pattern)
        if _is_glob(entry.pattern):
            # fnmatchcase operates on the raw (normalized) strings.
            if fnmatch.fnmatchcase(normalized_name, pattern_norm):
                return WatchlistHit(entry=entry, reason="glob")
        else:
            if pattern_norm in normalized_name:
                return WatchlistHit(entry=entry, reason="substring")
    return None
```

- [ ] **Step 5: Run + commit**

```bash
uv run pytest tests/unit/test_aliases.py tests/unit/test_watchlist_matcher.py -v
uv run pytest
uv run ruff check .
uv run mypy src
git add src/yas/matching/aliases.py src/yas/matching/watchlist.py \
    tests/unit/test_aliases.py tests/unit/test_watchlist_matcher.py
git commit -m "feat(matching): add interest aliases and pure watchlist pattern matcher"
```

---

## Task 5 — Haversine distance

**Files:**
- Create: `src/yas/geo/__init__.py`
- Create: `src/yas/geo/distance.py`
- Create: `tests/unit/test_distance.py`

- [ ] **Step 1: Test**

`tests/unit/test_distance.py`:

```python
import pytest

from yas.geo.distance import great_circle_miles


def test_same_point_zero():
    assert great_circle_miles(41.88, -87.63, 41.88, -87.63) == pytest.approx(0.0, abs=0.001)


def test_known_chicago_to_nyc():
    # Chicago (41.88, -87.63) to NYC (40.71, -74.01) ≈ 712 miles
    d = great_circle_miles(41.88, -87.63, 40.71, -74.01)
    assert 700 < d < 725


def test_short_urban_distance():
    # ~1 mile apart
    d = great_circle_miles(41.881, -87.630, 41.881, -87.611)
    assert 0.8 < d < 1.2


def test_symmetry():
    d1 = great_circle_miles(41.88, -87.63, 40.71, -74.01)
    d2 = great_circle_miles(40.71, -74.01, 41.88, -87.63)
    assert d1 == pytest.approx(d2)
```

- [ ] **Step 2: Empty `src/yas/geo/__init__.py`**

- [ ] **Step 3: Implement `src/yas/geo/distance.py`**

```python
"""Pure haversine great-circle distance in miles."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

_EARTH_MILES = 3958.7613


def great_circle_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lat2_r = radians(lat1), radians(lat2)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2) ** 2
    return 2 * _EARTH_MILES * asin(sqrt(a))
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/unit/test_distance.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/geo/__init__.py src/yas/geo/distance.py tests/unit/test_distance.py
git commit -m "feat(geo): add haversine distance"
```

---

## Task 6 — Nominatim client

**Files:**
- Create: `src/yas/geo/client.py`
- Create: `tests/unit/test_nominatim_client.py`

- [ ] **Step 1: Tests**

`tests/unit/test_nominatim_client.py`:

```python
import asyncio

import httpx
import pytest
import respx

from yas.geo.client import GeocodeResult, NominatimClient


_OK_PAYLOAD = [
    {"lat": "41.8781", "lon": "-87.6298", "display_name": "Chicago, IL, USA"},
]


@pytest.mark.asyncio
@respx.mock
async def test_happy_path():
    respx.get(NominatimClient.BASE_URL).mock(return_value=httpx.Response(200, json=_OK_PAYLOAD))
    client = NominatimClient(min_interval_s=0.0)
    try:
        r = await client.geocode("Chicago, IL")
        assert isinstance(r, GeocodeResult)
        assert r.lat == pytest.approx(41.8781)
        assert r.lon == pytest.approx(-87.6298)
        assert r.provider == "nominatim"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_empty_result_returns_none():
    respx.get(NominatimClient.BASE_URL).mock(return_value=httpx.Response(200, json=[]))
    client = NominatimClient(min_interval_s=0.0)
    try:
        assert await client.geocode("Nowheresville, XX") is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_transport_error_retries_once_then_returns_none():
    route = respx.get(NominatimClient.BASE_URL).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.ConnectError("boom")],
    )
    client = NominatimClient(min_interval_s=0.0)
    try:
        result = await client.geocode("Chicago")
        assert result is None
        assert route.call_count == 2    # one retry
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_429_doubles_interval():
    respx.get(NominatimClient.BASE_URL).mock(return_value=httpx.Response(429))
    client = NominatimClient(min_interval_s=0.1)
    try:
        assert await client.geocode("anywhere") is None
        # session interval doubled (0.1 → 0.2), capped at 10s
        assert client._min_interval_s >= 0.2
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit_serializes_concurrent_calls():
    respx.get(NominatimClient.BASE_URL).mock(return_value=httpx.Response(200, json=_OK_PAYLOAD))
    client = NominatimClient(min_interval_s=0.2)
    try:
        start = asyncio.get_event_loop().time()
        await asyncio.gather(client.geocode("a"), client.geocode("b"), client.geocode("c"))
        elapsed = asyncio.get_event_loop().time() - start
        # Three calls × 0.2s interval → at least 0.4s wall clock (first free, two spaced)
        assert elapsed >= 0.35
    finally:
        await client.aclose()
```

- [ ] **Step 2: Run — expect import errors**

- [ ] **Step 3: Implement `src/yas/geo/client.py`**

```python
"""Geocoder protocol and Nominatim-backed client.

Respects Nominatim's usage policy: 1 req/s max, identifying User-Agent.
Rate-limit is internal (asyncio.Lock + monotonic timestamp). Failures
(transport, HTTP, parse) return None and are reported separately by
the enricher via geocode_attempts.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lon: float
    display_name: str
    provider: str  # "nominatim"


class Geocoder(Protocol):
    async def geocode(self, address: str) -> GeocodeResult | None: ...


class NominatimClient:
    BASE_URL = "https://nominatim.openstreetmap.org/search"
    USER_AGENT = "yas/0.1 (+https://github.com/example/youth-activity-scheduler)"
    _MAX_INTERVAL_S = 10.0

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        min_interval_s: float = 1.0,
    ) -> None:
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            headers={"User-Agent": self.USER_AGENT},
            timeout=httpx.Timeout(15.0),
        )
        self._min_interval_s = min_interval_s
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def geocode(self, address: str) -> GeocodeResult | None:
        await self._wait_turn()
        return await self._do_geocode(address, attempt=0)

    async def _wait_turn(self) -> None:
        async with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._min_interval_s:
                await asyncio.sleep(self._min_interval_s - elapsed)
            self._last_request_at = time.monotonic()

    async def _do_geocode(self, address: str, *, attempt: int) -> GeocodeResult | None:
        params = {"q": address, "format": "json", "limit": 1}
        try:
            r = await self._http.get(self.BASE_URL, params=params)
        except httpx.TransportError:
            if attempt == 0:
                await asyncio.sleep(2.0)
                return await self._do_geocode(address, attempt=1)
            return None
        if r.status_code == 429:
            self._min_interval_s = min(self._min_interval_s * 2 or 1.0, self._MAX_INTERVAL_S)
            return None
        if r.status_code >= 400:
            return None
        try:
            data = r.json()
        except Exception:  # noqa: BLE001
            return None
        if not data:
            return None
        item = data[0]
        try:
            return GeocodeResult(
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                display_name=str(item.get("display_name", "")),
                provider="nominatim",
            )
        except (KeyError, TypeError, ValueError):
            return None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/unit/test_nominatim_client.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/geo/client.py tests/unit/test_nominatim_client.py
git commit -m "feat(geo): add Nominatim client with 1 req/s rate limit"
```

---

## Task 7 — Geocode enricher + FakeGeocoder

**Files:**
- Create: `tests/fakes/geocoder.py`
- Create: `src/yas/geo/enricher.py`
- Create: `tests/integration/test_enricher.py`

This task depends on a `GeocodeAttempt` SQLAlchemy model for the `geocode_attempts` table. **Create it first as part of this task** under `src/yas/db/models/geocode_attempt.py`, then register it in `db/models/__init__.py`. (The table was created by the Task 1 migration; we add the model now, not earlier, to keep tasks focused.)

- [ ] **Step 1: Add the `GeocodeAttempt` model**

Create `src/yas/db/models/geocode_attempt.py`:

```python
"""Negative-cache row for addresses Nominatim couldn't resolve."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base


class GeocodeAttempt(Base):
    __tablename__ = "geocode_attempts"

    address_norm: Mapped[str] = mapped_column(String, primary_key=True)
    last_tried: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[str] = mapped_column(String, nullable=False)       # "ok" | "not_found" | "error"
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
```

Register it in `src/yas/db/models/__init__.py` alongside the existing models: add import + `__all__` entry.

- [ ] **Step 2: Create `tests/fakes/geocoder.py`**

```python
"""FakeGeocoder — scripted responses for integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from yas.geo.client import GeocodeResult


@dataclass
class FakeGeocoder:
    fixtures: dict[str, GeocodeResult] = field(default_factory=dict)
    misses: set[str] = field(default_factory=set)
    errors: set[str] = field(default_factory=set)
    call_count: int = 0

    async def geocode(self, address: str) -> GeocodeResult | None:
        self.call_count += 1
        key = address.lower().strip()
        if key in self.errors:
            raise RuntimeError(f"simulated geocode error for {address!r}")
        if key in self.misses:
            return None
        return self.fixtures.get(key)
```

- [ ] **Step 3: Failing integration test**

`tests/integration/test_enricher.py`:

```python
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tests.fakes.geocoder import FakeGeocoder
from yas.crawl.normalize import normalize_name
from yas.db.base import Base
from yas.db.models import GeocodeAttempt, Location, Offering, Page, Site
from yas.db.session import create_engine_for, session_scope
from yas.geo.client import GeocodeResult
from yas.geo.enricher import enrich_ungeocoded_locations


async def _setup(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/e.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_enricher_populates_coords(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="Lincoln Park Rec", address="2045 N Lincoln Park W, Chicago, IL"))
    geocoder = FakeGeocoder(fixtures={
        "2045 n lincoln park w, chicago, il": GeocodeResult(
            lat=41.9214, lon=-87.6351, display_name="Lincoln Park", provider="fake",
        )
    })
    async with session_scope(engine) as s:
        result = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert result.updated == 1
    async with session_scope(engine) as s:
        loc = (await s.execute(select(Location))).scalar_one()
        assert loc.lat == pytest.approx(41.9214)
        assert loc.lon == pytest.approx(-87.6351)
    await engine.dispose()


@pytest.mark.asyncio
async def test_enricher_records_not_found_and_skips_on_retry(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="X", address="Nowheresville, XX"))
    geocoder = FakeGeocoder(misses={"nowheresville, xx"})
    async with session_scope(engine) as s:
        r1 = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert r1.not_found == 1
    async with session_scope(engine) as s:
        r2 = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert r2.skipped == 1   # skipped due to prior not_found
    async with session_scope(engine) as s:
        rows = (await s.execute(select(GeocodeAttempt))).scalars().all()
        assert len(rows) == 1
        assert rows[0].result == "not_found"
    assert geocoder.call_count == 1   # second call skipped
    await engine.dispose()


@pytest.mark.asyncio
async def test_enricher_records_error(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="X", address="error-please"))
    geocoder = FakeGeocoder(errors={"error-please"})
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert r.errored == 1
    async with session_scope(engine) as s:
        rows = (await s.execute(select(GeocodeAttempt))).scalars().all()
        assert len(rows) == 1
        assert rows[0].result == "error"
    await engine.dispose()
```

- [ ] **Step 4: Implement `src/yas/geo/enricher.py`**

```python
"""Geocode the locations table, in batches, and record negative cache rows.

Triggers matcher.rematch_offering for each offering at a location that just
gained coordinates."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from yas.config import Settings
from yas.crawl.normalize import normalize_name
from yas.db.models import GeocodeAttempt, Location, Offering
from yas.db.session import session_scope
from yas.geo.client import Geocoder
from yas.logging import get_logger

log = get_logger("yas.geo.enricher")


@dataclass(frozen=True)
class EnrichResult:
    updated: int
    not_found: int
    errored: int
    skipped: int


async def enrich_ungeocoded_locations(
    session: AsyncSession,
    geocoder: Geocoder,
    *,
    batch_size: int = 20,
    on_rematch: "callable | None" = None,
) -> EnrichResult:
    updated = 0
    not_found = 0
    errored = 0
    skipped = 0

    locations = (
        await session.execute(
            select(Location).where(Location.lat.is_(None)).where(Location.address.isnot(None)).limit(batch_size)
        )
    ).scalars().all()

    for loc in locations:
        addr_norm = normalize_name(loc.address or "")
        prior = (
            await session.execute(
                select(GeocodeAttempt).where(GeocodeAttempt.address_norm == addr_norm)
            )
        ).scalar_one_or_none()
        if prior is not None and prior.result in {"not_found", "error"}:
            skipped += 1
            continue
        try:
            result = await geocoder.geocode(loc.address or "")
        except Exception as exc:  # noqa: BLE001
            errored += 1
            session.add(GeocodeAttempt(
                address_norm=addr_norm, last_tried=datetime.now(UTC),
                result="error", detail=str(exc)[:500],
            ))
            continue
        if result is None:
            not_found += 1
            if prior is None:
                session.add(GeocodeAttempt(
                    address_norm=addr_norm, last_tried=datetime.now(UTC),
                    result="not_found",
                ))
            else:
                prior.last_tried = datetime.now(UTC)
                prior.result = "not_found"
            continue
        loc.lat = result.lat
        loc.lon = result.lon
        updated += 1
        if prior is None:
            session.add(GeocodeAttempt(
                address_norm=addr_norm, last_tried=datetime.now(UTC), result="ok",
            ))
        else:
            prior.last_tried = datetime.now(UTC)
            prior.result = "ok"
        if on_rematch is not None:
            offering_ids = (
                await session.execute(select(Offering.id).where(Offering.location_id == loc.id))
            ).scalars().all()
            for oid in offering_ids:
                await on_rematch(session, oid)

    return EnrichResult(updated=updated, not_found=not_found, errored=errored, skipped=skipped)


async def geocode_enricher_loop(
    engine: AsyncEngine, settings: Settings, geocoder: Geocoder,
) -> None:
    from yas.matching.matcher import rematch_offering  # local import to avoid cycles

    log.info("geocode.start",
             tick_s=settings.geocode_tick_s,
             batch_size=settings.geocode_batch_size)
    try:
        while True:
            async with session_scope(engine) as s:
                result = await enrich_ungeocoded_locations(
                    s, geocoder, batch_size=settings.geocode_batch_size,
                    on_rematch=rematch_offering,
                )
            if result.updated or result.not_found or result.errored:
                log.info("geocode.tick",
                         updated=result.updated, not_found=result.not_found,
                         errored=result.errored, skipped=result.skipped)
            await asyncio.sleep(settings.geocode_tick_s)
    except asyncio.CancelledError:
        log.info("geocode.stop")
        raise
```

> `on_rematch` is an injection seam so this file doesn't force an import of the matcher until the full orchestrator lands in Task 10. The enricher loop imports locally.

- [ ] **Step 5: Run + commit**

```bash
uv run pytest tests/integration/test_enricher.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/db/models/geocode_attempt.py src/yas/db/models/__init__.py \
    tests/fakes/geocoder.py src/yas/geo/enricher.py tests/integration/test_enricher.py
git commit -m "feat(geo): add enricher with negative-cache persistence"
```

---

## Task 8 — School-block materializer

**Files:**
- Create: `src/yas/unavailability/__init__.py`
- Create: `src/yas/unavailability/school_materializer.py`
- Create: `tests/unit/test_school_materializer.py`

- [ ] **Step 1: Test**

```python
# tests/unit/test_school_materializer.py
from datetime import date, time

import pytest
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import Kid, UnavailabilityBlock
from yas.db.models._types import UnavailabilitySource
from yas.db.session import create_engine_for, session_scope
from yas.unavailability.school_materializer import materialize_school_blocks


async def _setup(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/s.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
    return engine


@pytest.mark.asyncio
async def test_no_school_info_produces_zero_blocks(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await materialize_school_blocks(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(
            select(UnavailabilityBlock).where(UnavailabilityBlock.source == UnavailabilitySource.school.value)
        )).scalars().all()
        assert rows == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_materializes_one_block_per_year_range(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = (await s.execute(select(Kid))).scalar_one()
        kid.school_time_start = time(8, 0)
        kid.school_time_end = time(15, 0)
        kid.school_year_ranges = [
            {"start": "2026-09-02", "end": "2027-06-14"},
            {"start": "2027-09-01", "end": "2028-06-13"},
        ]
    async with session_scope(engine) as s:
        await materialize_school_blocks(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(
            select(UnavailabilityBlock).where(UnavailabilityBlock.source == UnavailabilitySource.school.value)
        )).scalars().all()
        assert len(rows) == 2
        for r in rows:
            assert r.time_start == time(8, 0)
            assert r.time_end == time(15, 0)
            assert r.days_of_week == ["mon", "tue", "wed", "thu", "fri"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_rewrites_on_second_call(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = (await s.execute(select(Kid))).scalar_one()
        kid.school_time_start = time(8, 0)
        kid.school_time_end = time(15, 0)
        kid.school_year_ranges = [{"start": "2026-09-02", "end": "2027-06-14"}]
    async with session_scope(engine) as s:
        await materialize_school_blocks(s, kid_id=1)
    # change the schedule
    async with session_scope(engine) as s:
        kid = (await s.execute(select(Kid))).scalar_one()
        kid.school_time_start = time(9, 0)
        kid.school_time_end = time(16, 0)
    async with session_scope(engine) as s:
        await materialize_school_blocks(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(
            select(UnavailabilityBlock).where(UnavailabilityBlock.source == UnavailabilitySource.school.value)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].time_start == time(9, 0)
        assert rows[0].time_end == time(16, 0)
    await engine.dispose()


@pytest.mark.asyncio
async def test_partial_school_info_produces_zero_blocks(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = (await s.execute(select(Kid))).scalar_one()
        kid.school_time_start = time(8, 0)
        # school_time_end left null
        kid.school_year_ranges = [{"start": "2026-09-02", "end": "2027-06-14"}]
    async with session_scope(engine) as s:
        await materialize_school_blocks(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(
            select(UnavailabilityBlock).where(UnavailabilityBlock.source == UnavailabilitySource.school.value)
        )).scalars().all()
        assert rows == []
    await engine.dispose()
```

- [ ] **Step 2: Empty `src/yas/unavailability/__init__.py`**

- [ ] **Step 3: Implement `src/yas/unavailability/school_materializer.py`**

```python
"""Delete-and-rewrite the source=school unavailability blocks for one kid."""

from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Kid, UnavailabilityBlock
from yas.db.models._types import UnavailabilitySource


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


async def materialize_school_blocks(session: AsyncSession, kid_id: int) -> None:
    """Idempotent rewrite of all source=school blocks for this kid."""
    kid = (await session.execute(select(Kid).where(Kid.id == kid_id))).scalar_one()

    await session.execute(
        delete(UnavailabilityBlock).where(
            UnavailabilityBlock.kid_id == kid_id,
            UnavailabilityBlock.source == UnavailabilitySource.school.value,
        )
    )

    if kid.school_time_start is None or kid.school_time_end is None:
        return
    if not kid.school_year_ranges:
        return

    weekdays = kid.school_weekdays or ["mon", "tue", "wed", "thu", "fri"]
    for entry in kid.school_year_ranges:
        start = _parse_date(entry["start"])
        end = _parse_date(entry["end"])
        session.add(UnavailabilityBlock(
            kid_id=kid_id,
            source=UnavailabilitySource.school.value,
            label=f"School {start.isoformat()}..{end.isoformat()}",
            days_of_week=weekdays,
            time_start=kid.school_time_start,
            time_end=kid.school_time_end,
            date_start=start,
            date_end=end,
            active=True,
        ))
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/unit/test_school_materializer.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/unavailability/ tests/unit/test_school_materializer.py
git commit -m "feat(unavailability): add school-block materializer"
```

---

## Task 9 — Enrollment-block materializer

**Files:**
- Create: `src/yas/unavailability/enrollment_materializer.py`
- Create: `tests/unit/test_enrollment_materializer.py`

- [ ] **Step 1: Test**

```python
# tests/unit/test_enrollment_materializer.py
from datetime import date, time

import pytest
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import Enrollment, Kid, Offering, Page, Site, UnavailabilityBlock
from yas.db.models._types import EnrollmentStatus, UnavailabilitySource
from yas.db.session import create_engine_for, session_scope
from yas.unavailability.enrollment_materializer import apply_enrollment_block


async def _setup(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/e.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        site = Site(id=1, name="X", base_url="https://x")
        s.add(site)
        await s.flush()
        page = Page(id=1, site_id=1, url="https://x/p")
        s.add(page)
        await s.flush()
        s.add(Offering(
            id=1, site_id=1, page_id=1,
            name="Sat Soccer", normalized_name="sat soccer",
            start_date=date(2026, 5, 1), end_date=date(2026, 6, 30),
            days_of_week=["sat"], time_start=time(9, 0), time_end=time(10, 0),
        ))
        s.add(Enrollment(id=1, kid_id=1, offering_id=1, status=EnrollmentStatus.interested.value))
    return engine


@pytest.mark.asyncio
async def test_interested_does_not_create_block(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await apply_enrollment_block(s, enrollment_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert rows == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_enrolled_creates_block(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        e = (await s.execute(select(Enrollment))).scalar_one()
        e.status = EnrollmentStatus.enrolled.value
    async with session_scope(engine) as s:
        await apply_enrollment_block(s, enrollment_id=1)
    async with session_scope(engine) as s:
        blocks = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert len(blocks) == 1
        b = blocks[0]
        assert b.source == UnavailabilitySource.enrollment.value
        assert b.source_enrollment_id == 1
        assert b.days_of_week == ["sat"]
        assert b.time_start == time(9, 0)
        assert b.date_start == date(2026, 5, 1)
    await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_deletes_block(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        e = (await s.execute(select(Enrollment))).scalar_one()
        e.status = EnrollmentStatus.enrolled.value
    async with session_scope(engine) as s:
        await apply_enrollment_block(s, enrollment_id=1)
    async with session_scope(engine) as s:
        e = (await s.execute(select(Enrollment))).scalar_one()
        e.status = EnrollmentStatus.cancelled.value
    async with session_scope(engine) as s:
        await apply_enrollment_block(s, enrollment_id=1)
    async with session_scope(engine) as s:
        blocks = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert blocks == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_on_second_call(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        e = (await s.execute(select(Enrollment))).scalar_one()
        e.status = EnrollmentStatus.enrolled.value
    async with session_scope(engine) as s:
        await apply_enrollment_block(s, enrollment_id=1)
    async with session_scope(engine) as s:
        await apply_enrollment_block(s, enrollment_id=1)
    async with session_scope(engine) as s:
        blocks = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert len(blocks) == 1
    await engine.dispose()
```

- [ ] **Step 2: Implement `src/yas/unavailability/enrollment_materializer.py`**

```python
"""Create, update, or remove a source=enrollment block for an enrollment."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Enrollment, Offering, UnavailabilityBlock
from yas.db.models._types import EnrollmentStatus, UnavailabilitySource


async def apply_enrollment_block(session: AsyncSession, enrollment_id: int) -> None:
    enrollment = (
        await session.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
    ).scalar_one()

    existing = (
        await session.execute(
            select(UnavailabilityBlock).where(UnavailabilityBlock.source_enrollment_id == enrollment_id)
        )
    ).scalar_one_or_none()

    status = getattr(enrollment.status, "value", enrollment.status)
    if status != EnrollmentStatus.enrolled.value:
        if existing is not None:
            await session.delete(existing)
        return

    offering = (
        await session.execute(select(Offering).where(Offering.id == enrollment.offering_id))
    ).scalar_one()

    if existing is None:
        session.add(UnavailabilityBlock(
            kid_id=enrollment.kid_id,
            source=UnavailabilitySource.enrollment.value,
            source_enrollment_id=enrollment.id,
            label=f"Enrolled: {offering.name}",
            days_of_week=list(offering.days_of_week or []),
            time_start=offering.time_start,
            time_end=offering.time_end,
            date_start=offering.start_date,
            date_end=offering.end_date,
            active=True,
        ))
    else:
        existing.kid_id = enrollment.kid_id
        existing.label = f"Enrolled: {offering.name}"
        existing.days_of_week = list(offering.days_of_week or [])
        existing.time_start = offering.time_start
        existing.time_end = offering.time_end
        existing.date_start = offering.start_date
        existing.date_end = offering.end_date
        existing.active = True
```

- [ ] **Step 3: Run + commit**

```bash
uv run pytest tests/unit/test_enrollment_materializer.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/unavailability/enrollment_materializer.py tests/unit/test_enrollment_materializer.py
git commit -m "feat(unavailability): add enrollment-block materializer"
```

---

## Task 10 — Matcher orchestrator

The keystone: the three public `async` functions that compose all pure pieces from Tasks 2–6/8–9, read necessary rows from the DB, evaluate the (kid, offering) cross-product, and upsert/delete `matches` rows.

**Files:**
- Create: `src/yas/matching/matcher.py`
- Create: `tests/integration/test_matcher.py`

- [ ] **Step 1: Integration tests (failing)**

`tests/integration/test_matcher.py`:

```python
from datetime import date, time

import pytest
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import (
    Enrollment, HouseholdSettings, Kid, Location, Match, Offering, Page, Site,
    UnavailabilityBlock, WatchlistEntry,
)
from yas.db.models._types import (
    EnrollmentStatus, OfferingStatus, ProgramType, UnavailabilitySource, WatchlistPriority,
)
from yas.db.session import create_engine_for, session_scope
from yas.matching.matcher import rematch_kid, rematch_offering


async def _setup(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/m.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(HouseholdSettings(id=1, default_max_distance_mi=20.0))
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
    return engine


async def _kid(session, **kwargs):
    defaults = dict(name="Sam", dob=date(2019, 5, 1), interests=["soccer"], active=True)
    defaults.update(kwargs)
    k = Kid(**defaults)
    session.add(k)
    await session.flush()
    return k


async def _offering(session, **kwargs):
    defaults = dict(
        site_id=1, page_id=1, name="Spring Soccer", normalized_name="spring soccer",
        program_type=ProgramType.soccer.value, age_min=6, age_max=8,
        start_date=date(2026, 5, 1), end_date=date(2026, 6, 30),
        days_of_week=["sat"], time_start=time(9, 0), time_end=time(10, 0),
        status=OfferingStatus.active.value,
    )
    defaults.update(kwargs)
    o = Offering(**defaults)
    session.add(o)
    await session.flush()
    return o


@pytest.mark.asyncio
async def test_rematch_kid_writes_matching_row(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = await _kid(s)
        offering = await _offering(s)
    async with session_scope(engine) as s:
        result = await rematch_kid(s, kid_id=1)
    assert len(result.new) == 1
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Match))).scalars().all()
        assert len(rows) == 1
        assert rows[0].kid_id == 1
        assert 0.0 <= rows[0].score <= 1.0
        assert "gates" in rows[0].reasons
        assert "score_breakdown" in rows[0].reasons
    await engine.dispose()


@pytest.mark.asyncio
async def test_age_gate_uses_start_date(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        # kid is 4 today but turns 5 on 2026-05-01
        await _kid(s, dob=date(2021, 5, 1), interests=["soccer"])
        await _offering(s, age_min=5, start_date=date(2026, 5, 15))
    async with session_scope(engine) as s:
        await rematch_kid(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Match))).scalars().all()
        assert len(rows) == 1   # matched despite today's age = 4


@pytest.mark.asyncio
async def test_summer_offering_passes_school_year_gate(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = await _kid(s, interests=["soccer"])
        # school block covers 2026-09..2027-06
        s.add(UnavailabilityBlock(
            kid_id=kid.id, source=UnavailabilitySource.school.value,
            days_of_week=["mon","tue","wed","thu","fri"],
            time_start=time(8,0), time_end=time(15,0),
            date_start=date(2026,9,2), date_end=date(2027,6,14),
        ))
        await _offering(s,
            start_date=date(2026, 6, 15), end_date=date(2026, 8, 15),
            days_of_week=["mon","wed"], time_start=time(9,0), time_end=time(12,0),
        )
    async with session_scope(engine) as s:
        await rematch_kid(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Match))).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_watchlist_bypasses_all_hard_gates(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = await _kid(s, interests=["swim"], max_distance_mi=1.0)   # not soccer; tiny distance
        # location with unavailable coords so distance stays unknown = fail-open on distance
        s.add(WatchlistEntry(
            id=1, kid_id=kid.id, pattern="spring soccer",
            priority=WatchlistPriority.high.value, active=True, ignore_hard_gates=False,
        ))
        await _offering(s)   # program_type soccer, age 6-8 (kid is 6 on 2026-05-01)
    async with session_scope(engine) as s:
        await rematch_kid(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Match))).scalars().all()
        assert len(rows) == 1
        assert rows[0].reasons.get("watchlist_hit") is not None


@pytest.mark.asyncio
async def test_enrollment_block_prevents_sibling_match(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid_a = await _kid(s, interests=["soccer"])
        kid_b = await _kid(s, name="Kid B", dob=date(2019, 5, 1), interests=["soccer"])
        sat_9 = await _offering(s, name="Sat 9am Soccer")
        sat_9_other = await _offering(s, name="Sat 9am Other Soccer")
        s.add(Enrollment(
            id=1, kid_id=kid_a.id, offering_id=sat_9.id, status=EnrollmentStatus.enrolled.value,
        ))
        await s.flush()
        # materialize the enrollment block manually (avoiding materializer coupling here)
        s.add(UnavailabilityBlock(
            kid_id=kid_a.id, source=UnavailabilitySource.enrollment.value,
            source_enrollment_id=1,
            days_of_week=["sat"], time_start=time(9,0), time_end=time(10,0),
            date_start=date(2026,5,1), date_end=date(2026,6,30),
        ))
    async with session_scope(engine) as s:
        await rematch_kid(s, kid_id=kid_a.id)
        await rematch_kid(s, kid_id=kid_b.id)
    async with session_scope(engine) as s:
        # Kid A matches the enrolled offering (obviously) but not the conflicting sibling
        rows_a = (await s.execute(select(Match).where(Match.kid_id == kid_a.id))).scalars().all()
        assert {m.offering_id for m in rows_a} == {sat_9.id}   # conflicting sibling filtered
        # Kid B is unaffected and matches both soccer offerings
        rows_b = (await s.execute(select(Match).where(Match.kid_id == kid_b.id))).scalars().all()
        assert {m.offering_id for m in rows_b} == {sat_9.id, sat_9_other.id}


@pytest.mark.asyncio
async def test_failed_gate_removes_existing_match(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = await _kid(s, interests=["soccer"])
        await _offering(s)
    async with session_scope(engine) as s:
        await rematch_kid(s, kid_id=1)
    async with session_scope(engine) as s:
        # change the kid to a different age so the match should drop
        kid = (await s.execute(select(Kid))).scalar_one()
        kid.dob = date(2010, 1, 1)   # kid is ~16
    async with session_scope(engine) as s:
        await rematch_kid(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Match))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_rematch_offering_touches_all_kids(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await _kid(s)
        await _kid(s, name="Sib", interests=["soccer"])
        await _offering(s)
    async with session_scope(engine) as s:
        await rematch_offering(s, offering_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Match))).scalars().all()
        assert len(rows) == 2
```

- [ ] **Step 2: Implement `src/yas/matching/matcher.py`**

```python
"""Matcher orchestrator — composes gates + scoring + watchlist into matches rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import (
    HouseholdSettings, Kid, Location, Match, Offering, UnavailabilityBlock, WatchlistEntry,
)
from yas.db.models._types import OfferingStatus
from yas.geo.distance import great_circle_miles
from yas.matching.aliases import INTEREST_ALIASES
from yas.matching.gates import (
    GateResult, age_fits, distance_fits, interests_overlap,
    no_conflict_with_unavailability, offering_active_and_not_ended,
)
from yas.matching.scoring import compute_score
from yas.matching.watchlist import matches_watchlist


@dataclass(frozen=True)
class MatchResult:
    kid_id: int | None = None
    offering_id: int | None = None
    new: list[tuple[int, int]] = field(default_factory=list)
    updated: list[tuple[int, int]] = field(default_factory=list)
    removed: list[tuple[int, int]] = field(default_factory=list)


async def _household_defaults(session: AsyncSession) -> tuple[int | None, float | None]:
    hh = (await session.execute(select(HouseholdSettings))).scalars().first()
    if hh is None:
        return None, None
    return hh.home_location_id, hh.default_max_distance_mi


async def _home_coords(session: AsyncSession, home_id: int | None) -> tuple[float, float] | None:
    if home_id is None:
        return None
    loc = (await session.execute(select(Location).where(Location.id == home_id))).scalar_one_or_none()
    if loc is None or loc.lat is None or loc.lon is None:
        return None
    return (loc.lat, loc.lon)


async def _offering_coords(session: AsyncSession, offering: Offering) -> tuple[float, float] | None:
    if offering.location_id is None:
        return None
    loc = (await session.execute(select(Location).where(Location.id == offering.location_id))).scalar_one_or_none()
    if loc is None or loc.lat is None or loc.lon is None:
        return None
    return (loc.lat, loc.lon)


async def _compute_distance_mi(
    session: AsyncSession, home: tuple[float, float] | None, offering: Offering,
) -> float | None:
    if home is None:
        return None
    coords = await _offering_coords(session, offering)
    if coords is None:
        return None
    return great_circle_miles(home[0], home[1], coords[0], coords[1])


async def _kid_blocks(session: AsyncSession, kid_id: int) -> list[UnavailabilityBlock]:
    return list((await session.execute(
        select(UnavailabilityBlock).where(UnavailabilityBlock.kid_id == kid_id)
    )).scalars().all())


async def _kid_watchlist(session: AsyncSession, kid_id: int) -> list[WatchlistEntry]:
    return list((await session.execute(
        select(WatchlistEntry).where(WatchlistEntry.kid_id == kid_id)
    )).scalars().all())


def _school_holidays(kid: Kid) -> set[date]:
    result: set[date] = set()
    for d in kid.school_holidays or []:
        try:
            result.add(date.fromisoformat(d) if isinstance(d, str) else d)
        except Exception:  # noqa: BLE001
            continue
    return result


async def _eligible_offerings(session: AsyncSession) -> list[Offering]:
    return list((await session.execute(
        select(Offering).where(Offering.status == OfferingStatus.active.value)
    )).scalars().all())


async def _active_kids(session: AsyncSession) -> list[Kid]:
    return list((await session.execute(
        select(Kid).where(Kid.active.is_(True))
    )).scalars().all())


def _gates_passed(gates: list[GateResult]) -> bool:
    return all(g.passed for g in gates)


def _reasons_payload(
    gates: list[GateResult], score_bd: dict[str, Any], watchlist_hit: Any,
) -> dict[str, Any]:
    return {
        "gates": {g.code: {"passed": g.passed, "detail": g.detail} for g in gates},
        "score_breakdown": score_bd,
        "watchlist_hit": (
            {
                "entry_id": watchlist_hit.entry.id,
                "pattern": watchlist_hit.entry.pattern,
                "match_type": watchlist_hit.reason,
                "priority": getattr(watchlist_hit.entry.priority, "value", watchlist_hit.entry.priority),
            } if watchlist_hit else None
        ),
    }


async def _evaluate_pair(
    session: AsyncSession, kid: Kid, offering: Offering, *,
    home: tuple[float, float] | None, default_max_distance: float | None,
    today: date,
    # Optional precomputed per-kid state (hoisted by rematch_kid for N-offering loops).
    blocks: list[UnavailabilityBlock] | None = None,
    watchlist_entries: list[WatchlistEntry] | None = None,
    school_holidays: set[date] | None = None,
) -> tuple[bool, float, dict[str, Any]]:
    distance_mi = await _compute_distance_mi(session, home, offering)
    if blocks is None:
        blocks = await _kid_blocks(session, kid.id)
    if watchlist_entries is None:
        watchlist_entries = await _kid_watchlist(session, kid.id)
    if school_holidays is None:
        school_holidays = _school_holidays(kid)
    watchlist = matches_watchlist(offering, watchlist_entries, site_id=offering.site_id)

    gates = [
        age_fits(kid, offering, today=today),
        distance_fits(kid, offering, distance_mi=distance_mi, household_default=default_max_distance),
        interests_overlap(kid, offering, INTEREST_ALIASES),
        offering_active_and_not_ended(offering, today=today),
        no_conflict_with_unavailability(offering, blocks, school_holidays, today=today),
    ]
    score, breakdown = compute_score(
        kid, offering,
        distance_mi=distance_mi,
        household_max_distance_mi=default_max_distance,
        today=today,
    )
    include = watchlist is not None or _gates_passed(gates)
    reasons = _reasons_payload(gates, breakdown, watchlist)
    return include, score, reasons


async def _upsert_match(session: AsyncSession, kid_id: int, offering_id: int,
                        score: float, reasons: dict[str, Any]) -> bool:
    """Returns True if new (insert), False if existing row updated."""
    existing = (await session.execute(
        select(Match).where(Match.kid_id == kid_id, Match.offering_id == offering_id)
    )).scalar_one_or_none()
    now = datetime.now(UTC)
    if existing is None:
        session.add(Match(kid_id=kid_id, offering_id=offering_id,
                          score=score, reasons=reasons, computed_at=now))
        return True
    existing.score = score
    existing.reasons = reasons
    existing.computed_at = now
    return False


async def _delete_match_if_exists(session: AsyncSession, kid_id: int, offering_id: int) -> bool:
    existing = (await session.execute(
        select(Match).where(Match.kid_id == kid_id, Match.offering_id == offering_id)
    )).scalar_one_or_none()
    if existing is None:
        return False
    await session.delete(existing)
    return True


async def rematch_kid(session: AsyncSession, kid_id: int, *, today: date | None = None) -> MatchResult:
    kid = (await session.execute(select(Kid).where(Kid.id == kid_id))).scalar_one()
    if today is None:
        today = date.today()
    home_id, default_distance = await _household_defaults(session)
    home = await _home_coords(session, home_id)
    offerings = await _eligible_offerings(session)
    # Hoist per-kid queries out of the per-offering loop.
    blocks = await _kid_blocks(session, kid_id)
    watchlist_entries = await _kid_watchlist(session, kid_id)
    school_holidays = _school_holidays(kid)
    result = MatchResult(kid_id=kid_id)
    for off in offerings:
        include, score, reasons = await _evaluate_pair(
            session, kid, off,
            home=home, default_max_distance=default_distance, today=today,
            blocks=blocks, watchlist_entries=watchlist_entries, school_holidays=school_holidays,
        )
        key = (kid_id, off.id)
        if include:
            inserted = await _upsert_match(session, kid_id, off.id, score, reasons)
            (result.new if inserted else result.updated).append(key)
        else:
            if await _delete_match_if_exists(session, kid_id, off.id):
                result.removed.append(key)
    return result


async def rematch_offering(session: AsyncSession, offering_id: int, *, today: date | None = None) -> MatchResult:
    off = (await session.execute(select(Offering).where(Offering.id == offering_id))).scalar_one()
    if today is None:
        today = date.today()
    home_id, default_distance = await _household_defaults(session)
    home = await _home_coords(session, home_id)
    result = MatchResult(offering_id=offering_id)
    for kid in await _active_kids(session):
        include, score, reasons = await _evaluate_pair(
            session, kid, off, home=home, default_max_distance=default_distance, today=today,
        )
        key = (kid.id, offering_id)
        if include:
            inserted = await _upsert_match(session, kid.id, offering_id, score, reasons)
            (result.new if inserted else result.updated).append(key)
        else:
            if await _delete_match_if_exists(session, kid.id, offering_id):
                result.removed.append(key)
    return result


async def rematch_all_active_kids(session: AsyncSession, *, today: date | None = None) -> list[MatchResult]:
    results: list[MatchResult] = []
    for kid in await _active_kids(session):
        results.append(await rematch_kid(session, kid.id, today=today))
    return results
```

- [ ] **Step 3: Run + commit**

```bash
uv run pytest tests/integration/test_matcher.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/matching/matcher.py tests/integration/test_matcher.py
git commit -m "feat(matching): add matcher orchestrator composing gates+scoring+watchlist"
```

---

## Task 11 — Household HTTP API + immediate geocode

**Files:**
- Create: `src/yas/web/routes/household_schemas.py`
- Create: `src/yas/web/routes/household.py`
- Modify: `src/yas/web/routes/__init__.py` (export new router)
- Modify: `src/yas/web/app.py` (include new router)
- Modify: `src/yas/web/deps.py` (AppState gains `geocoder` field)
- Create: `tests/integration/test_api_household.py`

- [ ] **Step 1: Failing API test**

`tests/integration/test_api_household.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.fakes.geocoder import FakeGeocoder
from yas.db.base import Base
from yas.db.models import HouseholdSettings, Location
from yas.db.session import create_engine_for, session_scope
from yas.geo.client import GeocodeResult
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/h.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    geocoder = FakeGeocoder(fixtures={
        "123 main st, chicago, il": GeocodeResult(
            lat=41.88, lon=-87.63, display_name="Chicago", provider="fake",
        )
    })
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=geocoder)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine, geocoder
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_household_creates_default_row(client):
    c, _, _ = client
    r = await c.get("/api/household")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 1
    assert body["default_max_distance_mi"] is None
    assert body["home_location_id"] is None


@pytest.mark.asyncio
async def test_patch_default_max_distance(client):
    c, _, _ = client
    r = await c.patch("/api/household", json={"default_max_distance_mi": 15.0})
    assert r.status_code == 200
    assert r.json()["default_max_distance_mi"] == 15.0


@pytest.mark.asyncio
async def test_patch_home_address_triggers_immediate_geocode(client):
    c, engine, geocoder = client
    r = await c.patch(
        "/api/household",
        json={"home_address": "123 Main St, Chicago, IL", "home_location_name": "Home"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["home_location_id"] is not None
    assert geocoder.call_count >= 1
    async with session_scope(engine) as s:
        loc = (await s.execute(select(Location).where(Location.id == body["home_location_id"]))).scalar_one()
        assert loc.lat == 41.88
        assert loc.lon == -87.63


@pytest.mark.asyncio
async def test_patch_home_address_geocode_miss_still_saves(client):
    c, engine, geocoder = client
    geocoder.misses.add("nowhereville, xx")
    r = await c.patch(
        "/api/household",
        json={"home_address": "Nowhereville, XX", "home_location_name": "Home"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["home_location_id"] is not None  # location created
    async with session_scope(engine) as s:
        loc = (await s.execute(select(Location).where(Location.id == body["home_location_id"]))).scalar_one()
        assert loc.lat is None   # miss — enricher will retry never (negative-cached)
```

- [ ] **Step 2: Schemas**

`src/yas/web/routes/household_schemas.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HouseholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    home_location_id: int | None
    default_max_distance_mi: float | None
    digest_time: str
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    daily_llm_cost_cap_usd: float


class HouseholdPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Ergonomic: set home by address; handler creates/updates the Location row.
    home_address: str | None = None
    home_location_name: str | None = None
    # Or set directly by id.
    home_location_id: int | None = None
    default_max_distance_mi: float | None = None
    digest_time: str | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    daily_llm_cost_cap_usd: float | None = None
```

- [ ] **Step 3: Handler**

`src/yas/web/routes/household.py`:

```python
"""Single-row household settings with immediate-geocode on home-address save."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from yas.crawl.normalize import normalize_name
from yas.db.models import GeocodeAttempt, HouseholdSettings, Location
from yas.db.session import session_scope
from yas.web.routes.household_schemas import HouseholdOut, HouseholdPatch


router = APIRouter(prefix="/api/household", tags=["household"])


def _engine(req: Request):
    return req.app.state.yas.engine


def _geocoder(req: Request):
    return req.app.state.yas.geocoder


async def _load_or_create(session) -> HouseholdSettings:
    hh = (await session.execute(select(HouseholdSettings))).scalars().first()
    if hh is None:
        hh = HouseholdSettings(id=1)
        session.add(hh)
        await session.flush()
    return hh


@router.get("", response_model=HouseholdOut)
async def get_household(request: Request) -> HouseholdOut:
    async with session_scope(_engine(request)) as s:
        hh = await _load_or_create(s)
        return HouseholdOut.model_validate(hh)


@router.patch("", response_model=HouseholdOut)
async def patch_household(patch: HouseholdPatch, request: Request) -> HouseholdOut:
    geocoder = _geocoder(request)
    async with session_scope(_engine(request)) as s:
        hh = await _load_or_create(s)
        data = patch.model_dump(exclude_unset=True)

        # Handle home_address ergonomics: create/update a Location row.
        address = data.pop("home_address", None)
        loc_name = data.pop("home_location_name", None) or "Home"
        if address is not None:
            existing_id = hh.home_location_id
            if existing_id is not None:
                loc = (await s.execute(select(Location).where(Location.id == existing_id))).scalar_one()
                loc.name = loc_name
                loc.address = address
                loc.lat = None   # invalidate; will re-geocode
                loc.lon = None
            else:
                loc = Location(name=loc_name, address=address)
                s.add(loc)
                await s.flush()
                hh.home_location_id = loc.id
            # Immediate geocode attempt.
            if geocoder is not None:
                try:
                    result = await geocoder.geocode(address)
                except Exception:  # noqa: BLE001
                    result = None
                addr_norm = normalize_name(address)
                prior = (await s.execute(
                    select(GeocodeAttempt).where(GeocodeAttempt.address_norm == addr_norm)
                )).scalar_one_or_none()
                now = datetime.now(UTC)
                if result is not None:
                    loc.lat = result.lat
                    loc.lon = result.lon
                    if prior is None:
                        s.add(GeocodeAttempt(address_norm=addr_norm, last_tried=now, result="ok"))
                    else:
                        prior.last_tried = now
                        prior.result = "ok"
                else:
                    if prior is None:
                        s.add(GeocodeAttempt(address_norm=addr_norm, last_tried=now, result="not_found"))
                    else:
                        prior.last_tried = now
                        prior.result = "not_found"

        for key, value in data.items():
            setattr(hh, key, value)

        await s.flush()
        return HouseholdOut.model_validate(hh)
```

- [ ] **Step 4: Register router + AppState extension**

Edit `src/yas/web/deps.py` to add `geocoder: Geocoder | None = None` on `AppState` (keyword-only). Import `Geocoder` at top.

Edit `src/yas/web/app.py`:
- Signature: `def create_app(engine=None, settings=None, *, fetcher=None, llm=None, geocoder=None) -> FastAPI`.
- Pass `geocoder` into `AppState`.
- Include the new router: `from yas.web.routes import household_router; app.include_router(household_router)`.

Update existing callers of `create_app` in this same commit so the suite stays green:
- `src/yas/__main__.py` — existing `_run_all` already constructs `fetcher` and `llm`; leave geocoder as `None` here for now (Task 17 wires it). The kwargs-only signature means omitting `geocoder=` is fine.
- Existing tests in `tests/integration/test_health.py` pass only `engine=...` — keyword-only geocoder defaults to None. No change needed.
- Task 11's new `tests/integration/test_api_household.py` explicitly passes `geocoder=geocoder`.

Edit `src/yas/web/routes/__init__.py`:
```python
from yas.web.routes.sites import router as sites_router
from yas.web.routes.household import router as household_router

__all__ = ["sites_router", "household_router"]
```

- [ ] **Step 5: Run + commit**

```bash
uv run pytest tests/integration/test_api_household.py -v
uv run pytest
uv run ruff check . && uv run mypy src
git add src/yas/web/ tests/integration/test_api_household.py
git commit -m "feat(web): add /api/household with immediate geocode on save"
```

---

## Task 12 — Kids HTTP API

**Files:**
- Create: `src/yas/web/routes/kids_schemas.py`
- Create: `src/yas/web/routes/kids.py`
- Modify: `src/yas/web/routes/__init__.py`, `src/yas/web/app.py`
- Create: `tests/integration/test_api_kids.py`

Follow the same pattern as Phase 2's `sites` router and Task 11's `household`. Post-write hook:

```python
async with session_scope(engine) as s:
    kid = ... # create/update
    await s.flush()
    if any(f in patch_data for f in ("school_time_start","school_time_end",
            "school_year_ranges","school_weekdays","school_holidays",
            "availability","interests","max_distance_mi","dob")):
        await materialize_school_blocks(s, kid.id)
    await rematch_kid(s, kid.id)
```

**Required endpoints** (all under `/api/kids`): `POST`, `GET` (list), `GET /{id}` (detail with nested unavailability / watchlist / enrollments / top-10 matches), `PATCH /{id}`, `DELETE /{id}`.

**Required tests** (minimum):

- `test_create_kid_with_nested_unavailability_atomic` — POST with `unavailability: [...]` creates both atomically.
- `test_create_kid_then_register_offering_produces_match` — create kid, then create a site+page with matching offering via the existing `/api/sites` route; after scheduler tick + reconcile + hook, `GET /api/matches?kid_id=` returns a row. (Deferred to Task 17's integration — leave as a placeholder `pytest.mark.skip` here so the test file exists but doesn't exercise cross-task behavior yet.)
- `test_patch_kid_triggers_rematch_once` — PATCH `interests`; verify the matcher ran exactly once (spy on the matcher via monkeypatch).
- `test_patch_school_schedule_materializes_blocks` — PATCH school fields; DB has fresh `source=school` rows.
- `test_get_kid_includes_nested_blocks_and_top_matches` — detail shape.
- `test_delete_kid_cascades` — FK cascades already in Phase 1 schema.
- `test_create_kid_rejects_unknown_fields` — `extra="forbid"`.

Pydantic schemas live in `kids_schemas.py` with `from_attributes=True` on `KidOut`, `extra="forbid"` on `KidCreate`/`KidUpdate`.

- [ ] **Step 1–N:** follow the Phase 2 sites-router pattern. Each step produces a commit.

Commit message: `feat(web): add /api/kids CRUD with school materializer + rematch hooks`

---

## Task 13 — Watchlist HTTP API

**Files:**
- Create: `src/yas/web/routes/watchlist_schemas.py`, `src/yas/web/routes/watchlist.py`
- Modify: `__init__.py`, `app.py`
- Create: `tests/integration/test_api_watchlist.py`

Same pattern. Endpoints under `/api/kids/{kid_id}/watchlist`:

- `GET` list, `POST` create, `PATCH /{id}`, `DELETE /{id}`.

Each mutation calls `rematch_kid(session, kid_id)` before returning.

Pydantic:
- `WatchlistCreate` (extra=forbid): `pattern`, `site_id` (optional), `priority` (default `normal`), `notes`, `ignore_hard_gates` (default False — but documented as unused).
- `WatchlistPatch`: partial-update subset.
- `WatchlistOut` (from_attributes=True).

**Required tests:**

- `test_create_watchlist_entry_and_rematches_kid` — POST; verify matcher called once.
- `test_patch_pattern_triggers_rematch`
- `test_delete_entry_triggers_rematch_and_drops_hit_matches`
- `test_site_id_must_exist_if_set` — POST with nonexistent site → 404.
- `test_pattern_substring_and_glob_round_trip_via_api` — POST glob pattern, verify subsequent `GET /api/matches` surfaces the watchlist hit. (Placeholder/skip is fine until Task 16.)

Commit: `feat(web): add /api/kids/{id}/watchlist CRUD with rematch hooks`

---

## Task 14 — Unavailability HTTP API

**Files:**
- Create: `src/yas/web/routes/unavailability_schemas.py`, `unavailability.py`
- Modify: `__init__.py`, `app.py`
- Create: `tests/integration/test_api_unavailability.py`

Endpoints under `/api/kids/{kid_id}/unavailability`:

- `GET` list all (including school/enrollment — read-only view).
- `POST` create `manual` or `custom`.
- `PATCH /{id}`, `DELETE /{id}` — refuse with HTTP 409 if `source ∈ {school, enrollment}`; also refuse on `source_enrollment_id IS NOT NULL`.

Each mutation calls `rematch_kid(session, kid_id)` before returning.

**Required tests:**

- `test_create_manual_block`
- `test_create_custom_block_with_date_range`
- `test_patch_manual_block`
- `test_delete_manual_block`
- `test_patch_school_block_returns_409` — refusal path.
- `test_patch_enrollment_block_returns_409`
- `test_get_lists_all_sources` — read-only for school/enrollment.

Commit: `feat(web): add /api/kids/{id}/unavailability CRUD with source gating`

---

## Task 15 — Enrollments HTTP API

**Files:**
- Create: `src/yas/web/routes/enrollments_schemas.py`, `enrollments.py`
- Modify: `__init__.py`, `app.py`
- Create: `tests/integration/test_api_enrollments.py`

Endpoints under `/api/enrollments`:

- `POST`, `GET` (with filters `kid_id`, `status`, `offering_id`), `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`.

Every mutation calls `apply_enrollment_block(session, enrollment_id)` then `rematch_kid(session, enrollment.kid_id)`.

**Required tests:**

- `test_post_enrollment_interested_does_not_block`
- `test_patch_to_enrolled_creates_block_and_rematches`
- `test_patch_back_to_interested_removes_block_and_rematches`
- `test_delete_enrollment_cleans_up_block_and_rematches`
- `test_filters_by_kid_id_and_status`
- `test_rejects_duplicate_kid_offering_pair` — unique constraint? (If Phase 1 schema doesn't enforce, skip this and note as deferred.)

Commit: `feat(web): add /api/enrollments CRUD with block materialization`

---

## Task 16 — Matches read-only HTTP API

**Files:**
- Create: `src/yas/web/routes/matches_schemas.py`, `matches.py`
- Modify: `__init__.py`, `app.py`
- Create: `tests/integration/test_api_matches.py`

Endpoint: `GET /api/matches?kid_id=&offering_id=&min_score=&limit=&offset=`.

Response is a paginated list. Each row includes:

```json
{
  "kid_id": 1,
  "offering_id": 42,
  "score": 0.78,
  "reasons": { ... },
  "computed_at": "...",
  "offering": { "id": 42, "name": "...", "program_type": "soccer", "start_date": "...", "time_start": "09:00" }
}
```

Pagination: default `limit=50, offset=0`; max limit 500.

**Required tests:**

- `test_list_all_matches_empty`
- `test_list_with_kid_id_filter`
- `test_list_with_offering_id_filter`
- `test_list_with_min_score_filter`
- `test_list_pagination`
- `test_reasons_shape_contains_gates_and_score_breakdown`

Commit: `feat(web): add /api/matches read-only with reasons JSON`

---

## Task 17 — Pipeline + worker integration (rematch hooks, daily sweep, geocode enricher)

**Files:**
- Modify: `src/yas/crawl/pipeline.py` — call `rematch_offering(id)` for each id in `reconcile_result.new + updated` inside the same session.
- Modify: `src/yas/worker/runner.py` — construct `NominatimClient`, add `daily_sweep_loop` + `geocode_enricher_loop` tasks to the `TaskGroup`.
- Create: `src/yas/worker/sweep.py` — `daily_sweep_loop(engine, settings)`.
- Modify: `src/yas/__main__.py` — construct geocoder in `_run_all`, pass to `create_app` and `run_worker`.
- Create: `tests/integration/test_worker_loops.py` — sanity that the new loops run and exit on cancel.

### 17.1 Pipeline hook

In `src/yas/crawl/pipeline.py`, inside `_do_crawl`, after the `reconcile(...)` call and before emitting events, add:

```python
from yas.matching.matcher import rematch_offering
for oid in reconcile_result.new + reconcile_result.updated:
    await rematch_offering(s, oid)
```

This runs inside the same `session_scope` block that already opened the session for reconcile.

### 17.2 Daily sweep loop

`src/yas/worker/sweep.py`:

```python
"""Daily sweep: rematch all active kids at a configured UTC time."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings
from yas.db.session import session_scope
from yas.logging import get_logger
from yas.matching.matcher import rematch_all_active_kids

log = get_logger("yas.worker.sweep")


def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


async def daily_sweep_loop(engine: AsyncEngine, settings: Settings) -> None:
    target = _parse_hhmm(settings.sweep_time_utc)
    last_run: date | None = None
    log.info("sweep.start", time_utc=settings.sweep_time_utc)
    try:
        while True:
            now = datetime.now(UTC)
            today = now.date()
            if now.time() >= target and last_run != today:
                async with session_scope(engine) as s:
                    results = await rematch_all_active_kids(s)
                log.info("sweep.ran", kids=len(results))
                last_run = today
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        log.info("sweep.stop")
        raise
```

### 17.3 Worker runner extension

Extend `run_worker` to accept an optional `geocoder: Geocoder | None`; default construct `NominatimClient` when not provided (and `aclose()` it if owned). Add two new `tg.create_task(...)` lines guarded by `settings.sweep_enabled` and `settings.geocode_enabled`.

### 17.4 `__main__._run_all` updates

Construct one `NominatimClient` at the top, pass to `create_app(..., geocoder=...)` and `run_worker(..., geocoder=...)`. Close on shutdown.

### 17.5 Sanity integration test

`tests/integration/test_worker_loops.py`:

```python
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from yas.config import Settings
from yas.db.base import Base
from yas.db.session import create_engine_for
from yas.worker.sweep import daily_sweep_loop


@pytest.mark.asyncio
async def test_daily_sweep_cancels_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/s.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = Settings(_env_file=None, sweep_time_utc="23:59")  # type: ignore[call-arg]
    task = asyncio.create_task(daily_sweep_loop(engine, settings))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await engine.dispose()
```

### 17.6 Verify + commit

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy src
git add src/yas/crawl/pipeline.py src/yas/worker/ src/yas/__main__.py tests/integration/test_worker_loops.py
git commit -m "feat: wire rematch hook into pipeline; add daily sweep + geocode enricher"
```

---

## Task 18 — Smoke script, README, phase exit verification

**Files:**
- Create: `scripts/smoke_phase3.sh`
- Modify: `README.md`

- [ ] **Step 1: Smoke script**

`scripts/smoke_phase3.sh`:

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
rm -f data/activities.db*
$COMPOSE up -d yas-migrate
$COMPOSE up -d yas-worker yas-api
sleep 10

echo "--- set home location ---"
curl -sS -X PATCH localhost:8080/api/household -H 'content-type: application/json' \
  -d '{"home_address":"2045 N Lincoln Park W, Chicago, IL","home_location_name":"Home","default_max_distance_mi":20.0}' | jq .

echo "--- create kid ---"
curl -sS -X POST localhost:8080/api/kids -H 'content-type: application/json' -d '{
  "name":"Sam",
  "dob":"2019-05-01",
  "interests":["baseball"],
  "school_weekdays":["mon","tue","wed","thu","fri"],
  "school_time_start":"08:00",
  "school_time_end":"15:00",
  "school_year_ranges":[{"start":"2026-09-02","end":"2027-06-14"}]
}' | jq .

echo "--- register Lil Sluggers ---"
curl -sS -X POST localhost:8080/api/sites -H 'content-type: application/json' -d '{
  "name":"Lil Sluggers Chicago",
  "base_url":"https://www.lilsluggerschicago.com/",
  "needs_browser":true,
  "pages":[{"url":"https://www.lilsluggerschicago.com/spring-session-24.html","kind":"schedule"}]
}' | jq .

echo "Waiting 90s for scheduler + crawl + extract + rematch..."
sleep 90

echo "--- offerings ---"
$COMPOSE exec -T yas-api sqlite3 /data/activities.db \
  'select id, name, program_type, age_min, age_max, start_date, time_start from offerings'

echo "--- matches ---"
curl -sS 'localhost:8080/api/matches?kid_id=1' | jq .

echo "--- add watchlist entry ---"
curl -sS -X POST localhost:8080/api/kids/1/watchlist -H 'content-type: application/json' \
  -d '{"pattern":"t*ball*","priority":"high"}' | jq .

sleep 2
echo "--- matches after watchlist ---"
curl -sS 'localhost:8080/api/matches?kid_id=1' | jq '.[] | {offering_id, score, watchlist: .reasons.watchlist_hit}'

$COMPOSE down
```

Make executable: `chmod +x scripts/smoke_phase3.sh`.

- [ ] **Step 2: README update**

Add a **Managing kids and matches** section after the existing Managing sites section:

```markdown
## Managing kids and matches

Kids, watchlists, unavailability blocks, and enrollments are registered via HTTP.
Matches are read-only — they're computed automatically whenever something changes.

```bash
# Create a household with a home address (geocoded immediately).
curl -sS -X PATCH localhost:8080/api/household -H 'content-type: application/json' \
  -d '{"home_address":"2045 N Lincoln Park W, Chicago, IL","default_max_distance_mi":20}'

# Create a kid.
curl -sS -X POST localhost:8080/api/kids -H 'content-type: application/json' -d '{
  "name":"Sam","dob":"2019-05-01","interests":["baseball"],
  "school_weekdays":["mon","tue","wed","thu","fri"],
  "school_time_start":"08:00","school_time_end":"15:00",
  "school_year_ranges":[{"start":"2026-09-02","end":"2027-06-14"}]
}'

# Read matches.
curl localhost:8080/api/matches?kid_id=1

# Add a wildcard watchlist entry.
curl -X POST localhost:8080/api/kids/1/watchlist -H 'content-type: application/json' \
  -d '{"pattern":"t*ball*","priority":"high"}'

# Mark an enrollment.
curl -X POST localhost:8080/api/enrollments -H 'content-type: application/json' \
  -d '{"kid_id":1,"offering_id":42,"status":"enrolled"}'
```
```

- [ ] **Step 3: Final verification**

Run all gates locally:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -v
```

Then the end-to-end smoke (requires real API key):

```bash
./scripts/smoke_phase3.sh
```

Expected:
- `offerings` table contains extracted baseball offerings (from Phase 2 result).
- `GET /api/matches?kid_id=1` returns at least one row with non-empty `reasons.gates.age_ok` and `reasons.score_breakdown`.
- After adding the wildcard watchlist entry, the second `GET /api/matches?kid_id=1` response contains at least one row where `reasons.watchlist_hit` is not null.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_phase3.sh README.md
git commit -m "docs: add phase-3 smoke script and kids/matches quickstart"
```

---

## Phase 3 exit checklist

Apply @superpowers:verification-before-completion. Verify with actual commands, not assertions.

- [ ] `uv run ruff check .` clean
- [ ] `uv run ruff format --check .` clean
- [ ] `uv run mypy src` clean
- [ ] `uv run pytest` — all prior-phase tests plus Phase 3 additions green
- [ ] `alembic upgrade head` on fresh DB creates `geocode_attempts` table
- [ ] Docker Compose (macOS overlay locally) brings all five worker tasks up (heartbeat + crawl scheduler + daily sweep + geocode enricher + existing pipeline)
- [ ] `scripts/smoke_phase3.sh` succeeds end-to-end with a real API key against Lil Sluggers; `GET /api/matches?kid_id=1` returns matches with populated `reasons` JSON including real distance
- [ ] Adding a watchlist entry with a wildcard pattern produces at least one match flagged with `reasons.watchlist_hit`
- [ ] Creating an enrollment with `status=enrolled` for an offering removes any conflicting sibling matches in the next rematch
- [ ] No silent failures: geocode / rematch / sweep errors all visible in `crawl_runs.error_text` or a structured log line

When all boxes check, merge with `--no-ff` to `main`. Proceed to **Phase 4 — Alerting**, written as its own plan.
