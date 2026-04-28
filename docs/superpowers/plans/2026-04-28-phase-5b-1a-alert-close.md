# Phase 5b-1a — Alert Close (Backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an alert soft-close lifecycle (`closed_at` + `close_reason`) with `POST /close` and `POST /reopen` endpoints, and exclude closed alerts from `/api/inbox/summary` by default.

**Architecture:** Two nullable columns on `alerts`, one new `StrEnum`, two action-style routes following the existing `POST /{alert_id}/resend` precedent. The inbox summary gains one query parameter and one extra `WHERE` clause. Backend-only — frontend wiring is Phase 5b-1b.

**Tech Stack:** SQLAlchemy 2.x async, Alembic, FastAPI, Pydantic v2, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-04-28-phase-5b-1a-alert-close-design.md`

**Project conventions to maintain:**
- All Python deps already pinned to exact patch in `pyproject.toml`. Do NOT add new deps; this slice needs none.
- All commits must be signed via the 1Password SSH agent. Set `SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"` before each `git commit` in fresh shells (subagents do NOT inherit it). After commit, verify with `git cat-file commit HEAD | grep -q '^gpgsig '`.
- Backend gates: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`.
- Branch off `main` into `phase-5b-1a-alert-close`. Do NOT commit to `main` directly.

---

## File Structure

**Modify:**
- `src/yas/db/models/_types.py` — add `CloseReason` StrEnum.
- `src/yas/db/models/alert.py` — add `closed_at` + `close_reason` columns.
- `src/yas/web/routes/alerts_schemas.py` — extend `AlertOut`; add `AlertCloseIn`.
- `src/yas/web/routes/inbox_schemas.py` — extend `InboxAlertOut` with the two new fields.
- `src/yas/web/routes/inbox.py` — add `include_closed` query param + filter.
- `src/yas/web/routes/alerts.py` — add `POST /{alert_id}/close` + `POST /{alert_id}/reopen`.
- `tests/integration/test_api_inbox.py` — add 3 close-related test cases.

**Create:**
- `alembic/versions/0004_alert_close.py` — migration adding both columns + index.
- `tests/integration/test_api_alerts_close.py` — 10 test cases for the two new endpoints.

---

## Task 1 — Schema: enum, model columns, migration

**Files:**
- Modify: `src/yas/db/models/_types.py`
- Modify: `src/yas/db/models/alert.py`
- Create: `alembic/versions/0004_alert_close.py`

End state: Alert model has two new nullable columns, CloseReason enum is exported, migration applies cleanly to a fresh DB and to a DB at the previous head. Existing 528 backend tests still pass.

- [ ] **Step 1: Add `CloseReason` enum**

In `src/yas/db/models/_types.py`, append the new enum after `EnrollmentStatus` (or wherever fits the file's existing alphabetical/grouping order — match the surrounding style):

```python
class CloseReason(StrEnum):
    acknowledged = "acknowledged"
    dismissed = "dismissed"
```

The file already imports `StrEnum`; do not re-import.

- [ ] **Step 2: Add columns to the Alert model**

In `src/yas/db/models/alert.py`, add the import and the two new columns just before `__table_args__`:

```python
from yas.db.models._types import AlertType, CloseReason  # extend the existing import line
```

```python
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    close_reason: Mapped[CloseReason | None] = mapped_column(String, nullable=True)
```

Leave `__table_args__` as-is — the `index=True` on `closed_at` produces an auto-named index; no manual `Index(...)` entry is needed.

- [ ] **Step 3: Create the migration**

Create `alembic/versions/0004_alert_close.py`:

```python
"""add alert close columns.

Revision ID: 0004_alert_close
Revises: 0003_pushover_config_json
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_alert_close"
down_revision: str | Sequence[str] | None = "0003_pushover_config_json"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("close_reason", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_alerts_closed_at"),
        "alerts",
        ["closed_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_alerts_closed_at"), table_name="alerts")
    op.drop_column("alerts", "close_reason")
    op.drop_column("alerts", "closed_at")
```

- [ ] **Step 4: Verify migration applies cleanly**

```bash
rm -f data/activities.db
mkdir -p data
uv run alembic upgrade head
uv run alembic current
```

Expected: `0004_alert_close (head)` printed by `alembic current`. No tracebacks.

- [ ] **Step 5: Verify migration rolls back cleanly**

```bash
uv run alembic downgrade -1
uv run alembic current
```

Expected: `0003_pushover_config_json (head)`.

Then re-upgrade:

```bash
uv run alembic upgrade head
```

- [ ] **Step 6: Run the existing test suite to confirm nothing regressed**

```bash
uv run pytest -q
```

Expected: 528 passed (the new columns are nullable, existing seeds don't set them, no behavior change yet).

- [ ] **Step 7: Run lint/format/type gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Expected: all clean.

- [ ] **Step 8: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add src/yas/db/models/_types.py src/yas/db/models/alert.py alembic/versions/0004_alert_close.py
git commit -m "feat(db): add alert close columns + CloseReason enum

Adds closed_at (indexed) and close_reason (CloseReason enum)
nullable columns to alerts. No behavior change yet — endpoints
land in the next task."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 2 — Pydantic schemas: AlertOut, AlertCloseIn, InboxAlertOut

**Files:**
- Modify: `src/yas/web/routes/alerts_schemas.py`
- Modify: `src/yas/web/routes/inbox_schemas.py`

End state: `AlertOut` and `InboxAlertOut` expose `closed_at` and `close_reason`. New `AlertCloseIn` request model exists for the close endpoint. Existing endpoints continue returning the same shape (with the new fields populated as `null` for all existing rows).

- [ ] **Step 1: Extend AlertOut and add AlertCloseIn**

In `src/yas/web/routes/alerts_schemas.py`, add the import and two field additions:

```python
from yas.db.models._types import CloseReason
```

In `AlertOut`, append after `payload_json`:

```python
    closed_at: datetime | None = None
    close_reason: CloseReason | None = None
```

Append a new model after `AlertListResponse`:

```python
class AlertCloseIn(BaseModel):
    """Request body for POST /api/alerts/{id}/close."""

    reason: CloseReason
```

- [ ] **Step 2: Extend InboxAlertOut**

In `src/yas/web/routes/inbox_schemas.py`:

```python
from yas.db.models._types import CloseReason
```

In `InboxAlertOut`, append after `summary_text`:

```python
    closed_at: datetime | None = None
    close_reason: CloseReason | None = None
```

- [ ] **Step 3: Verify existing tests still pass**

```bash
uv run pytest -q
```

Expected: 528 passed. Existing `AlertOut`/`InboxAlertOut` consumers should still work — the new fields default to `None` for any row whose `closed_at` is null.

- [ ] **Step 4: Lint/format/type**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

- [ ] **Step 5: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add src/yas/web/routes/alerts_schemas.py src/yas/web/routes/inbox_schemas.py
git commit -m "feat(api): expose closed_at + close_reason on AlertOut/InboxAlertOut"
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 3 — `POST /api/alerts/{id}/close` (TDD)

**Files:**
- Create: `tests/integration/test_api_alerts_close.py`
- Modify: `src/yas/web/routes/alerts.py`

End state: The close endpoint exists, 7 new tests pass, existing tests still pass.

- [ ] **Step 1: Write the new test file with the close test cases**

Create `tests/integration/test_api_alerts_close.py`:

```python
"""Integration tests for POST /api/alerts/{id}/close and /reopen."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import Alert, Kid
from yas.db.models._types import AlertType
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
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        await s.flush()
        s.add(
            Alert(
                id=1,
                type=AlertType.watchlist_hit,
                kid_id=1,
                channels=["email"],
                scheduled_for=datetime.now(UTC) - timedelta(hours=1),
                sent_at=None,
                skipped=False,
                dedup_key="open-1",
                payload_json={"msg": "open"},
            )
        )
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_close_alert_with_acknowledged_sets_fields(client):
    c, _ = client
    r = await c.post("/api/alerts/1/close", json={"reason": "acknowledged"})
    assert r.status_code == 200
    body = r.json()
    assert body["close_reason"] == "acknowledged"
    assert body["closed_at"] is not None


@pytest.mark.asyncio
async def test_close_alert_with_dismissed_sets_fields(client):
    c, _ = client
    r = await c.post("/api/alerts/1/close", json={"reason": "dismissed"})
    assert r.status_code == 200
    body = r.json()
    assert body["close_reason"] == "dismissed"
    assert body["closed_at"] is not None


@pytest.mark.asyncio
async def test_closing_already_closed_with_same_reason_is_idempotent(client):
    c, _ = client
    first = await c.post("/api/alerts/1/close", json={"reason": "acknowledged"})
    closed_at_first = first.json()["closed_at"]

    second = await c.post("/api/alerts/1/close", json={"reason": "acknowledged"})
    assert second.status_code == 200
    assert second.json()["close_reason"] == "acknowledged"
    # closed_at MUST NOT advance on a same-reason re-close.
    assert second.json()["closed_at"] == closed_at_first


@pytest.mark.asyncio
async def test_closing_already_closed_with_different_reason_updates_reason(client):
    c, _ = client
    first = await c.post("/api/alerts/1/close", json={"reason": "acknowledged"})
    closed_at_first = first.json()["closed_at"]

    second = await c.post("/api/alerts/1/close", json={"reason": "dismissed"})
    assert second.status_code == 200
    assert second.json()["close_reason"] == "dismissed"
    # Last-write-wins on reason; closed_at does NOT advance.
    assert second.json()["closed_at"] == closed_at_first


@pytest.mark.asyncio
async def test_close_returns_404_for_unknown_id(client):
    c, _ = client
    r = await c.post("/api/alerts/9999/close", json={"reason": "acknowledged"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_close_returns_422_when_reason_missing(client):
    c, _ = client
    r = await c.post("/api/alerts/1/close", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_close_returns_422_for_invalid_reason(client):
    c, _ = client
    r = await c.post("/api/alerts/1/close", json={"reason": "snoozed"})
    assert r.status_code == 422
```

- [ ] **Step 2: Run the new tests to confirm they all fail (no endpoint yet)**

```bash
uv run pytest tests/integration/test_api_alerts_close.py -q
```

Expected: 7 failures. Most will be 405 Method Not Allowed (the route doesn't exist) — that's fine, the tests are red.

- [ ] **Step 3: Implement the close endpoint**

In `src/yas/web/routes/alerts.py`, add to the existing imports:

```python
from yas.db.models._types import AlertType, CloseReason
from yas.web.routes.alerts_schemas import AlertCloseIn, AlertListResponse, AlertOut
```

Append the new route at the bottom of the file (after `resend_alert`):

```python
@router.post("/{alert_id}/close", response_model=AlertOut)
async def close_alert(request: Request, alert_id: int, body: AlertCloseIn) -> AlertOut:
    async with session_scope(_engine(request)) as s:
        alert = (await s.execute(select(Alert).where(Alert.id == alert_id))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
        if alert.closed_at is None:
            alert.closed_at = datetime.now(UTC)
        # Always update reason (last-write-wins for re-close with different reason).
        alert.close_reason = body.reason
        await s.flush()
        return AlertOut.model_validate(alert)
```

- [ ] **Step 4: Run the close tests; confirm all 7 pass**

```bash
uv run pytest tests/integration/test_api_alerts_close.py -q
```

Expected: 7 passed.

- [ ] **Step 5: Run the full backend suite**

```bash
uv run pytest -q
```

Expected: 535 passed (528 + 7).

- [ ] **Step 6: Lint/format/type**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

- [ ] **Step 7: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add tests/integration/test_api_alerts_close.py src/yas/web/routes/alerts.py
git commit -m "feat(api): POST /api/alerts/{id}/close (idempotent, last-reason-wins)"
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 4 — `POST /api/alerts/{id}/reopen` (TDD)

**Files:**
- Modify: `tests/integration/test_api_alerts_close.py`
- Modify: `src/yas/web/routes/alerts.py`

End state: 3 new reopen tests pass; total close-tests-file count is 10.

- [ ] **Step 1: Append reopen test cases**

Append to `tests/integration/test_api_alerts_close.py`:

```python
@pytest.mark.asyncio
async def test_reopen_clears_both_fields(client):
    c, _ = client
    await c.post("/api/alerts/1/close", json={"reason": "acknowledged"})
    r = await c.post("/api/alerts/1/reopen")
    assert r.status_code == 200
    body = r.json()
    assert body["closed_at"] is None
    assert body["close_reason"] is None


@pytest.mark.asyncio
async def test_reopen_already_open_is_idempotent(client):
    c, _ = client
    r = await c.post("/api/alerts/1/reopen")
    assert r.status_code == 200
    assert r.json()["closed_at"] is None
    assert r.json()["close_reason"] is None


@pytest.mark.asyncio
async def test_reopen_returns_404_for_unknown_id(client):
    c, _ = client
    r = await c.post("/api/alerts/9999/reopen")
    assert r.status_code == 404
```

- [ ] **Step 2: Run new tests to confirm 3 fail**

```bash
uv run pytest tests/integration/test_api_alerts_close.py::test_reopen_clears_both_fields tests/integration/test_api_alerts_close.py::test_reopen_already_open_is_idempotent tests/integration/test_api_alerts_close.py::test_reopen_returns_404_for_unknown_id -q
```

Expected: 3 failures.

- [ ] **Step 3: Implement reopen endpoint**

Append to `src/yas/web/routes/alerts.py`:

```python
@router.post("/{alert_id}/reopen", response_model=AlertOut)
async def reopen_alert(request: Request, alert_id: int) -> AlertOut:
    async with session_scope(_engine(request)) as s:
        alert = (await s.execute(select(Alert).where(Alert.id == alert_id))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
        alert.closed_at = None
        alert.close_reason = None
        await s.flush()
        return AlertOut.model_validate(alert)
```

- [ ] **Step 4: Run all 10 close-related tests**

```bash
uv run pytest tests/integration/test_api_alerts_close.py -q
```

Expected: 10 passed.

- [ ] **Step 5: Full suite + gates**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: 538 passed.

- [ ] **Step 6: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add tests/integration/test_api_alerts_close.py src/yas/web/routes/alerts.py
git commit -m "feat(api): POST /api/alerts/{id}/reopen (idempotent)"
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 5 — Inbox summary: default-exclude closed alerts + `?include_closed` (TDD)

**Files:**
- Modify: `tests/integration/test_api_inbox.py`
- Modify: `src/yas/web/routes/inbox.py`

End state: Inbox summary excludes closed alerts by default. `?include_closed=true` opts back in. The `schedule_posted` site-distinct count at `inbox.py:131` is unaffected by close status. 3 new tests pass.

- [ ] **Step 1: Add 3 new test cases to `tests/integration/test_api_inbox.py`**

Append at the bottom of the file. Reuse the existing `client` fixture and `_iso` helper. Make sure imports include `CloseReason` and (if not already) `Site` / `AlertType` (they almost certainly already are):

```python
from yas.db.models._types import CloseReason  # add to existing imports
```

```python
@pytest.mark.asyncio
async def test_inbox_summary_excludes_closed_alerts_by_default(client):
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        await s.flush()
        s.add(
            Alert(
                id=1,
                type=AlertType.watchlist_hit,
                kid_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=1),
                dedup_key="open-1",
                payload_json={},
            )
        )
        s.add(
            Alert(
                id=2,
                type=AlertType.watchlist_hit,
                kid_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=2),
                dedup_key="closed-1",
                payload_json={},
                closed_at=now,
                close_reason=CloseReason.acknowledged,
            )
        )
    r = await c.get(
        "/api/inbox/summary",
        params={"since": _iso(now - timedelta(days=1)), "until": _iso(now + timedelta(days=1))},
    )
    assert r.status_code == 200
    ids = {a["id"] for a in r.json()["alerts"]}
    assert ids == {1}


@pytest.mark.asyncio
async def test_inbox_summary_with_include_closed_returns_closed_alerts(client):
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        await s.flush()
        s.add(
            Alert(
                id=1,
                type=AlertType.watchlist_hit,
                kid_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=1),
                dedup_key="open-1",
                payload_json={},
            )
        )
        s.add(
            Alert(
                id=2,
                type=AlertType.watchlist_hit,
                kid_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=2),
                dedup_key="closed-1",
                payload_json={},
                closed_at=now,
                close_reason=CloseReason.dismissed,
            )
        )
    r = await c.get(
        "/api/inbox/summary",
        params={
            "since": _iso(now - timedelta(days=1)),
            "until": _iso(now + timedelta(days=1)),
            "include_closed": "true",
        },
    )
    assert r.status_code == 200
    alerts = r.json()["alerts"]
    ids_to_reasons = {a["id"]: a["close_reason"] for a in alerts}
    assert ids_to_reasons == {1: None, 2: "dismissed"}


@pytest.mark.asyncio
async def test_closing_schedule_posted_alert_does_not_reduce_site_activity_count(client):
    """Regression: site-distinct schedule_posted count is analytics, not inbox.

    Closing a schedule_posted alert should NOT change posted_new_count.
    """
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(
            Alert(
                id=1,
                type=AlertType.schedule_posted,
                site_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=1),
                dedup_key="sp-1",
                payload_json={},
                closed_at=now,
                close_reason=CloseReason.acknowledged,
            )
        )
    r = await c.get(
        "/api/inbox/summary",
        params={"since": _iso(now - timedelta(days=1)), "until": _iso(now + timedelta(days=1))},
    )
    assert r.status_code == 200
    body = r.json()
    # The closed schedule_posted alert is NOT in the inbox alert list…
    assert body["alerts"] == []
    # …but the site-distinct analytics count still sees it.
    assert body["site_activity"]["posted_new_count"] == 1
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```bash
uv run pytest tests/integration/test_api_inbox.py::test_inbox_summary_excludes_closed_alerts_by_default tests/integration/test_api_inbox.py::test_inbox_summary_with_include_closed_returns_closed_alerts tests/integration/test_api_inbox.py::test_closing_schedule_posted_alert_does_not_reduce_site_activity_count -q
```

Expected: 3 failures (the filter doesn't exist; or the response shape may differ — that's the red state).

- [ ] **Step 3: Implement the filter and the query parameter**

In `src/yas/web/routes/inbox.py`, modify the `inbox_summary` signature to accept the new param. Add (just after `until`):

```python
include_closed: Annotated[bool, Query()] = False,
```

In the alerts query block (currently at lines 47–54 — verify still there), conditionally add the close-status `where` clause:

```python
alerts_q = (
    select(Alert, Kid.name)
    .outerjoin(Kid, Kid.id == Alert.kid_id)
    .where(Alert.scheduled_for >= since)
    .where(Alert.scheduled_for < until)
    .order_by(Alert.scheduled_for.desc())
    .limit(50)
)
if not include_closed:
    alerts_q = alerts_q.where(Alert.closed_at.is_(None))
```

In the `for alert, kid_name in alert_rows:` loop where `InboxAlertOut(...)` is constructed, add the two new fields to the kwargs:

```python
            inbox_alerts.append(
                InboxAlertOut(
                    id=alert.id,
                    type=alert.type,
                    kid_id=alert.kid_id,
                    kid_name=kid_name,
                    offering_id=alert.offering_id,
                    site_id=alert.site_id,
                    channels=alert.channels,
                    scheduled_for=alert.scheduled_for,
                    sent_at=alert.sent_at,
                    skipped=alert.skipped,
                    dedup_key=alert.dedup_key,
                    payload_json=alert.payload_json or {},
                    summary_text=summary,
                    closed_at=alert.closed_at,
                    close_reason=alert.close_reason,
                )
            )
```

(Match the actual indentation of the existing `InboxAlertOut(...)` call; the snippet above is illustrative. Read the surrounding lines first and merge cleanly.)

Do NOT touch the `posted_new_count` query at line ~131 — leaving it unfiltered is the correct behaviour.

- [ ] **Step 4: Run all 3 new tests to confirm they pass**

```bash
uv run pytest tests/integration/test_api_inbox.py::test_inbox_summary_excludes_closed_alerts_by_default tests/integration/test_api_inbox.py::test_inbox_summary_with_include_closed_returns_closed_alerts tests/integration/test_api_inbox.py::test_closing_schedule_posted_alert_does_not_reduce_site_activity_count -q
```

Expected: 3 passed.

- [ ] **Step 5: Full suite to confirm no regressions**

```bash
uv run pytest -q
```

Expected: 541 passed (528 + 7 + 3 + 3 = 541).

- [ ] **Step 6: Lint/format/type**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

- [ ] **Step 7: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add tests/integration/test_api_inbox.py src/yas/web/routes/inbox.py
git commit -m "feat(api): inbox summary excludes closed alerts by default

Adds ?include_closed=true to opt back in. The schedule_posted
site-distinct analytics count is intentionally left unfiltered —
regression test locks that behaviour in."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 6 — Final exit-gate verification

End state: All exit criteria from the spec §7 verified with actual command output. Branch ready to merge.

- [ ] **Step 1: Fresh-DB migration check**

```bash
rm -f data/activities.db
mkdir -p data
uv run alembic upgrade head
uv run alembic current
```

Expected: `0004_alert_close (head)`.

- [ ] **Step 2: Previous-head migration check (validates the up-migration on a populated DB structure)**

```bash
rm -f data/activities.db
uv run alembic upgrade 0003_pushover_config_json
uv run alembic upgrade head
uv run alembic current
```

Expected: `0004_alert_close (head)` with no errors.

- [ ] **Step 3: All backend gates**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Expected: 541 passed; ruff/format/mypy clean.

- [ ] **Step 4: E2E smoke (still backend-only)**

```bash
bash -n scripts/e2e_phase5a.sh
```

Expected: clean (syntax check only — actually running the e2e against this branch is a manual gate that needs Docker + Anthropic key; not required for the PR but worth running before merge).

- [ ] **Step 5: Push and open PR**

```bash
git push -u origin phase-5b-1a-alert-close
gh pr create --title "phase 5b-1a: alert close (backend)" --body "$(cat <<'EOF'
## Summary
- Adds Alert.closed_at + close_reason columns (nullable, indexed) and CloseReason StrEnum
- POST /api/alerts/{id}/close (idempotent, last-reason-wins) and POST /api/alerts/{id}/reopen
- Inbox summary excludes closed alerts by default; ?include_closed=true opts back in
- schedule_posted analytics count intentionally unfiltered (regression test locks it in)

Backend-only — frontend wiring is Phase 5b-1b.

## Test plan
- [x] uv run pytest -q (541 passed; +13 from 528 baseline)
- [x] uv run ruff check . && uv run ruff format --check . clean
- [x] uv run mypy src clean
- [x] alembic upgrade head clean on fresh DB
- [x] alembic upgrade head clean on DB at previous head (0003_pushover_config_json)
- [ ] CI passes
EOF
)"
```

CI on the PR runs the full backend gate including the migration step we just fixed. Once it's green, merge with `--no-ff`.

---

## Notes for the implementer

- **No new dependencies**. Everything in this slice uses existing imports.
- **No frontend changes**. Phase 5a's TopBar badge already reads `data.alerts.length` from the inbox summary, so it'll automatically reflect closed alerts disappearing.
- **No worker changes**. The note in spec §6 about the worker still firing pending sends after close is intentional — we'll revisit during 5b-1b's review pass once we have UI to inform the decision.
- **Follow existing patterns**. The fixture style in `tests/integration/test_api_alerts_close.py` mirrors `test_api_alerts.py` line 17 onward. The route handler shape mirrors `resend_alert` in `alerts.py:99`.
- **`test_closing_already_closed_with_different_reason_updates_reason` is the subtle case**. The handler must update `close_reason` but NOT touch `closed_at` if it's already set. The implementation uses `if alert.closed_at is None: alert.closed_at = ...` to enforce this — read it carefully.
