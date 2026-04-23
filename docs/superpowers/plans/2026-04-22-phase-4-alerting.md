# Phase 4 — Alerting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use @superpowers:subagent-driven-development (recommended) or @superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Follow @superpowers:test-driven-development throughout. Apply @superpowers:verification-before-completion before marking any task done.

**Goal:** Pipeline events and matcher results become delivered alerts — email digests, ntfy pushes, Pushover emergency-priority pokes for registration-opens-now. Silent states from Phase 3/3.5 smokes (stale sites, matchless kids) surface as first-class alert types that roll into the daily digest.

**Architecture:** Event-driven enqueuer (sync, inside existing pipeline/matcher sessions) → `alerts` table with dedup_keys → polled `alert_delivery_loop` (60s tick) with coalesce + rate cap + quiet hours + retries → `Notifier` protocol with three implementations (Email with SMTP/ForwardEmail transports, ntfy, Pushover). Two additional worker loops: `daily_digest_loop` (07:00 UTC) and `detector_loop` (09:00 UTC).

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 async, Pydantic V2, Jinja2 (already in deps), httpx (for ntfy/Pushover/ForwardEmail), `aiosmtplib` (NEW, runtime — SMTP), `aiosmtpd` (NEW, dev — test SMTP server), existing `AnthropicClient.call_tool` for digest top-line.

**Reference spec:** `docs/superpowers/specs/2026-04-22-phase-4-alerting-design.md`. Parent spec §6: `docs/superpowers/specs/2026-04-21-youth-activity-scheduler-design.md`.

---

## Deliverables (phase exit criteria)

- `uv run pytest` green with all new tests + prior phases
- `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` clean
- Docker Compose end-to-end smoke:
  - Configure email via Mailpit sidecar; watchlist entry + offering reconcile → email arrives in Mailpit with expected subject + body sections
  - Configure Pushover from real env (optional); reg_opens_now alert → Pushover with `priority=2`
  - Force-build digest via `POST /api/digest/preview?kid_id=N` returns rendered HTML + text with LLM top-line OR template fallback
  - Toggle `email_config_json.transport` from `smtp` to `forwardemail`; digest arrives via the API path
  - Inject 10 push-scheduled alerts to one kid in a 10-minute span; delivery emits first 5, coalesces excess into one consolidated push
  - Set `quiet_hours_start/end` to include now; `reg_opens_now` still delivers to push; `new_match` is push-suppressed (email still sends)

## Conventions

- **Branch:** `phase-4-alerting` off `main`. Final merge with `--no-ff`.
- **TDD discipline:** failing test → verify fails → implement → verify passes → commit.
- **Commits:** conventional style. One commit per task unless a reviewer-driven fix justifies a second.
- **Secrets:** DB config references env var NAMES (e.g. `password_env: "YAS_SMTP_PASSWORD"`). Actual secrets live only in `.env`. Missing env = channel disabled with a log warning; never crash.
- **Pydantic V2:** `ConfigDict(extra="forbid")` on write schemas.
- **EXACT file paths in `git add`** — directory-level adds have interleaved tasks before.
- **Commits unsigned** for this session is accepted. If `git commit` fails for any OTHER reason, report BLOCKED — don't retry repeatedly.

---

## File structure delta

```
src/yas/
├── config.py                            # MODIFIED — ~12 new settings + channel secrets
├── db/models/_types.py                  # MODIFIED — add site_stagnant, no_matches_for_kid
├── crawl/pipeline.py                    # MODIFIED — enqueue_* calls after reconcile+rematch
├── matching/matcher.py                  # MODIFIED — enqueue_* calls when matches inserted
├── alerts/                              # NEW package
│   ├── __init__.py
│   ├── enqueuer.py                       # all enqueue_* functions; dedup_key
│   ├── schemas.py                        # alert payload Pydantic shapes
│   ├── rate_limit.py                     # coalesce + rate_cap + quiet_hours (pure)
│   ├── routing.py                        # alert_routing table read + defaults seed
│   ├── delivery.py                       # send-one-group orchestrator; retry taxonomy
│   ├── channels/
│   │   ├── __init__.py
│   │   ├── base.py                       # Notifier Protocol + NotifierMessage + SendResult
│   │   ├── email.py                      # EmailChannel + _SMTPTransport + _ForwardEmailTransport
│   │   ├── ntfy.py                       # NtfyChannel
│   │   └── pushover.py                   # PushoverChannel
│   ├── digest/
│   │   ├── __init__.py
│   │   ├── builder.py                    # async gather_digest_payload + render
│   │   ├── llm_summary.py                # generate_top_line with fallback
│   │   ├── filters.py                    # price / rel_date / fmt
│   │   └── templates/
│   │       ├── digest.html.j2
│   │       └── digest.txt.j2
│   └── detectors/
│       ├── __init__.py
│       ├── site_stagnant.py
│       └── no_matches_for_kid.py
├── worker/
│   ├── delivery_loop.py                  # NEW — alert_delivery_loop
│   ├── digest_loop.py                    # NEW — daily_digest_loop
│   ├── detector_loop.py                  # NEW — daily detector loop
│   └── runner.py                         # MODIFIED — add three tasks to TaskGroup
├── web/
│   ├── app.py                            # MODIFIED — register three new routers
│   └── routes/
│       ├── alerts.py                     # NEW
│       ├── alerts_schemas.py             # NEW
│       ├── alert_routing.py              # NEW
│       ├── alert_routing_schemas.py      # NEW
│       ├── digest_preview.py             # NEW
│       └── digest_preview_schemas.py     # NEW

tests/
├── fakes/
│   ├── notifier.py                       # NEW — FakeNotifier
│   └── smtp_server.py                    # NEW — aiosmtpd fixture wrapper
├── unit/
│   ├── test_alerts_enqueuer.py           # NEW
│   ├── test_alerts_rate_limit.py         # NEW — coalesce, rate cap, quiet hours
│   ├── test_alerts_routing.py            # NEW
│   ├── test_alerts_email_channel.py      # NEW
│   ├── test_alerts_ntfy_channel.py       # NEW
│   ├── test_alerts_pushover_channel.py   # NEW
│   ├── test_alerts_detectors.py          # NEW
│   ├── test_alerts_digest_builder.py     # NEW
│   ├── test_alerts_digest_llm_summary.py # NEW
│   └── test_alerts_digest_filters.py     # NEW
└── integration/
    ├── test_alerts_delivery_loop.py       # NEW
    ├── test_alerts_digest_loop.py         # NEW
    ├── test_alerts_detector_loop.py       # NEW
    ├── test_alerts_pipeline_integration.py # NEW — full crawl → enqueue flow
    ├── test_api_alerts.py                  # NEW
    ├── test_api_alert_routing.py           # NEW
    └── test_api_digest_preview.py          # NEW

scripts/smoke_phase4.sh                   # NEW
docker-compose.smoke.yml                  # NEW — adds Mailpit sidecar for smoke only
```

---

## Task 1 — Branch, config, env, new alert types

**Files:**
- Modify: `src/yas/config.py` — 10 new settings + 5 channel-secret fields
- Modify: `.env.example`
- Modify: `src/yas/db/models/_types.py` — add `site_stagnant`, `no_matches_for_kid` to `AlertType`
- Modify: `tests/unit/test_config.py` — new tests
- Modify: `tests/unit/test_models_import.py` — assert new enum values present

- [ ] **Step 1: Cut branch**

```bash
cd /Users/owine/Git/youth-activity-scheduler
git checkout main
git checkout -b phase-4-alerting
```

- [ ] **Step 2: Failing config tests**

Append to `tests/unit/test_config.py`:

```python
def test_alert_settings_defaults(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = _settings()
    assert s.alerts_enabled is True
    assert s.alert_delivery_tick_s == 60
    assert s.alert_coalesce_normal_s == 600
    assert s.alert_max_pushes_per_hour == 5
    assert s.alert_digest_time_utc == "07:00"
    assert s.alert_detector_time_utc == "09:00"
    assert s.alert_stagnant_site_days == 30
    assert s.alert_no_matches_kid_days == 7
    assert s.alert_countdown_past_due_grace_s == 86400
    assert s.alert_digest_empty_skip is True


def test_alert_channel_secrets_optional(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = _settings()
    # All None by default — channel adapters disable themselves when None.
    assert s.smtp_password is None
    assert s.forwardemail_api_token is None
    assert s.ntfy_auth_token is None
    assert s.pushover_user_key is None
    assert s.pushover_app_token is None


def test_alert_channel_secrets_from_env(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("YAS_SMTP_PASSWORD", "hunter2")
    monkeypatch.setenv("YAS_PUSHOVER_USER_KEY", "u123")
    s = _settings()
    assert s.smtp_password == "hunter2"
    assert s.pushover_user_key == "u123"
```

Run: `uv run pytest tests/unit/test_config.py -v` — expect failures.

- [ ] **Step 3: Implement config**

Append to `Settings` class in `src/yas/config.py`:

```python
    # Alerting
    alerts_enabled: bool = True
    alert_delivery_tick_s: int = 60
    alert_coalesce_normal_s: int = 600
    alert_max_pushes_per_hour: int = 5
    alert_digest_time_utc: str = "07:00"
    alert_detector_time_utc: str = "09:00"
    alert_stagnant_site_days: int = 30
    alert_no_matches_kid_days: int = 7
    alert_countdown_past_due_grace_s: int = 86400
    alert_digest_empty_skip: bool = True

    # Channel secrets (env-only). Missing env disables the channel at runtime.
    smtp_password: str | None = None
    forwardemail_api_token: str | None = None
    ntfy_auth_token: str | None = None
    pushover_user_key: str | None = None
    pushover_app_token: str | None = None
```

- [ ] **Step 4: Extend AlertType enum**

Edit `src/yas/db/models/_types.py`. Find the `AlertType` StrEnum; add two new values:

```python
class AlertType(StrEnum):
    watchlist_hit = "watchlist_hit"
    new_match = "new_match"
    reg_opens_24h = "reg_opens_24h"
    reg_opens_1h = "reg_opens_1h"
    reg_opens_now = "reg_opens_now"
    schedule_posted = "schedule_posted"
    crawl_failed = "crawl_failed"
    digest = "digest"
    # Phase 4 additions
    site_stagnant = "site_stagnant"
    no_matches_for_kid = "no_matches_for_kid"
    push_cap = "push_cap"
```

**Verify no Alembic migration needed** — `alerts.type` column should be plain `String` (not a SQLite CHECK constraint or native enum). Spot-check `src/yas/db/models/alert.py`:

```bash
grep -n "type" src/yas/db/models/alert.py
```

Expected: `type: Mapped[str] = mapped_column(String, ...)` with no `CheckConstraint` over `type`. If a CHECK constraint exists, generate an Alembic migration (`alembic revision --autogenerate -m "extend_alert_type_enum"`) using `render_as_batch=True` before proceeding. Otherwise the Python enum values are used only at insert time and no schema change is needed.

- [ ] **Step 5: Update test_models_import.py**

Edit `tests/unit/test_models_import.py`. Find the existing test that asserts StrEnum members; ensure `site_stagnant` and `no_matches_for_kid` are exercised if there's a parametrized check, OR add a targeted test:

```python
def test_alerttype_has_phase4_additions():
    from yas.db.models._types import AlertType
    assert AlertType.site_stagnant.value == "site_stagnant"
    assert AlertType.no_matches_for_kid.value == "no_matches_for_kid"
```

- [ ] **Step 6: Update .env.example**

Append:

```
# Alerting
# YAS_ALERTS_ENABLED=true
# YAS_ALERT_DELIVERY_TICK_S=60
# YAS_ALERT_COALESCE_NORMAL_S=600
# YAS_ALERT_MAX_PUSHES_PER_HOUR=5
# YAS_ALERT_DIGEST_TIME_UTC=07:00
# YAS_ALERT_DETECTOR_TIME_UTC=09:00
# YAS_ALERT_STAGNANT_SITE_DAYS=30
# YAS_ALERT_NO_MATCHES_KID_DAYS=7
# YAS_ALERT_COUNTDOWN_PAST_DUE_GRACE_S=86400
# YAS_ALERT_DIGEST_EMPTY_SKIP=true

# Channel secrets (set only if you configure the channel)
# YAS_SMTP_PASSWORD=...
# YAS_FORWARDEMAIL_API_TOKEN=...
# YAS_NTFY_AUTH_TOKEN=...
# YAS_PUSHOVER_USER_KEY=...
# YAS_PUSHOVER_APP_TOKEN=...
```

- [ ] **Step 7: Run gates**

```bash
uv run pytest tests/unit/test_config.py tests/unit/test_models_import.py -v
uv run pytest
uv run ruff check .
uv run mypy src
```

All green.

- [ ] **Step 8: Commit**

```bash
git add src/yas/config.py .env.example src/yas/db/models/_types.py \
    tests/unit/test_config.py tests/unit/test_models_import.py
git commit -m "chore: add phase-4 config, channel-secret env fields, and two new AlertType values"
```

---

## Task 2 — Alert payload schemas + enqueuer module

**Files:**
- Create: `src/yas/alerts/__init__.py` (empty)
- Create: `src/yas/alerts/schemas.py` — per-alert-type payload Pydantic models
- Create: `src/yas/alerts/enqueuer.py` — all `enqueue_*` functions + `dedup_key`
- Create: `tests/unit/test_alerts_enqueuer.py`

Enqueuer is the single most-called alerts module. Every mutation site hits it. Tests assert insert-on-new, update-on-dedup-collision, no-op when preconditions fail.

- [ ] **Step 1: Failing tests (expansive)**

`tests/unit/test_alerts_enqueuer.py`:

```python
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from yas.alerts.enqueuer import (
    dedup_key_for,
    enqueue_crawl_failed,
    enqueue_digest,
    enqueue_new_match,
    enqueue_no_matches_for_kid,
    enqueue_push_cap,
    enqueue_registration_countdowns,
    enqueue_site_stagnant,
    enqueue_watchlist_hit,
)
from yas.db.base import Base
from yas.db.models import Alert, Kid, Offering, Page, Site
from yas.db.models._types import AlertType, ProgramType
from yas.db.session import create_engine_for, session_scope


async def _setup(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/a.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1),
                  alert_on={"new_match": True, "reg_opens": True}))
        s.add(Kid(id=2, name="Alex", dob=date(2018, 1, 1),
                  alert_on={"new_match": False, "reg_opens": True}))
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        s.add(
            Offering(
                id=1, site_id=1, page_id=1,
                name="Spring Soccer", normalized_name="spring soccer",
                program_type=ProgramType.soccer.value,
            )
        )
    return engine


# --- dedup_key -----------------------------------------------------------------

def test_dedup_key_new_match_has_kid_and_offering():
    key = dedup_key_for(AlertType.new_match, kid_id=1, offering_id=42)
    assert key == "new_match:1:42"


def test_dedup_key_site_stagnant_no_kid():
    key = dedup_key_for(AlertType.site_stagnant, site_id=9)
    assert key == "site_stagnant:-:9"


def test_dedup_key_countdown_includes_scheduled_for():
    when = datetime(2026, 5, 5, 9, 0, tzinfo=UTC)
    key = dedup_key_for(AlertType.reg_opens_24h, kid_id=1, offering_id=42, scheduled_for=when)
    assert key == "reg_opens_24h:1:42:2026-05-05T09:00"


def test_dedup_key_digest_includes_for_date():
    key = dedup_key_for(AlertType.digest, kid_id=1, for_date=date(2026, 5, 5))
    assert key == "digest:1:2026-05-05"


def test_dedup_key_no_matches_for_kid():
    assert dedup_key_for(AlertType.no_matches_for_kid, kid_id=1) == "no_matches_for_kid:1:-"


# --- enqueue_new_match ---------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_new_match_inserts_first_time(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        aid = await enqueue_new_match(
            s, kid_id=1, offering_id=1, score=0.9, reasons={"k": "v"},
        )
    assert aid is not None
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1
        assert rows[0].type == AlertType.new_match.value
        assert rows[0].kid_id == 1
        assert rows[0].offering_id == 1


@pytest.mark.asyncio
async def test_enqueue_new_match_updates_on_dedup_hit(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await enqueue_new_match(s, kid_id=1, offering_id=1, score=0.5, reasons={"v": 1})
    async with session_scope(engine) as s:
        await enqueue_new_match(s, kid_id=1, offering_id=1, score=0.9, reasons={"v": 2})
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1                              # no duplicate
        assert rows[0].payload_json["score"] == 0.9         # updated


@pytest.mark.asyncio
async def test_enqueue_new_match_respects_kid_alert_on_toggle(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        # Kid 2 has alert_on.new_match=False
        aid = await enqueue_new_match(s, kid_id=2, offering_id=1, score=0.9, reasons={})
    assert aid is None
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert rows == []


# --- enqueue_watchlist_hit -----------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_watchlist_hit_always_inserts(tmp_path):
    engine = await _setup(tmp_path)
    # Even a kid with new_match=False should still get watchlist alerts.
    async with session_scope(engine) as s:
        aid = await enqueue_watchlist_hit(
            s, kid_id=2, offering_id=1, watchlist_entry_id=7, reasons={"pattern": "soccer"},
        )
    assert aid is not None


# --- enqueue_registration_countdowns ------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_registration_countdowns_inserts_three_rows(tmp_path):
    engine = await _setup(tmp_path)
    opens_at = datetime.now(UTC) + timedelta(days=3)
    async with session_scope(engine) as s:
        ids = await enqueue_registration_countdowns(
            s, offering_id=1, kid_id=1, opens_at=opens_at,
        )
    assert len(ids) == 3
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert).order_by(Alert.scheduled_for))).scalars().all()
        types = [r.type for r in rows]
        assert types == [
            AlertType.reg_opens_24h.value,
            AlertType.reg_opens_1h.value,
            AlertType.reg_opens_now.value,
        ]


@pytest.mark.asyncio
async def test_enqueue_registration_countdowns_skips_past_due(tmp_path):
    engine = await _setup(tmp_path)
    # opens_at is 30 minutes from now. T-24h is in the past; T-1h is in the past;
    # only T-0 (now+30min) gets scheduled.
    opens_at = datetime.now(UTC) + timedelta(minutes=30)
    async with session_scope(engine) as s:
        ids = await enqueue_registration_countdowns(
            s, offering_id=1, kid_id=1, opens_at=opens_at,
        )
    assert len(ids) == 1
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1
        assert rows[0].type == AlertType.reg_opens_now.value


@pytest.mark.asyncio
async def test_enqueue_registration_countdowns_rewrites_on_date_change(tmp_path):
    engine = await _setup(tmp_path)
    original = datetime.now(UTC) + timedelta(days=3)
    shifted = original + timedelta(days=7)
    async with session_scope(engine) as s:
        await enqueue_registration_countdowns(s, offering_id=1, kid_id=1, opens_at=original)
    async with session_scope(engine) as s:
        await enqueue_registration_countdowns(s, offering_id=1, kid_id=1, opens_at=shifted)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert).order_by(Alert.scheduled_for))).scalars().all()
        # Should still be only three rows — old deleted, new inserted
        assert len(rows) == 3
        first = rows[0].scheduled_for
        assert first > original


# --- enqueue_crawl_failed ------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_crawl_failed_dedups_per_site(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await enqueue_crawl_failed(s, site_id=1, consecutive_failures=3, last_error="timeout")
    async with session_scope(engine) as s:
        await enqueue_crawl_failed(s, site_id=1, consecutive_failures=4, last_error="timeout")
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload_json["consecutive_failures"] == 4


# --- enqueue_site_stagnant + enqueue_no_matches_for_kid -----------------------

@pytest.mark.asyncio
async def test_enqueue_site_stagnant_one_per_site(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await enqueue_site_stagnant(s, site_id=1, days_silent=31)
    async with session_scope(engine) as s:
        await enqueue_site_stagnant(s, site_id=1, days_silent=32)    # next day
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload_json["days_silent"] == 32


@pytest.mark.asyncio
async def test_enqueue_no_matches_for_kid_one_per_kid(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await enqueue_no_matches_for_kid(s, kid_id=1, days_since_created=7)
    async with session_scope(engine) as s:
        await enqueue_no_matches_for_kid(s, kid_id=1, days_since_created=14)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1


# --- enqueue_digest ------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_digest_dedups_per_day(tmp_path):
    engine = await _setup(tmp_path)
    today = date(2026, 5, 5)
    payload = {"subject": "...", "body_plain": "...", "body_html": "..."}
    async with session_scope(engine) as s:
        await enqueue_digest(s, kid_id=1, for_date=today, payload=payload)
    async with session_scope(engine) as s:
        await enqueue_digest(s, kid_id=1, for_date=today,
                             payload={**payload, "subject": "updated"})
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload_json["subject"] == "updated"
```

Run: `uv run pytest tests/unit/test_alerts_enqueuer.py -v` — expect ImportError.

- [ ] **Step 2: Implement `src/yas/alerts/__init__.py`** (empty)

- [ ] **Step 3: Implement `src/yas/alerts/schemas.py`**

```python
"""Pydantic payload shapes for each AlertType.

Each AlertType has a small schema describing what goes into alerts.payload_json.
These are used by the enqueuer for validation + by the delivery-worker renderers
as structured inputs to channel message templates."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewMatchPayload(_Base):
    score: float
    reasons: dict[str, Any]


class WatchlistHitPayload(_Base):
    watchlist_entry_id: int
    reasons: dict[str, Any]


class RegOpensPayload(_Base):
    opens_at: datetime
    offering_name: str
    registration_url: str | None = None


class SchedulePostedPayload(_Base):
    summary: str | None = None


class CrawlFailedPayload(_Base):
    consecutive_failures: int
    last_error: str


class SiteStagnantPayload(_Base):
    site_name: str
    days_silent: int


class NoMatchesForKidPayload(_Base):
    kid_name: str
    days_since_created: int


class DigestPayload(_Base):
    subject: str
    body_plain: str
    body_html: str | None = None
```

- [ ] **Step 4: Implement `src/yas/alerts/enqueuer.py`**

```python
"""Event-driven alert enqueuer.

Called synchronously from pipeline/matcher/detector sites with an open
AsyncSession. Each function computes a dedup_key and either inserts a new
alerts row or updates an existing unsent row in-place."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Alert, Kid, Site
from yas.db.models._types import AlertType
from yas.logging import get_logger

log = get_logger("yas.alerts.enqueuer")


def dedup_key_for(
    alert_type: AlertType,
    *,
    kid_id: int | None = None,
    offering_id: int | None = None,
    site_id: int | None = None,
    page_id: int | None = None,
    scheduled_for: datetime | None = None,
    for_date: date | None = None,
    hour_bucket: str | None = None,
) -> str:
    """Compute the dedup_key per the spec. See Phase 4 spec §3.1."""
    k = "-" if kid_id is None else str(kid_id)
    if alert_type == AlertType.digest:
        assert for_date is not None
        return f"digest:{k}:{for_date.isoformat()}"
    if alert_type in {AlertType.reg_opens_24h, AlertType.reg_opens_1h, AlertType.reg_opens_now}:
        assert offering_id is not None and scheduled_for is not None
        sf_min = scheduled_for.strftime("%Y-%m-%dT%H:%M")
        return f"{alert_type.value}:{k}:{offering_id}:{sf_min}"
    if alert_type == AlertType.crawl_failed:
        return f"crawl_failed:-:{site_id}"
    if alert_type == AlertType.site_stagnant:
        return f"site_stagnant:-:{site_id}"
    if alert_type == AlertType.no_matches_for_kid:
        return f"no_matches_for_kid:{k}:-"
    if alert_type == AlertType.schedule_posted:
        return f"schedule_posted:-:{site_id}:{page_id}"
    if alert_type == AlertType.watchlist_hit:
        assert offering_id is not None
        return f"watchlist_hit:{k}:{offering_id}"
    if alert_type == AlertType.new_match:
        assert offering_id is not None
        return f"new_match:{k}:{offering_id}"
    # push_cap is an internal alert used by delivery worker; not dispatched here.
    raise ValueError(f"no dedup_key rule for {alert_type!r}")


async def _upsert_alert(
    session: AsyncSession,
    *,
    alert_type: AlertType,
    dedup_key: str,
    kid_id: int | None,
    offering_id: int | None,
    site_id: int | None,
    scheduled_for: datetime,
    payload: dict[str, Any],
) -> int:
    """Insert a new unsent alert OR update an existing unsent row with the
    same dedup_key. Returns the row id."""
    existing = (
        await session.execute(
            select(Alert).where(
                Alert.dedup_key == dedup_key,
                Alert.sent_at.is_(None),
                Alert.skipped.is_(False),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.payload_json = payload
        existing.scheduled_for = scheduled_for
        return existing.id
    row = Alert(
        type=alert_type.value,
        kid_id=kid_id,
        offering_id=offering_id,
        site_id=site_id,
        channels=[],  # delivery worker fills from routing at send time
        scheduled_for=scheduled_for,
        dedup_key=dedup_key,
        payload_json=payload,
    )
    session.add(row)
    await session.flush()
    return row.id


def _kid_alert_on(kid: Kid, key: str, default: bool = True) -> bool:
    data = kid.alert_on or {}
    val = data.get(key, default)
    return bool(val)


async def enqueue_new_match(
    session: AsyncSession,
    *,
    kid_id: int,
    offering_id: int,
    score: float,
    reasons: dict[str, Any],
) -> int | None:
    """Insert or update a new_match alert. Respects kid.alert_on.new_match."""
    kid = (await session.execute(select(Kid).where(Kid.id == kid_id))).scalar_one()
    if not _kid_alert_on(kid, "new_match", default=True):
        return None
    dk = dedup_key_for(AlertType.new_match, kid_id=kid_id, offering_id=offering_id)
    return await _upsert_alert(
        session,
        alert_type=AlertType.new_match,
        dedup_key=dk,
        kid_id=kid_id,
        offering_id=offering_id,
        site_id=None,
        scheduled_for=datetime.now(UTC),
        payload={"score": score, "reasons": reasons},
    )


async def enqueue_watchlist_hit(
    session: AsyncSession,
    *,
    kid_id: int,
    offering_id: int,
    watchlist_entry_id: int,
    reasons: dict[str, Any],
) -> int:
    """Insert or update a watchlist_hit alert. Bypasses kid.alert_on — the user
    added the watchlist entry explicitly."""
    dk = dedup_key_for(AlertType.watchlist_hit, kid_id=kid_id, offering_id=offering_id)
    return await _upsert_alert(
        session,
        alert_type=AlertType.watchlist_hit,
        dedup_key=dk,
        kid_id=kid_id,
        offering_id=offering_id,
        site_id=None,
        scheduled_for=datetime.now(UTC),
        payload={
            "watchlist_entry_id": watchlist_entry_id,
            "reasons": reasons,
        },
    )


async def enqueue_schedule_posted(
    session: AsyncSession,
    *,
    page_id: int,
    site_id: int,
    summary: str | None,
) -> int:
    dk = dedup_key_for(AlertType.schedule_posted, site_id=site_id, page_id=page_id)
    return await _upsert_alert(
        session,
        alert_type=AlertType.schedule_posted,
        dedup_key=dk,
        kid_id=None,
        offering_id=None,
        site_id=site_id,
        scheduled_for=datetime.now(UTC),
        payload={"summary": summary},
    )


async def enqueue_crawl_failed(
    session: AsyncSession,
    *,
    site_id: int,
    consecutive_failures: int,
    last_error: str,
) -> int:
    dk = dedup_key_for(AlertType.crawl_failed, site_id=site_id)
    return await _upsert_alert(
        session,
        alert_type=AlertType.crawl_failed,
        dedup_key=dk,
        kid_id=None,
        offering_id=None,
        site_id=site_id,
        scheduled_for=datetime.now(UTC),
        payload={
            "consecutive_failures": consecutive_failures,
            "last_error": last_error,
        },
    )


async def enqueue_registration_countdowns(
    session: AsyncSession,
    *,
    offering_id: int,
    kid_id: int,
    opens_at: datetime,
) -> list[int]:
    """Delete any existing unsent reg_opens_* rows for this (kid, offering) and
    insert up to three fresh ones at T-24h, T-1h, T. Skips past-due schedules."""
    # Delete prior unsent countdowns for this pair.
    await session.execute(
        delete(Alert).where(
            Alert.kid_id == kid_id,
            Alert.offering_id == offering_id,
            Alert.type.in_([
                AlertType.reg_opens_24h.value,
                AlertType.reg_opens_1h.value,
                AlertType.reg_opens_now.value,
            ]),
            Alert.sent_at.is_(None),
            Alert.skipped.is_(False),
        )
    )

    now = datetime.now(UTC)
    offsets: list[tuple[AlertType, timedelta]] = [
        (AlertType.reg_opens_24h, timedelta(hours=24)),
        (AlertType.reg_opens_1h, timedelta(hours=1)),
        (AlertType.reg_opens_now, timedelta(0)),
    ]
    ids: list[int] = []
    payload_base = {"opens_at": opens_at.isoformat(), "offering_id": offering_id}
    for alert_type, offset in offsets:
        scheduled_for = opens_at - offset
        if scheduled_for < now:
            continue
        dk = dedup_key_for(
            alert_type, kid_id=kid_id, offering_id=offering_id,
            scheduled_for=scheduled_for,
        )
        aid = await _upsert_alert(
            session,
            alert_type=alert_type,
            dedup_key=dk,
            kid_id=kid_id,
            offering_id=offering_id,
            site_id=None,
            scheduled_for=scheduled_for,
            payload=payload_base,
        )
        ids.append(aid)
    return ids


async def enqueue_site_stagnant(
    session: AsyncSession,
    *,
    site_id: int,
    days_silent: int,
) -> int:
    site = (await session.execute(select(Site).where(Site.id == site_id))).scalar_one()
    dk = dedup_key_for(AlertType.site_stagnant, site_id=site_id)
    return await _upsert_alert(
        session,
        alert_type=AlertType.site_stagnant,
        dedup_key=dk,
        kid_id=None,
        offering_id=None,
        site_id=site_id,
        scheduled_for=datetime.now(UTC),
        payload={"site_name": site.name, "days_silent": days_silent},
    )


async def enqueue_no_matches_for_kid(
    session: AsyncSession,
    *,
    kid_id: int,
    days_since_created: int,
) -> int:
    kid = (await session.execute(select(Kid).where(Kid.id == kid_id))).scalar_one()
    dk = dedup_key_for(AlertType.no_matches_for_kid, kid_id=kid_id)
    return await _upsert_alert(
        session,
        alert_type=AlertType.no_matches_for_kid,
        dedup_key=dk,
        kid_id=kid_id,
        offering_id=None,
        site_id=None,
        scheduled_for=datetime.now(UTC),
        payload={"kid_name": kid.name, "days_since_created": days_since_created},
    )


async def enqueue_digest(
    session: AsyncSession,
    *,
    kid_id: int,
    for_date: date,
    payload: dict[str, Any],
) -> int:
    dk = dedup_key_for(AlertType.digest, kid_id=kid_id, for_date=for_date)
    return await _upsert_alert(
        session,
        alert_type=AlertType.digest,
        dedup_key=dk,
        kid_id=kid_id,
        offering_id=None,
        site_id=None,
        scheduled_for=datetime.now(UTC),
        payload=payload,
    )


async def enqueue_push_cap(
    session: AsyncSession,
    *,
    kid_id: int,
    hour_bucket: str,  # ISO hour, e.g. "2026-04-22T15"
    suppressed_count: int,
) -> int:
    """Consolidated alert emitted by delivery loop when per-hour push cap is
    hit. Kept in the enqueuer (not an inline Alert insert in delivery.py) so
    all alert inserts share the same dedup/upsert path."""
    dk = f"push_cap:{kid_id}:{hour_bucket}"
    return await _upsert_alert(
        session,
        alert_type=AlertType.push_cap,
        dedup_key=dk,
        kid_id=kid_id,
        offering_id=None,
        site_id=None,
        scheduled_for=datetime.now(UTC),
        payload={"suppressed_count": suppressed_count, "hour_bucket": hour_bucket},
    )
```

Also add a test `test_enqueue_push_cap_dedups_per_hour_bucket` under Task 2.

- [ ] **Step 5: Run + commit**

```bash
uv run pytest tests/unit/test_alerts_enqueuer.py -v
uv run pytest
uv run ruff check .
uv run mypy src
git add src/yas/alerts/__init__.py src/yas/alerts/schemas.py src/yas/alerts/enqueuer.py \
    tests/unit/test_alerts_enqueuer.py
git commit -m "feat(alerts): add alert payload schemas and enqueuer with dedup_key"
```

---

## Task 3 — Pure rate-limit helpers: coalesce + push cap + quiet hours

**Files:**
- Create: `src/yas/alerts/rate_limit.py`
- Create: `tests/unit/test_alerts_rate_limit.py`

Three pure functions + one DB-backed helper. All tested deterministically.

- [ ] **Step 1: Failing tests**

`tests/unit/test_alerts_rate_limit.py`:

```python
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

import pytest

from yas.alerts.rate_limit import (
    AlertGroup,
    coalesce,
    is_in_quiet_hours,
    should_rate_limit_push,
)
from yas.db.models._types import AlertType


# Minimal shape; tests don't need a real Alert ORM instance.
@dataclass
class _FakeAlert:
    id: int
    kid_id: int | None
    type: str
    scheduled_for: datetime
    payload_json: dict = field(default_factory=dict)


def _a(id_, kid, atype, offset_s: int) -> _FakeAlert:
    return _FakeAlert(
        id=id_, kid_id=kid, type=atype.value,
        scheduled_for=datetime(2026, 5, 5, 10, 0, tzinfo=UTC) + timedelta(seconds=offset_s),
    )


# --- coalesce -----------------------------------------------------------------

def test_coalesce_single_alert_single_group():
    alerts = [_a(1, 1, AlertType.new_match, 0)]
    groups = coalesce(alerts, window_s=600)
    assert len(groups) == 1
    assert len(groups[0].members) == 1


def test_coalesce_merges_same_kid_type_within_window():
    alerts = [
        _a(1, 1, AlertType.new_match, 0),
        _a(2, 1, AlertType.new_match, 60),
        _a(3, 1, AlertType.new_match, 120),
    ]
    groups = coalesce(alerts, window_s=600)
    assert len(groups) == 1
    assert {m.id for m in groups[0].members} == {1, 2, 3}


def test_coalesce_does_not_merge_across_window():
    alerts = [
        _a(1, 1, AlertType.new_match, 0),
        _a(2, 1, AlertType.new_match, 700),   # 700s > 600s window
    ]
    groups = coalesce(alerts, window_s=600)
    assert len(groups) == 2


def test_coalesce_does_not_merge_different_types():
    alerts = [
        _a(1, 1, AlertType.new_match, 0),
        _a(2, 1, AlertType.reg_opens_24h, 60),
    ]
    groups = coalesce(alerts, window_s=600)
    assert len(groups) == 2


def test_coalesce_does_not_merge_different_kids():
    alerts = [
        _a(1, 1, AlertType.new_match, 0),
        _a(2, 2, AlertType.new_match, 60),
    ]
    groups = coalesce(alerts, window_s=600)
    assert len(groups) == 2


def test_coalesce_non_coalesceable_types_pass_through():
    # reg_opens_now, reg_opens_1h, watchlist_hit, crawl_failed, digest
    alerts = [
        _a(1, 1, AlertType.reg_opens_now, 0),
        _a(2, 1, AlertType.reg_opens_now, 60),
        _a(3, 1, AlertType.watchlist_hit, 0),
        _a(4, 1, AlertType.watchlist_hit, 60),
    ]
    groups = coalesce(alerts, window_s=600)
    # All four stay as individual groups.
    assert len(groups) == 4


def test_coalesce_stable_ordering_by_scheduled_for():
    alerts = [
        _a(3, 1, AlertType.new_match, 120),
        _a(1, 1, AlertType.new_match, 0),
        _a(2, 1, AlertType.new_match, 60),
    ]
    groups = coalesce(alerts, window_s=600)
    # Lead is the earliest-scheduled.
    assert groups[0].lead.id == 1


# --- should_rate_limit_push ---------------------------------------------------

@pytest.mark.parametrize("sent,cap,expected", [
    (0, 5, False),
    (4, 5, False),
    (5, 5, True),
    (10, 5, True),
])
def test_should_rate_limit_push(sent, cap, expected):
    assert should_rate_limit_push(sent, cap) is expected


# --- is_in_quiet_hours --------------------------------------------------------

def test_quiet_hours_same_day_window():
    now = datetime(2026, 5, 5, 14, 0, tzinfo=UTC)  # 14:00 UTC
    assert is_in_quiet_hours(now, "13:00", "15:00") is True
    assert is_in_quiet_hours(now, "15:00", "16:00") is False


def test_quiet_hours_wrap_around_midnight():
    # 22:00..07:00
    assert is_in_quiet_hours(datetime(2026, 5, 5, 23, 0, tzinfo=UTC), "22:00", "07:00") is True
    assert is_in_quiet_hours(datetime(2026, 5, 5, 3, 0, tzinfo=UTC), "22:00", "07:00") is True
    assert is_in_quiet_hours(datetime(2026, 5, 5, 8, 0, tzinfo=UTC), "22:00", "07:00") is False
    assert is_in_quiet_hours(datetime(2026, 5, 5, 21, 30, tzinfo=UTC), "22:00", "07:00") is False


def test_quiet_hours_none_fields_returns_false():
    now = datetime.now(UTC)
    assert is_in_quiet_hours(now, None, "07:00") is False
    assert is_in_quiet_hours(now, "22:00", None) is False
    assert is_in_quiet_hours(now, None, None) is False


def test_quiet_hours_boundary_inclusive_at_start_exclusive_at_end():
    assert is_in_quiet_hours(datetime(2026, 5, 5, 22, 0, tzinfo=UTC), "22:00", "07:00") is True
    assert is_in_quiet_hours(datetime(2026, 5, 5, 7, 0, tzinfo=UTC), "22:00", "07:00") is False
```

Run: `uv run pytest tests/unit/test_alerts_rate_limit.py -v` — expect ImportError.

- [ ] **Step 2: Implement `src/yas/alerts/rate_limit.py`**

```python
"""Pure helpers: coalesce, push-cap check, quiet-hours check."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Alert
from yas.db.models._types import AlertType

_NEVER_COALESCE = frozenset({
    AlertType.reg_opens_now.value,
    AlertType.reg_opens_1h.value,
    AlertType.watchlist_hit.value,
    AlertType.crawl_failed.value,
    AlertType.digest.value,
})


@dataclass(frozen=True)
class AlertGroup:
    lead: Any              # the earliest-scheduled member
    members: list[Any] = field(default_factory=list)
    kid_id: int | None = None
    alert_type: str = ""


def coalesce(due: list[Any], *, window_s: int) -> list[AlertGroup]:
    """Group alerts sharing (kid_id, type) where consecutive members'
    scheduled_for timestamps are within window_s of each other. Types in
    _NEVER_COALESCE pass through as singleton groups regardless."""
    # Sort by scheduled_for ascending for deterministic grouping.
    sorted_alerts = sorted(due, key=lambda a: (a.scheduled_for, a.id))
    groups: list[AlertGroup] = []
    pending: dict[tuple[int | None, str], list[Any]] = {}

    def _flush_group(key: tuple[int | None, str]) -> None:
        members = pending.pop(key, [])
        if not members:
            return
        groups.append(AlertGroup(
            lead=members[0],
            members=members,
            kid_id=key[0],
            alert_type=key[1],
        ))

    for a in sorted_alerts:
        if a.type in _NEVER_COALESCE:
            groups.append(AlertGroup(lead=a, members=[a], kid_id=a.kid_id, alert_type=a.type))
            continue
        key = (a.kid_id, a.type)
        existing = pending.get(key)
        if existing is None:
            pending[key] = [a]
            continue
        last = existing[-1]
        if (a.scheduled_for - last.scheduled_for).total_seconds() <= window_s:
            existing.append(a)
        else:
            _flush_group(key)
            pending[key] = [a]

    # Flush remaining
    for key in list(pending.keys()):
        _flush_group(key)

    # Re-sort groups by lead.scheduled_for for stable output
    groups.sort(key=lambda g: (g.lead.scheduled_for, g.lead.id))
    return groups


def should_rate_limit_push(sent_count: int, max_per_hour: int) -> bool:
    """True if the per-kid push cap has been reached in the last hour."""
    return sent_count >= max_per_hour


async def count_pushes_sent_in_last_hour(
    session: AsyncSession, kid_id: int, push_channels: list[str],
) -> int:
    """Count alerts.sent_at >= now-1h where any configured push channel was
    used. Channels is a list of notifier.name values."""
    if not push_channels:
        return 0
    window_start = datetime.now(UTC) - timedelta(hours=1)
    # `channels` is a JSON list; SQLite's json_each makes this checkable.
    # Use a substring match on the JSON string form for simplicity — acceptable
    # at this scale (kid has a handful of alerts/hour at most).
    rows = (
        await session.execute(
            select(func.count(Alert.id)).where(
                Alert.kid_id == kid_id,
                Alert.sent_at.isnot(None),
                Alert.sent_at >= window_start,
            )
        )
    ).scalar_one()
    # Filter in Python for push-channel membership (small N).
    if rows == 0:
        return 0
    alerts = (
        await session.execute(
            select(Alert).where(
                Alert.kid_id == kid_id,
                Alert.sent_at.isnot(None),
                Alert.sent_at >= window_start,
            )
        )
    ).scalars().all()
    return sum(1 for a in alerts if any(c in push_channels for c in (a.channels or [])))


def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def is_in_quiet_hours(
    now: datetime,
    quiet_start: str | None,
    quiet_end: str | None,
) -> bool:
    """Check if now falls in the household's configured quiet-hours window.
    Both fields are HH:MM in UTC. Wrap-around (e.g. 22:00..07:00) handled.
    If either is None → not in quiet hours."""
    if quiet_start is None or quiet_end is None:
        return False
    start = _parse_hhmm(quiet_start)
    end = _parse_hhmm(quiet_end)
    now_t = now.time()
    if start <= end:
        return start <= now_t < end
    # Wrap-around
    return now_t >= start or now_t < end
```

- [ ] **Step 3: Run + commit**

```bash
uv run pytest tests/unit/test_alerts_rate_limit.py -v
uv run pytest
uv run ruff check .
uv run mypy src
git add src/yas/alerts/rate_limit.py tests/unit/test_alerts_rate_limit.py
git commit -m "feat(alerts): add pure coalesce + rate-cap + quiet-hours helpers"
```

---

## Task 4 — Alert routing: table seeding + lookup

**Files:**
- Create: `src/yas/alerts/routing.py`
- Create: `tests/unit/test_alerts_routing.py`

Phase 1 created `alert_routing` table but no one uses it. Task 4 populates it with defaults on first run and provides a lookup function.

- [ ] **Step 1: Failing tests**

`tests/unit/test_alerts_routing.py`:

```python
import pytest
from sqlalchemy import select

from yas.alerts.routing import (
    DEFAULT_ROUTING,
    get_routing,
    seed_default_routing,
)
from yas.db.base import Base
from yas.db.models import AlertRouting
from yas.db.models._types import AlertType
from yas.db.session import create_engine_for, session_scope


async def _engine(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/r.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_seed_populates_all_alert_types(tmp_path):
    engine = await _engine(tmp_path)
    async with session_scope(engine) as s:
        await seed_default_routing(s)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(AlertRouting))).scalars().all()
        types = {r.type for r in rows}
        assert types == {t.value for t in AlertType}


@pytest.mark.asyncio
async def test_seed_idempotent(tmp_path):
    engine = await _engine(tmp_path)
    async with session_scope(engine) as s:
        await seed_default_routing(s)
    async with session_scope(engine) as s:
        await seed_default_routing(s)   # second call is a no-op
    async with session_scope(engine) as s:
        rows = (await s.execute(select(AlertRouting))).scalars().all()
        assert len(rows) == len(AlertType)


@pytest.mark.asyncio
async def test_get_routing_returns_channels_and_enabled(tmp_path):
    engine = await _engine(tmp_path)
    async with session_scope(engine) as s:
        await seed_default_routing(s)
    async with session_scope(engine) as s:
        channels, enabled = await get_routing(s, AlertType.watchlist_hit)
    assert "push" in channels and "email" in channels
    assert enabled is True


@pytest.mark.asyncio
async def test_get_routing_respects_disabled_flag(tmp_path):
    engine = await _engine(tmp_path)
    async with session_scope(engine) as s:
        await seed_default_routing(s)
        row = (await s.execute(
            select(AlertRouting).where(AlertRouting.type == AlertType.new_match.value)
        )).scalar_one()
        row.enabled = False
    async with session_scope(engine) as s:
        _channels, enabled = await get_routing(s, AlertType.new_match)
    assert enabled is False


def test_default_routing_covers_all_alert_types():
    for t in AlertType:
        assert t.value in DEFAULT_ROUTING


def test_default_routing_digest_only_types_have_empty_channels():
    # schedule_posted, site_stagnant, no_matches_for_kid roll into digest only
    for t in ("schedule_posted", "site_stagnant", "no_matches_for_kid"):
        assert DEFAULT_ROUTING[t] == []


def test_default_routing_reg_opens_now_has_push_and_email():
    assert "push" in DEFAULT_ROUTING["reg_opens_now"]
    assert "email" in DEFAULT_ROUTING["reg_opens_now"]
```

Run: `uv run pytest tests/unit/test_alerts_routing.py -v` — expect ImportError.

- [ ] **Step 2: Implement `src/yas/alerts/routing.py`**

```python
"""Alert routing: reads alert_routing table; seeds defaults on first run."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import AlertRouting
from yas.db.models._types import AlertType

DEFAULT_ROUTING: dict[str, list[str]] = {
    AlertType.watchlist_hit.value: ["push", "email"],
    AlertType.new_match.value: ["email"],
    AlertType.reg_opens_24h.value: ["email"],
    AlertType.reg_opens_1h.value: ["push"],
    AlertType.reg_opens_now.value: ["push", "email"],
    AlertType.schedule_posted.value: [],         # digest only
    AlertType.crawl_failed.value: ["email"],
    AlertType.digest.value: ["email"],
    AlertType.site_stagnant.value: [],            # digest only
    AlertType.no_matches_for_kid.value: [],       # digest only
}


async def seed_default_routing(session: AsyncSession) -> None:
    """Ensure alert_routing has a row for every AlertType. Idempotent."""
    existing_types = set(
        (await session.execute(select(AlertRouting.type))).scalars().all()
    )
    for alert_type, channels in DEFAULT_ROUTING.items():
        if alert_type in existing_types:
            continue
        session.add(AlertRouting(
            type=alert_type, channels=channels, enabled=True,
        ))
    await session.flush()


async def get_routing(
    session: AsyncSession, alert_type: AlertType,
) -> tuple[list[str], bool]:
    """Return (channels, enabled) for the given alert type. Falls back to
    DEFAULT_ROUTING + enabled=True if the row is missing."""
    row = (
        await session.execute(
            select(AlertRouting).where(AlertRouting.type == alert_type.value)
        )
    ).scalar_one_or_none()
    if row is None:
        return (DEFAULT_ROUTING.get(alert_type.value, []), True)
    return (list(row.channels or []), bool(row.enabled))
```

- [ ] **Step 3: Run + commit**

```bash
uv run pytest tests/unit/test_alerts_routing.py -v
uv run pytest
uv run ruff check .
uv run mypy src
git add src/yas/alerts/routing.py tests/unit/test_alerts_routing.py
git commit -m "feat(alerts): seed default routing table and lookup helper"
```

---

## Task 5 — Notifier protocol + FakeNotifier + aiosmtpd fixture

**Files:**
- Modify: `pyproject.toml` (add `aiosmtplib`, `aiosmtpd`)
- Create: `src/yas/alerts/channels/__init__.py` (empty)
- Create: `src/yas/alerts/channels/base.py` — `Notifier` Protocol + `NotifierMessage` + `SendResult` + `NotifierCapability`
- Create: `tests/fakes/notifier.py` — `FakeNotifier`
- Create: `tests/fakes/smtp_server.py` — `aiosmtpd`-based fixture helper
- Create: `tests/unit/test_alerts_channel_base.py` — minimal Protocol conformance test

- [ ] **Step 1: Add deps**

Edit `pyproject.toml`. In `[project].dependencies`, append:
```
  "aiosmtplib>=3.0",
```

In `[dependency-groups].dev`, append:
```
  "aiosmtpd>=1.4",
```

Run: `uv sync`

- [ ] **Step 2: Failing test**

`tests/unit/test_alerts_channel_base.py`:

```python
import pytest

from yas.alerts.channels.base import (
    Notifier,
    NotifierCapability,
    NotifierMessage,
    SendResult,
)
from yas.db.models._types import AlertType


def test_send_result_shape():
    r = SendResult(ok=True, transient_failure=False, detail="sent")
    assert r.ok is True


def test_notifier_message_urgent_default_false():
    m = NotifierMessage(
        kid_id=1, alert_type=AlertType.new_match,
        subject="Sub", body_plain="body",
    )
    assert m.urgent is False
    assert m.body_html is None


def test_fake_notifier_records_sends():
    from tests.fakes.notifier import FakeNotifier
    f = FakeNotifier(name="fake", capabilities={NotifierCapability.email})
    assert f.name == "fake"
    assert NotifierCapability.email in f.capabilities


def test_notifier_capability_push_emergency_distinct():
    assert NotifierCapability.push_emergency != NotifierCapability.push
```

Run: `uv run pytest tests/unit/test_alerts_channel_base.py -v` — expect ImportError.

- [ ] **Step 3: Implement `src/yas/alerts/channels/__init__.py`** (empty)

- [ ] **Step 4: Implement `src/yas/alerts/channels/base.py`**

```python
"""Notifier protocol, message + result dataclasses, capability enum."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from yas.db.models._types import AlertType


class NotifierCapability(StrEnum):
    email = "email"
    push = "push"
    push_emergency = "push_emergency"   # retry-until-ack (Pushover priority=2)


@dataclass(frozen=True)
class NotifierMessage:
    kid_id: int | None
    alert_type: AlertType
    subject: str
    body_plain: str
    body_html: str | None = None
    url: str | None = None
    urgent: bool = False


@dataclass(frozen=True)
class SendResult:
    ok: bool
    transient_failure: bool
    detail: str


class Notifier(Protocol):
    name: str
    capabilities: set[NotifierCapability]

    async def send(self, msg: NotifierMessage) -> SendResult: ...
    async def aclose(self) -> None: ...
```

- [ ] **Step 5: Implement `tests/fakes/notifier.py`**

```python
"""FakeNotifier — records send() calls; configurable transient/non-transient failures."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from yas.alerts.channels.base import (
    NotifierCapability,
    NotifierMessage,
    SendResult,
)


@dataclass
class FakeNotifier:
    name: str = "fake"
    capabilities: set[NotifierCapability] = field(
        default_factory=lambda: {NotifierCapability.email}
    )
    records: list[NotifierMessage] = field(default_factory=list)
    # Queue of pre-baked results; if empty, every send returns ok=True.
    result_queue: list[SendResult] = field(default_factory=list)
    call_count: int = 0

    async def send(self, msg: NotifierMessage) -> SendResult:
        self.call_count += 1
        self.records.append(msg)
        if self.result_queue:
            return self.result_queue.pop(0)
        return SendResult(ok=True, transient_failure=False, detail="fake ok")

    async def aclose(self) -> None:
        pass

    def queue_transient_failure(self, detail: str = "boom") -> None:
        self.result_queue.append(SendResult(ok=False, transient_failure=True, detail=detail))

    def queue_permanent_failure(self, detail: str = "no auth") -> None:
        self.result_queue.append(SendResult(ok=False, transient_failure=False, detail=detail))
```

- [ ] **Step 6: Implement `tests/fakes/smtp_server.py`**

```python
"""Thin wrapper over aiosmtpd for in-memory SMTP testing.

Used by EmailChannel SMTP-transport tests so we don't have to mock
aiosmtplib. Spin up the server in a fixture; it records every message."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as default_policy

from aiosmtpd.controller import Controller


@dataclass
class CapturedMessage:
    from_addr: str
    to_addrs: tuple[str, ...]
    message: EmailMessage


class _Handler:
    def __init__(self, sink: list[CapturedMessage]):
        self._sink = sink

    async def handle_DATA(self, server, session, envelope):
        msg = BytesParser(policy=default_policy).parsebytes(envelope.content)
        self._sink.append(CapturedMessage(
            from_addr=envelope.mail_from,
            to_addrs=tuple(envelope.rcpt_tos),
            message=msg,  # type: ignore[arg-type]
        ))
        return "250 OK"


@dataclass
class FakeSMTPServer:
    host: str
    port: int
    captured: list[CapturedMessage] = field(default_factory=list)


@asynccontextmanager
async def fake_smtp_server() -> AsyncIterator[FakeSMTPServer]:
    captured: list[CapturedMessage] = []
    controller = Controller(_Handler(captured), hostname="127.0.0.1", port=0)
    controller.start()
    try:
        yield FakeSMTPServer(
            host=controller.hostname,
            port=controller.server.sockets[0].getsockname()[1],
            captured=captured,
        )
    finally:
        controller.stop()
```

- [ ] **Step 7: Run + commit**

```bash
uv run pytest tests/unit/test_alerts_channel_base.py -v
uv run pytest
uv run ruff check .
uv run mypy src
git add pyproject.toml uv.lock src/yas/alerts/channels/__init__.py src/yas/alerts/channels/base.py \
    tests/fakes/notifier.py tests/fakes/smtp_server.py tests/unit/test_alerts_channel_base.py
git commit -m "feat(alerts): add Notifier protocol + FakeNotifier + aiosmtpd test fixture"
```

---

## Task 6 — EmailChannel with SMTP + ForwardEmail transports

**Files:**
- Create: `src/yas/alerts/channels/email.py` — `EmailChannel`, `_SMTPTransport`, `_ForwardEmailTransport`, `_build_email`
- Create: `tests/unit/test_alerts_email_channel.py`

The biggest single file in Phase 4 (~250 lines of source) because it houses two transports behind a shared builder. Use EXACT file paths; do not split.

### Implementer brief

This task is substantial enough to merit subagent-driven execution. The implementer should:

1. Write the test file verbatim. It exercises:
   - SMTP transport against the `fake_smtp_server()` fixture: assert message arrival, subject, From, To, multipart/alternative structure with plain+html parts
   - ForwardEmail transport against `respx`: assert POST to `https://api.forwardemail.net/v1/emails`, Basic Auth header with token from config's env var, form fields `from`, `to`, `subject`, `text`, `html`
   - `EmailChannel` selects transport from `transport` config field; missing transport → ValueError
   - Both transports produce `SendResult(ok=True, transient_failure=False, detail=...)` on success
   - SMTP transport: 5xx SMTP code → non-transient (permanent, per RFC 5321); 4xx / connection refused / timeout → transient
   - ForwardEmail transport: 4xx (not 429) → non-transient; 429 / 5xx / timeout → transient

2. Implement the email module with a shared `_build_email(subject, from_addr, to_addrs, text, html) -> email.message.EmailMessage` helper that produces multipart/alternative. Both transports send this.

3. The `EmailChannel.__init__(config: dict)` picks transport by `config["transport"]`. Each transport reads its own config subset (SMTP: host, port, username, password_env, use_tls, from_addr, to_addrs; ForwardEmail: api_token_env, from_addr, to_addrs). Secrets resolved via `os.environ.get(env_name)`; missing secret → transport init raises `ValueError("channel disabled: missing env var X")` which the delivery worker catches at startup.

4. Capabilities: `{NotifierCapability.email}`.

Full plan depends on the implementer reading the spec §3.9.1 and the shape in the test file. Keep the module narrowly focused — no retry logic (delivery worker owns retries).

- [ ] **Step 1: Write test file**

Failing tests as described in the implementer brief above. See the spec § 6.3 for the assertions to cover.

- [ ] **Step 2: Implement**

Write `src/yas/alerts/channels/email.py` per the spec.

- [ ] **Step 3: Run + gate + commit**

```bash
uv run pytest tests/unit/test_alerts_email_channel.py -v
uv run pytest
uv run ruff check .
uv run mypy src
git add src/yas/alerts/channels/email.py tests/unit/test_alerts_email_channel.py
git commit -m "feat(alerts): add EmailChannel with SMTP and ForwardEmail transports"
```

---

## Task 7 — NtfyChannel + PushoverChannel

**Files:**
- Create: `src/yas/alerts/channels/ntfy.py`
- Create: `src/yas/alerts/channels/pushover.py`
- Create: `tests/unit/test_alerts_ntfy_channel.py`
- Create: `tests/unit/test_alerts_pushover_channel.py`

Both are ~80 lines each, same shape (httpx POST against mocked endpoint). Combine into one commit since they're sibling adapters with symmetric tests.

### Implementer brief

**NtfyChannel** (spec §3.9.2):
- config fields: `base_url`, `topic`, `auth_token_env` (optional)
- `send()`: `httpx.AsyncClient.post(f"{base_url}/{topic}")` with headers `Title`, `Priority: high` when `msg.urgent` else default, `Click: {msg.url}` if set, `Authorization: Bearer <token>` if configured
- body: `msg.body_plain`
- Capabilities: `{push}`
- Error taxonomy: 4xx → non-transient; 429 / 5xx / transport → transient

**PushoverChannel** (spec §3.9.3):
- config fields: `user_key_env`, `app_token_env`, `devices` (optional list), `emergency_retry_s`, `emergency_expire_s`
- `send()`: `httpx.AsyncClient.post("https://api.pushover.net/1/messages.json")` form-encoded
- Fields: `token`, `user`, `title=msg.subject`, `message=msg.body_plain`, `url`/`url_title` if set, `priority=2 if msg.alert_type == reg_opens_now else 0`, `retry`+`expire` when priority=2, `devices` (comma-separated) if configured
- Capabilities: `{push, push_emergency}`
- Error taxonomy: Pushover API returns `status:1` on success; `status:0` + `errors` array on failure. 429 / 5xx → transient; 4xx with `status:0` → non-transient.

- [ ] **Step 1: Write both test files** (failing)

Use `respx` in each. Named must-have: `test_pushover_priority_2_for_reg_opens_now`.

- [ ] **Step 2: Implement both**

- [ ] **Step 3: Run + commit**

```bash
uv run pytest tests/unit/test_alerts_ntfy_channel.py tests/unit/test_alerts_pushover_channel.py -v
uv run pytest
uv run ruff check .
uv run mypy src
git add src/yas/alerts/channels/ntfy.py src/yas/alerts/channels/pushover.py \
    tests/unit/test_alerts_ntfy_channel.py tests/unit/test_alerts_pushover_channel.py
git commit -m "feat(alerts): add NtfyChannel and PushoverChannel with priority=2 for reg_opens_now"
```

---

## Task 8 — Detectors: site_stagnant + no_matches_for_kid

**Files:**
- Create: `src/yas/alerts/detectors/__init__.py` (empty)
- Create: `src/yas/alerts/detectors/site_stagnant.py`
- Create: `src/yas/alerts/detectors/no_matches_for_kid.py`
- Create: `tests/unit/test_alerts_detectors.py`

Two pure-SQL detectors. Seed the DB, run, assert the returned id set.

### Implementer brief

**`detect_stagnant_sites(session, threshold_days=30)`** — return active, non-muted `site_id`s where the most recent `offerings.first_seen` for the site is older than `threshold_days`. **Exclude** sites with zero offerings entirely (fresh registrations) — don't nag during the first N days after adding a site. Use a LEFT JOIN + MAX(first_seen) pattern, or equivalent.

**`detect_kids_without_matches(session, threshold_days=7)`** — return `kid_id`s where `kid.active=True AND kid.created_at <= now - threshold_days` AND zero rows exist in `matches` for the kid (ever — not just active).

Must-have tests:
- `test_site_stagnant_detector_ignores_fresh_sites`
- `test_no_matches_for_kid_detector_requires_N_days_active`

Plus: muted site excluded; inactive site excluded; site with a recent offering excluded.

- [ ] **Step 1: Write tests** (failing — import errors)

- [ ] **Step 2: Implement both**

- [ ] **Step 3: Run + commit**

```bash
git add src/yas/alerts/detectors/__init__.py \
    src/yas/alerts/detectors/site_stagnant.py \
    src/yas/alerts/detectors/no_matches_for_kid.py \
    tests/unit/test_alerts_detectors.py
git commit -m "feat(alerts): add site_stagnant and no_matches_for_kid detectors"
```

---

## Task 9 — Delivery loop: send-one-group + retry + polling

**Files:**
- Create: `src/yas/alerts/delivery.py` — `send_alert_group` orchestrator with retry taxonomy
- Create: `src/yas/worker/delivery_loop.py` — `alert_delivery_loop` polling task
- Create: `tests/integration/test_alerts_delivery_loop.py`

### Implementer brief

`send_alert_group(session, group: AlertGroup, notifiers: dict[str, Notifier], settings, household) -> None`:

1. Look up routing for `group.alert_type` via `get_routing`.
2. Build a `NotifierMessage` from the group (see body rendering below).
3. For each channel in routing:
   - Resolve `channel_name → NotifierCapability` → pick a `Notifier` with that capability (per-channel-name lookup from `notifiers` dict; for `reg_opens_now`, prefer the one with `push_emergency`; log downgrade otherwise).
   - Apply quiet-hours filter when the capability is `push` AND alert_type is not `reg_opens_now`.
   - Apply rate-cap when capability includes `push`; on cap reached, call `enqueue_push_cap(session, kid_id=..., hour_bucket=...)` (added to `enqueuer.py` in Task 2) whose dedup_key is `push_cap:{kid_id}:{hour_bucket}` — keeps all alert inserts flowing through the same upsert path so dedup logic stays in one place.
   - Call `notifier.send(msg)`; on success set `sent_at=now`, `channels += [notifier.name]`; on transient failure update `scheduled_for` per retry table (attempt 1 → +60s, 2 → +5m, 3 → +30m, 4 → skipped); on non-transient failure mark skipped with detail.

`alert_delivery_loop(engine, settings, notifiers)`:

```python
async def alert_delivery_loop(engine, settings, notifiers) -> None:
    log.info("delivery.start", tick_s=settings.alert_delivery_tick_s)
    try:
        while True:
            async with session_scope(engine) as s:
                # Load the single household_settings row each tick — quiet-hours
                # and rate-cap depend on its fields. Loaded fresh so config
                # edits via API take effect without worker restart.
                household = (await s.execute(
                    select(HouseholdSettings).limit(1)
                )).scalar_one_or_none()
                due = (await s.execute(
                    select(Alert).where(
                        Alert.sent_at.is_(None),
                        Alert.skipped.is_(False),
                        Alert.scheduled_for <= datetime.now(UTC),
                    ).order_by(Alert.scheduled_for).limit(100)
                )).scalars().all()
                # startup grace window → mark too-old skipped
                groups = coalesce(due, window_s=settings.alert_coalesce_normal_s)
                for g in groups:
                    await send_alert_group(s, g, notifiers, settings, household)
            await asyncio.sleep(settings.alert_delivery_tick_s)
    except asyncio.CancelledError:
        log.info("delivery.stop")
        raise
```

Integration tests (`tests/integration/test_alerts_delivery_loop.py`) use `FakeNotifier` keyed by channel name. Named must-have tests:
- `test_reg_opens_now_bypasses_quiet_hours`
- `test_push_rate_cap_coalesces_excess_to_single_message`
- `test_coalesce_merges_within_window_but_not_across_types`
- `test_startup_grace_window_fires_recent_past_due_countdown_once`

- [ ] **Step 1: Write tests** (failing)

- [ ] **Step 2: Implement delivery.py + delivery_loop.py**

- [ ] **Step 3: Run + commit**

```bash
git add src/yas/alerts/delivery.py src/yas/worker/delivery_loop.py \
    tests/integration/test_alerts_delivery_loop.py
git commit -m "feat(alerts): add delivery loop with coalesce + retry + rate cap + quiet hours"
```

---

## Task 10 — Digest: builder + Jinja templates + filters

**Files:**
- Create: `src/yas/alerts/digest/__init__.py` (empty)
- Create: `src/yas/alerts/digest/builder.py` — `gather_digest_payload` + `render_digest`
- Create: `src/yas/alerts/digest/filters.py` — `price`, `rel_date`, `fmt`
- Create: `src/yas/alerts/digest/templates/digest.html.j2`
- Create: `src/yas/alerts/digest/templates/digest.txt.j2`
- Create: `tests/unit/test_alerts_digest_builder.py`
- Create: `tests/unit/test_alerts_digest_filters.py`

### Implementer brief

`gather_digest_payload(session, kid, *, window_start, window_end, alert_no_matches_kid_days) -> DigestPayload` queries per spec §3.11 step 1:

- `new_matches`: matches where `computed_at >= window_start`
- `starting_soon`: kid's matched offerings with `start_date ∈ (today, today+14d]`
- `registration_calendar`: matched offerings with `registration_opens_at ∈ (now, now+14d]`
- `delivery_failures`: `alerts` where `skipped=true AND sent_at >= last_digest_sent_for_this_kid OR window_start, whichever is earlier`
- `site_stagnant_ids`: from `detect_stagnant_sites`
- Determine "is-under-no-matches-threshold": `kid.created_at >= now - alert_no_matches_kid_days AND no matches ever`

`render_digest(payload, top_line) -> tuple[str, str]` returns `(body_plain, body_html)` using Jinja2 env loaded from `src/yas/alerts/digest/templates/`. Register `price`, `rel_date`, `fmt` as filters.

**Filter behavior:**
- `price(cents)` → `"$85.00"` or `""` when None
- `rel_date(d)` → `"Sat, May 2"` within 30 days, `"in 3 days"` within a week, `"May 2, 2026"` beyond
- `fmt(dt)` → `"Tue 9:00 AM May 6"` (abbrev weekday, 12h time, abbrev month)

Templates from spec §3.11; produce both HTML (minimal inline CSS) and plain-text variants.

- [ ] **Step 1: Write filter tests** (failing)

- [ ] **Step 2: Implement filters**

- [ ] **Step 3: Write builder tests** (seeded DB; assert `gather_digest_payload` shape and counts)

- [ ] **Step 4: Implement builder + templates**

- [ ] **Step 5: Run + commit**

```bash
git add src/yas/alerts/digest/ tests/unit/test_alerts_digest_builder.py tests/unit/test_alerts_digest_filters.py
git commit -m "feat(alerts): add digest builder, filters, and HTML+text templates"
```

---

## Task 11 — Digest LLM top-line with fallback

**Files:**
- Create: `src/yas/alerts/digest/llm_summary.py`
- Create: `tests/unit/test_alerts_digest_llm_summary.py`

### Implementer brief

```python
async def generate_top_line(
    payload: DigestPayload, llm: LLMClient, *, cost_cap_remaining_usd: float,
) -> str:
```

Calls `llm.call_tool(...)` with a tool-use tool `report_top_line` whose input_schema is `{top_line: str}`. System prompt per spec §3.11 step 2. User input: JSON summary of counts + top item names (no full offering data).

**Fallback rules** (any of these → use template):
- LLM call raises
- LLM returns `top_line=""` or over 200 chars
- `cost_cap_remaining_usd < 0.01`

Fallback template: `"{kid_name}'s activities — {n_new} new matches, {n_reg_soon} opening soon"`.

The function must also accept `llm: LLMClient | None` — when `None` (e.g. api-only mode without Anthropic configured, matching the Phase 3.5 silent-failure-class pattern), go straight to the fallback template rather than raising.

Named must-have tests:
- `test_llm_top_line_falls_back_to_template_on_failure` (LLM raises)
- `test_llm_top_line_falls_back_to_template_when_llm_is_none` (LLM not configured)

- [ ] **Step 1: Tests** (failing)

- [ ] **Step 2: Implement**

- [ ] **Step 3: Run + commit**

```bash
git add src/yas/alerts/digest/llm_summary.py tests/unit/test_alerts_digest_llm_summary.py
git commit -m "feat(alerts): add LLM top-line generator with template fallback"
```

---

## Task 12 — Digest loop + detector loop + worker integration

**Files:**
- Create: `src/yas/worker/digest_loop.py` — `daily_digest_loop`
- Create: `src/yas/worker/detector_loop.py` — `daily_detector_loop`
- Modify: `src/yas/worker/runner.py` — add three new `create_task` calls (delivery + digest + detector); seed routing on startup; discover channel notifiers from household_settings config + env secrets
- Modify: `src/yas/__main__.py` — construct notifiers dict in `_run_all` (worker-side only; pass through to `alert_delivery_loop`)
- Create: `tests/integration/test_alerts_digest_loop.py`
- Create: `tests/integration/test_alerts_detector_loop.py`

### Implementer brief

`daily_digest_loop(engine, settings, llm)`:
- Tick pattern identical to Phase 3 sweep loop: every 60s, check if past `alert_digest_time_utc` AND not run today.
- Per active kid: `gather_digest_payload` → `generate_top_line` → `render_digest` → `enqueue_digest` (unless empty-day-skip applies AND kid isn't in no-matches-threshold window)
- Named must-have tests: `test_digest_empty_day_skipped_but_logs_debug`, `test_digest_no_matches_kid_under_threshold_sends_honest_message`

`daily_detector_loop(engine, settings)`:
- Tick pattern same. At `alert_detector_time_utc`: run `detect_stagnant_sites` → `enqueue_site_stagnant` for each; run `detect_kids_without_matches` → `enqueue_no_matches_for_kid` for each.

**Worker runner** (`runner.py`):
- Construct channel notifiers from `household_settings.smtp_config_json` / `ntfy_config_json` / `pushover_config_json`. Missing config → skip that channel. Missing env secrets (per Task 1 config) → instantiate but log "channel disabled: missing X".
- On startup, call `seed_default_routing(session)` under a session_scope.
- Pass `notifiers` dict into `alert_delivery_loop`.
- Add three `tg.create_task(...)` calls if `settings.alerts_enabled`.

**`__main__.py`** (`_run_all` and `worker` branches): construct notifiers dict for the worker path. Do NOT construct notifiers in the api-only branch or for `POST /api/digest/preview` — preview renders without sending, so it needs only the digest builder + template, not notifiers (YAGNI).

- [ ] **Step 1: Integration tests** (failing)

- [ ] **Step 2: Implement loops + runner updates**

- [ ] **Step 3: Run + commit**

```bash
git add src/yas/worker/digest_loop.py src/yas/worker/detector_loop.py \
    src/yas/worker/runner.py src/yas/__main__.py \
    tests/integration/test_alerts_digest_loop.py tests/integration/test_alerts_detector_loop.py
git commit -m "feat(alerts): add digest loop + detector loop + wire notifiers into worker"
```

---

## Task 13 — Pipeline + matcher event hooks

**Files:**
- Modify: `src/yas/crawl/pipeline.py` — enqueue_new_match / watchlist_hit / countdowns after reconcile+rematch; crawl_failed on 3 consecutive failures
- Modify: `src/yas/matching/matcher.py` — dedup against pipeline-path enqueuer (via dedup_key); call enqueue_new_match/watchlist_hit for every `MatchResult.new` entry
- Create: `tests/integration/test_alerts_pipeline_integration.py` — exercise full `crawl_page` → events → alerts rows

### Implementer brief

Pipeline (`pipeline.py`): after the existing rematch_offering loop, for each `new` or `updated` offering whose reconcile produced a match change:
- For each kid's new `matches` row:
  - If `reasons.watchlist_hit` is not None: `enqueue_watchlist_hit`
  - Else if `score >= kid.alert_score_threshold` AND `kid.alert_on.new_match` (checked by enqueuer): `enqueue_new_match`
- If the offering's `registration_opens_at` is newly set or changed: for each matched kid, `enqueue_registration_countdowns`
- If `page.consecutive_failures == 3`: `enqueue_crawl_failed`

Matcher (`matcher.py`): in the `_upsert_match` path, when `was_insert=True` (newly created), do the same enqueue_* calls. Rely on `dedup_key` to dedup against the pipeline-path calls.

`test_alerts_pipeline_integration.py`: drive a fake fetcher + fake LLM through the pipeline, assert:
- `alerts` rows appear with the right types/kid_ids
- Countdown scheduling fires when reconcile extracts `registration_opens_at`
- Watchlist hits alert even for kids with `alert_on.new_match=false`
- Named must-have: `test_countdown_rewrite_on_registration_date_change`
- Named must-have: `test_enqueue_new_match_dedups_across_pipeline_and_matcher_paths` — exercise an offering that triggers both the pipeline post-reconcile hook AND the matcher `_upsert_match` hook; assert exactly one `alerts` row exists for the `new_match` event (dedup_key collision).

- [ ] **Step 1: Integration test** (failing)

- [ ] **Step 2: Wire the hooks**

- [ ] **Step 3: Run + commit**

```bash
git add src/yas/crawl/pipeline.py src/yas/matching/matcher.py \
    tests/integration/test_alerts_pipeline_integration.py
git commit -m "feat(alerts): wire enqueuer into pipeline + matcher event hooks"
```

---

## Task 14 — HTTP: /api/alerts + /api/alerts/{id} + resend

**Files:**
- Create: `src/yas/web/routes/alerts.py`
- Create: `src/yas/web/routes/alerts_schemas.py`
- Modify: `src/yas/web/routes/__init__.py` (register router)
- Modify: `src/yas/web/app.py` (include router)
- Create: `tests/integration/test_api_alerts.py`

### Endpoints

- `GET /api/alerts?kid_id=&type=&status=&since=&until=&limit=&offset=` — paginated list; `status ∈ {pending, sent, skipped}`
- `GET /api/alerts/{id}` — detail
- `POST /api/alerts/{id}/resend` — clone the alert row with `scheduled_for=now, sent_at=None, skipped=False, dedup_key=<original>+":resend:<iso_now>"` (so resends never collide with future regular inserts)

### Schemas

`alerts_schemas.py`:
- `AlertOut`: from_attributes; fields: `id, type, kid_id, offering_id, site_id, channels, scheduled_for, sent_at, skipped, dedup_key, payload_json`
- `AlertListResponse`: `items: list[AlertOut]`, `total: int`, `limit: int`, `offset: int`

### Named must-have test

`test_alerts_resend_clones_original_payload` — resend a sent alert; assert new row exists with same payload, distinct dedup_key.

- [ ] **Step 1: Write failing integration tests** in `tests/integration/test_api_alerts.py` covering:
  - `GET /api/alerts` empty → 200 + `{items: [], total: 0, ...}`
  - `GET /api/alerts?kid_id=N` filters by kid
  - `GET /api/alerts?status=pending` returns only `sent_at is None AND skipped=False`
  - `GET /api/alerts?status=sent` returns only `sent_at IS NOT NULL`
  - `GET /api/alerts?status=skipped` returns only `skipped=True`
  - `GET /api/alerts?since=&until=` date-range filters on `scheduled_for`
  - `GET /api/alerts/{id}` returns detail; 404 for missing
  - `POST /api/alerts/{id}/resend` → 202, clones row, distinct dedup_key suffix
  - `test_alerts_resend_clones_original_payload` (named must-have)
- [ ] **Step 2: Implement** `alerts.py` + `alerts_schemas.py` per pattern from `src/yas/web/routes/kids.py` / `watchlist.py`. Keep routes thin; query logic stays within the handler.
- [ ] **Step 3: Run + commit**

```bash
uv run pytest tests/integration/test_api_alerts.py -v
git add src/yas/web/routes/alerts.py src/yas/web/routes/alerts_schemas.py \
    src/yas/web/routes/__init__.py src/yas/web/app.py \
    tests/integration/test_api_alerts.py
git commit -m "feat(web): add /api/alerts read + resend"
```

---

## Task 15 — HTTP: /api/alert_routing + /api/digest/preview

**Files:**
- Create: `src/yas/web/routes/alert_routing.py`
- Create: `src/yas/web/routes/alert_routing_schemas.py`
- Create: `src/yas/web/routes/digest_preview.py`
- Create: `src/yas/web/routes/digest_preview_schemas.py`
- Modify: `__init__.py`, `app.py` to register routers
- Create: `tests/integration/test_api_alert_routing.py`
- Create: `tests/integration/test_api_digest_preview.py`

### Endpoints

**`/api/alert_routing`:**
- `GET /` — return all rows as `list[AlertRoutingOut]`
- `PATCH /{type}` — update `channels` and/or `enabled` for one alert type. Validates `channels` only contains names of configured notifiers (pass validation if the notifier isn't configured yet — just document the discrepancy with a warning; don't hard-fail).

**`/api/digest/preview?kid_id=N`:**
- Build a digest for kid N RIGHT NOW (using past 24h window) and return `{subject, body_plain, body_html}` without enqueueing.
- Uses the existing `gather_digest_payload` + `generate_top_line` + `render_digest` path.

- [ ] Pattern follows Phase 3 route patterns. Tests assert round-trip shape.

Commit: `feat(web): add /api/alert_routing CRUD and /api/digest/preview`.

---

## Task 16 — Smoke script + Mailpit sidecar + README + phase exit verify

**Files:**
- Create: `docker-compose.smoke.yml` — adds Mailpit sidecar (image `axllent/mailpit`, ports 1025:1025 for SMTP + 8025:8025 for web UI)
- Create: `scripts/smoke_phase4.sh`
- Modify: `README.md`

### Smoke script behavior

```bash
# Use overlay: compose + macos + smoke (Mailpit sidecar)
COMPOSE="docker compose -f docker-compose.yml \
         $([ $(uname) = Darwin ] && echo '-f docker-compose.macos.yml') \
         -f docker-compose.smoke.yml"

$COMPOSE up -d
sleep 10

# Configure household email via Mailpit
curl ... /api/household -d '{"smtp_config_json": {"transport":"smtp", "host":"mailpit", ...}}'

# Add a kid, add a site, force a crawl
# Verify digest preview returns rendered content
curl ... /api/digest/preview?kid_id=1 | jq .

# Trigger a watchlist-hit pathway; verify email lands in Mailpit (http://localhost:8025)

# Optional: if YAS_PUSHOVER_USER_KEY is set, configure Pushover channel and trigger
# reg_opens_now synthetically; assert priority=2 push arrives.

$COMPOSE down
```

### README section

Append a "Alerting" section after the existing quickstart describing:
- Channel configuration via `household_settings` JSON fields
- Secrets resolved from env
- `POST /api/digest/preview` for inspecting what the daily digest would say
- Mailpit sidecar via `docker-compose.smoke.yml` for local email testing

### Exit gates

- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run mypy src`
- [ ] `uv run pytest`
- [ ] `./scripts/smoke_phase4.sh` (with Mailpit)
- [ ] `POST /api/digest/preview` returns 200 with HTML + text bodies
- [ ] Email delivered via SMTP → Mailpit received
- [ ] (Optional) Pushover priority=2 for reg_opens_now with real key

Commit: `docs: add phase-4 smoke + README alerting section + Mailpit sidecar`.

---

## Phase 4 exit checklist

Apply @superpowers:verification-before-completion. Every box verified with an actual command, not asserted.

- [ ] `uv run ruff check .` clean
- [ ] `uv run ruff format --check .` clean
- [ ] `uv run mypy src` clean
- [ ] `uv run pytest` — all new tests plus full suite green
- [ ] Docker Compose brings up all worker tasks (heartbeat, crawl scheduler, daily sweep, geocode enricher, alert delivery, digest loop, detector loop = 7 tasks)
- [ ] `scripts/smoke_phase4.sh` succeeds end-to-end with Mailpit
- [ ] All named must-have tests pass by name (listed in spec §6.5)
- [ ] No silent failures: the delivery worker writes debug logs for every decision (coalesced, rate-limited, quiet-hours suppressed, sent, failed)

When all boxes check, merge with `--no-ff` to `main`. Proceed to **Phase 5 — Web UI**, written as its own plan.
