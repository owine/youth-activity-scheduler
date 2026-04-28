# Phase 5b-1a — Alert Close (Backend)

**Status:** design approved, ready for implementation plan
**Date:** 2026-04-28
**Depends on:** Phase 5a merged (2026-04-28, commit `f958fca` on `main`)
**Succeeds into:** Phase 5b-1b (frontend mutation wiring including alert close UI)

## 1. Purpose and scope

Phase 5b-1a is a small backend slice that gives alerts a soft-close lifecycle so the inbox can become useful as a daily working surface rather than a passive feed. After this phase, an alert can be marked as either acknowledged ("I saw this and it's handled") or dismissed ("this wasn't useful"), and the inbox summary stops returning closed alerts by default.

This is the prerequisite for Phase 5b-1b's frontend mutation work. The split keeps the backend change — schema, migration, route, summary filter — focused and reviewable on its own, before any UI lands on top of it.

### 1.1 In scope

- Two new nullable columns on the `alerts` table: `closed_at` and `close_reason`.
- A new `CloseReason` string enum with `acknowledged` and `dismissed` initial values.
- Two new action-style endpoints under `/api/alerts/{id}`: `close` and `reopen`.
- Schema additions to `AlertOut` (and therefore to the embedded `InboxAlertOut`) so any consumer can render close state.
- A default-exclude filter on `GET /api/inbox/summary` with an opt-in `?include_closed=true` query parameter.
- Integration tests covering the happy paths, idempotency, error cases, and the inbox summary filter behaviour.

### 1.2 Out of scope — explicitly deferred

These were considered and intentionally excluded.

- **Frontend wiring.** The close/reopen UI, `useCloseAlert` hook, and drawer affordances belong to Phase 5b-1b.
- **Bulk operations.** No "mark all as read" / multi-id close in this slice. Single-alert ops only.
- **Audit trail.** No separate `alert_actions` history table; the timestamps on the row are sufficient for a single-household local app.
- **Closed-status filter on `GET /api/alerts`.** The list endpoint will return closed alerts mixed in. If 5b-1b's UI grows a "closed" tab, add `?closed: bool` then.
- **Additional close reasons.** `'snoozed'`, `'false_positive'`, `'duplicate'` etc. are accommodated by the enum without migration but are not values today.
- **Reopen-with-reason.** Reopen clears both fields; a re-close with a different reason is a second `close` call.
- **Hard delete.** No `DELETE /api/alerts/{id}` endpoint; close is the soft-delete affordance.
- **Worker-side suppression of closed alerts.** Closing an alert does not cancel a pending send; the worker still uses `sent_at` (not `closed_at`) to drive delivery. Captured as a follow-up question for 5b-1b's review pass — see §6.

## 2. Schema

### 2.1 Model changes

`src/yas/db/models/alert.py`:

```python
closed_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True, index=True
)
close_reason: Mapped[CloseReason | None] = mapped_column(String, nullable=True)
```

Both columns are nullable. Existing rows default to "open" (`closed_at IS NULL`). The two columns are always set or cleared together — never one without the other. The route handlers enforce this; no DB-level check constraint, matching the project's existing pattern.

The index on `closed_at` is for the inbox summary's `IS NULL` predicate. SQLite handles `IS NULL` without an index, but the index helps once the alerts table grows (this is the same precedent as `Alert.scheduled_for` and `Alert.dedup_key`, which are both indexed).

### 2.2 Enum

`src/yas/db/models/_types.py`:

```python
class CloseReason(StrEnum):
    acknowledged = "acknowledged"
    dismissed = "dismissed"
```

The `StrEnum` pattern matches the existing `AlertType` and `CrawlStatus` enums in the same file.

### 2.3 Migration

Single Alembic auto-revision adds both columns. No backfill needed (both nullable). The index is included in the revision file so the up-migration is one statement per column plus one create-index.

## 3. Endpoints

Two new routes added to `src/yas/web/routes/alerts.py`. Both follow the existing action-style precedent of `POST /{alert_id}/resend`.

### 3.1 `POST /api/alerts/{alert_id}/close`

```python
class AlertCloseIn(BaseModel):
    reason: CloseReason

@router.post("/{alert_id}/close", response_model=AlertOut)
async def close_alert(alert_id: int, body: AlertCloseIn, request: Request) -> AlertOut: ...
```

Behaviour:

- Looks up the alert by id; returns 404 if not found.
- If the alert is already closed:
  - Same reason → 200, no-op (idempotent).
  - Different reason → 200, `close_reason` updates (last-write-wins). `closed_at` does NOT advance.
- Otherwise sets `closed_at = datetime.now(UTC)` and `close_reason = body.reason`, commits, returns the updated alert.
- 422 if `reason` is missing or not a valid `CloseReason` (Pydantic handles this).

### 3.2 `POST /api/alerts/{alert_id}/reopen`

```python
@router.post("/{alert_id}/reopen", response_model=AlertOut)
async def reopen_alert(alert_id: int, request: Request) -> AlertOut: ...
```

Behaviour:

- 404 if alert not found.
- If already open: 200 no-op (idempotent).
- Otherwise sets both `closed_at = None` and `close_reason = None`, commits, returns the updated alert.
- No request body.

### 3.3 Schema additions

`src/yas/web/routes/alerts_schemas.py`'s `AlertOut` gains:

```python
closed_at: datetime | None = None
close_reason: CloseReason | None = None
```

`close_reason` is typed as the enum (not a `Literal`) so the enum stays the single source of truth for valid values; Pydantic + `from_attributes=True` serialises the enum to its string value automatically.

These flow through to `InboxAlertOut` (which embeds `AlertOut` shape). The frontend can render close-state anywhere it consumes either schema.

### 3.4 What `/api/alerts` (list) does NOT do

The existing `GET /api/alerts` list endpoint is not modified. It returns closed alerts mixed in alongside open ones; consumers that want only open alerts use the inbox summary endpoint (§4), and any future filter on the list endpoint is a 5b-1b concern.

## 4. Inbox summary filter

`src/yas/web/routes/inbox.py`'s `inbox_summary` handler is extended with one query parameter and one extra `WHERE` clause.

### 4.1 Query parameter

```python
include_closed: Annotated[bool, Query()] = False,
```

### 4.2 Filter change

When `include_closed` is `False` (the default), the alerts query at `inbox.py:47–54` adds `.where(Alert.closed_at.is_(None))`. When `include_closed` is `True`, that clause is omitted and closed alerts are returned alongside open ones (with `closed_at` and `close_reason` populated in the response items).

### 4.3 Unaffected: site-activity counts

The `schedule_posted` count at `inbox.py:131` is an analytics signal — "how many distinct sites posted new schedules in this window" — not an inbox-item count. It is NOT filtered by close status. A user closing a `schedule_posted` alert does not retroactively reduce the count of sites that posted that week. A regression test (§5) locks this in.

### 4.4 Topbar badge semantics

The frontend's topbar alert badge (added in 5a, see TopBar.tsx) reads `data.alerts.length` from the summary response. With the default-exclude filter, the badge naturally drops as the user closes alerts. No frontend change is needed in 5b-1a; the badge behaves correctly the moment this slice ships.

## 5. Tests

### 5.1 New file: `tests/integration/test_api_alerts_close.py`

Each test seeds at least one open alert and exercises one path. Test names follow the project's existing convention.

```
close_alert:
  closes_open_alert_with_acknowledged                → 200, fields populated
  closes_open_alert_with_dismissed                   → 200, fields populated
  closing_already_closed_with_same_reason_is_noop    → 200, closed_at unchanged
  closing_already_closed_with_different_reason       → 200, reason updates, closed_at unchanged
  close_returns_404_for_unknown_id                   → 404
  close_returns_422_when_reason_missing              → 422
  close_returns_422_for_invalid_reason               → 422 (e.g. body {"reason": "snoozed"})

reopen_alert:
  reopens_closed_alert_clears_both_fields            → 200, both null
  reopens_already_open_is_noop                       → 200, both still null
  reopen_returns_404_for_unknown_id                  → 404
```

### 5.2 Modify: `tests/integration/test_api_inbox.py`

```
inbox_summary_excludes_closed_alerts_by_default
inbox_summary_with_include_closed_returns_closed_alerts
closing_schedule_posted_alert_does_not_reduce_site_activity_count   ← regression
```

### 5.3 Test count

~13 new test cases. Backend pytest count goes from 528 to ~541.

## 6. Open questions surfaced for the 5b-1b review pass

These are not blocking 5b-1a but should be resolved during 5b-1b design.

- **Should the worker suppress closed pending alerts?** A future-scheduled alert that is closed before its `scheduled_for` time still gets sent today (the worker filters on `sent_at IS NULL`, not `closed_at IS NULL`). Arguably wrong; the fix is one-line in the worker query. Decide during 5b-1b once the close UI exists and the user-facing intent ("does close-now-cancel-pending-send make sense?") is concrete.
- **Should `GET /api/alerts` (list) gain a `?closed: bool` filter?** Only if 5b-1b's UI grows a closed-alerts tab. If it stays inside the inbox-summary path, the list endpoint can be left alone.

## 7. Exit criteria

- Migration applies cleanly on a fresh DB and on a DB at the previous head.
- All existing tests still pass.
- 13 new test cases pass.
- `mypy src` clean.
- `ruff check .` and `ruff format --check .` clean.
- `bash -n scripts/e2e_phase5a.sh` and `npx playwright test --list` still green (no frontend-side regression introduced; this slice does not touch the frontend).

When these land, merge to `main` and proceed to **Phase 5b-1b — Frontend mutation wiring**, written as its own spec.
