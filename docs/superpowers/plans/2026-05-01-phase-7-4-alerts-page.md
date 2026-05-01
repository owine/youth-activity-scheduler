# Phase 7-4 — Alerts Page Implementation Plan (Outbox + Digest Preview)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new top-level `/alerts` route with two tabs (Outbox listing all alerts with filters/pagination/resend; Digest preview rendering the next-scheduled per-kid digest in a sandboxed iframe) — closing master §7 page #8 and finishing Phase 7.

**Architecture:** Backend extends `AlertOut` with `summary_text` (composed via the existing `summarize_alert` helper, which reads names from `Alert.payload_json` — no extra joins beyond Kid). **The `GET /api/digest/preview` endpoint already exists** (commit `44f3b73`) with shape `{subject, body_plain, body_html}` — Phase 7-4 reuses it as-is, no backend creation needed for digest. Frontend route `/alerts` with internal tab routing via untyped URL search params. Reuses existing `<Card>`, `<Badge>`, `<Skeleton>`, `<EmptyState>`, `<ErrorBanner>`. No new dependencies.

**Tech Stack:** React 19, TanStack Query 5, TanStack Router 1.168, MSW, Vitest + RTL. FastAPI + pytest.

**Spec:** `docs/superpowers/specs/2026-05-01-phase-7-4-alerts-page-design.md`

**Project conventions:**
- Frontend deps pinned exact in `frontend/package.json` (no `^`/`~`).
- All commits GPG-signed via 1Password agent. Set `SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"` before each `git commit` in fresh shells. Verify with `git cat-file commit HEAD | grep -q '^gpgsig '`.
- Branch already exists: `phase-7-4-alerts-page`. Spec already committed there. Do NOT commit to `main`.
- **Never use GitHub auto-close keywords** (`Closes #N`, `Fixes #N`) in commit messages — issue #1 is the Renovate dep dashboard. Use `Closes master §N page #M` or plain prose.
- Frontend gates from `frontend/`: `npm run typecheck`, `npm run lint`, `npm run test`. Only assert touched files Prettier-clean (`npx prettier --check <files>`).
- Backend gates: `uv run pytest -q --no-cov`, `uv run ruff check .`, **`uv run ruff format --check .`** (CI checks this), `uv run mypy src`.
- Frontend baseline at start: 251 tests across 39 files. Backend baseline: 593 tests.

**Master §7 page-coverage delta:** Closes page #8 (Alerts: outbox, resend, digest preview). After this lands: 9 of 9 master §7 pages met. **Phase 7 complete.**

---

## File Structure

**Modify — backend:**
- `src/yas/web/routes/alerts_schemas.py` — add `summary_text: str` to `AlertOut`.
- `src/yas/web/routes/alerts.py` — `list_alerts` and `get_alert` left-join `Kid` (for `kid_name`), call `summarize_alert(...)` per row, populate `summary_text`. Reuses the existing helper from `inbox_alert_summary.py` (no Offering/Site join needed — names come from `payload_json`).
- `src/yas/web/app.py` — already registers the digest preview router; no change in this phase.
- `tests/integration/test_api_alerts.py` — extend with one test asserting `summary_text` populates correctly.

**Backend digest preview endpoint already exists** (commit `44f3b73`) with shape `{subject, body_plain, body_html}` and tests in `tests/integration/test_api_digest_preview.py`. Phase 7-4 does NOT create this — it consumes it from the frontend.

**Create — frontend:**
- `frontend/src/routes/alerts.tsx` — thin route shell; reads `?tab=`.
- `frontend/src/components/alerts/OutboxPanel.tsx` + `.test.tsx`
- `frontend/src/components/alerts/OutboxFilterBar.tsx` + `.test.tsx`
- `frontend/src/components/alerts/OutboxRow.tsx` + `.test.tsx`
- `frontend/src/components/alerts/DigestPreviewPanel.tsx` + `.test.tsx`

**Modify — frontend:**
- `frontend/src/lib/types.ts` — add `Alert` (full shape with `summary_text`), `AlertListResponse`, `OutboxFilterState`, `AlertStatus`, `DigestPreviewResponse`.
- `frontend/src/lib/queries.ts` — add `useAlerts(filters, pageSize)` + `useDigestPreview(kidId: number | null)`.
- `frontend/src/lib/mutations.ts` — add `useResendAlert`.
- `frontend/src/lib/mutations.test.tsx` — extend with 2 tests for `useResendAlert`.
- `frontend/src/components/layout/TopBar.tsx` — add "Alerts" link with `lucide-react` icon (e.g. `Mail` or `Send`) between an existing pair (between Offerings and Sites is a clean spot).
- `frontend/src/test/handlers.ts` — defaults for `GET /api/alerts`, `POST /api/alerts/:id/resend`, `GET /api/digest/preview`.
- `frontend/src/routeTree.gen.ts` — regenerated.

**No new dependencies.**

---

## Task 1 — Backend: `AlertOut.summary_text` (TDD)

**Files:**
- Modify: `src/yas/web/routes/alerts_schemas.py`
- Modify: `src/yas/web/routes/alerts.py`
- Modify: `tests/integration/test_api_alerts.py`

End state: `AlertOut.summary_text` populated on list + single-get endpoints by calling the existing `summarize_alert` helper. ~+1 backend test.

### Step 1: Read the existing pattern

```bash
sed -n '40,90p' src/yas/web/routes/inbox.py
```

Note the canonical pattern (line 48-66): `select(Alert, Kid.name).outerjoin(Kid, Kid.id == Alert.kid_id)`, tuple-unpack, then `summarize_alert(at, kid_name=kid_name, payload=alert.payload_json or {})`. The `at: AlertType | str` defensive parsing handles unknown types. **The names (offering_name, site_name) come from `alert.payload_json` — no Offering/Site joins needed.**

### Step 2: Write failing test

Append to `tests/integration/test_api_alerts.py`:

```python
@pytest.mark.asyncio
async def test_alert_list_includes_summary_text(client):
    """AlertOut.summary_text populated via summarize_alert (D2)."""
    c, engine = client  # verify fixture yields tuple; if not, adjust
    # Seed: a watchlist_hit alert for an existing kid, plus a system alert.
    async with session_scope(engine) as s:
        s.add(Alert(
            type=AlertType.watchlist_hit.value,
            kid_id=1,  # existing seeded kid
            channels=["email"],
            scheduled_for=datetime.now(UTC),
            dedup_key="test-watchlist-hit",
            payload_json={"offering_name": "T-Ball", "site_name": "Lil Sluggers"},
        ))
        s.add(Alert(
            type=AlertType.crawl_failed.value,
            channels=["email"],
            scheduled_for=datetime.now(UTC),
            dedup_key="test-crawl-failed",
            payload_json={"site_name": "Lil Sluggers"},
        ))

    r = await c.get("/api/alerts")
    assert r.status_code == 200
    body = r.json()
    items = body["items"]
    assert len(items) >= 2

    # Find the watchlist_hit
    wh = next(i for i in items if i["type"] == "watchlist_hit")
    assert "summary_text" in wh
    assert "Watchlist hit" in wh["summary_text"]
    assert "T-Ball" in wh["summary_text"]

    # System alert (no kid_id) still has a sensible summary
    cf = next(i for i in items if i["type"] == "crawl_failed")
    assert cf["summary_text"]
    assert "Lil Sluggers" in cf["summary_text"]
```

(Adjust imports at top: `from datetime import datetime, UTC`, `from yas.db.models import Alert`, `from yas.db.models._types import AlertType`, `from yas.db.session import session_scope`.)

**Important**: the existing `client` fixture in `test_api_alerts.py` yields just `c` (not a tuple — see line 95: `yield c`). Two ways to make the new test work:

1. **Refactor the fixture to yield `(c, engine)`** and update all existing tests in this file to unpack — this is the canonical pattern from `test_api_household.py` / `test_api_matches.py`. Recommended; consistency win.
2. **Use a separate engine reference**: store `engine` in the fixture's outer scope and reference it directly. Less clean.

Pick option 1. After updating the fixture, every existing test in this file that takes `client` as a param will need `c, _ = client` or `c, engine = client` instead of just `client`. Find them and update.

### Step 3: Run test — verify fail

```bash
uv run pytest tests/integration/test_api_alerts.py -q 2>&1 | tail -10
```

Expected: 1 failure with `KeyError: 'summary_text'` or pydantic field-missing error.

### Step 4: Add `summary_text` to `AlertOut`

Edit `src/yas/web/routes/alerts_schemas.py`. Append to the `AlertOut` class:

```python
class AlertOut(BaseModel):
    """Alert detail for GET responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    kid_id: int | None
    offering_id: int | None
    site_id: int | None
    channels: list[str]
    scheduled_for: datetime
    sent_at: datetime | None
    skipped: bool
    dedup_key: str
    payload_json: dict[str, Any]
    closed_at: datetime | None = None
    close_reason: CloseReason | None = None
    summary_text: str = ""  # populated by handlers via summarize_alert
```

(Default = empty string so the `from_attributes=True` initialization doesn't fail when constructing from an ORM `Alert` row — handlers explicitly set the real value.)

### Step 5: Update `alerts.py` `list_alerts` + `get_alert`

```python
# Top imports
from yas.db.models import Alert, Kid
from yas.web.routes.inbox_alert_summary import summarize_alert

# In list_alerts: change main query to outer-join Kid for kid_name.
# Replace the existing `q = select(Alert)` and the rows fetch with:
q = (
    select(Alert, Kid.name)
    .outerjoin(Kid, Kid.id == Alert.kid_id)
)
# (Apply all existing filters to q identically — they reference Alert columns
#  which the join doesn't change.)
# After applying filters, count_q stays as-is (it doesn't need kid_name).
# Order/pagination unchanged.
q = q.order_by(Alert.id.desc()).limit(limit).offset(offset)
rows = (await s.execute(q)).all()

items: list[AlertOut] = []
for alert, kid_name in rows:
    try:
        at: AlertType | str = AlertType(alert.type)
    except ValueError:
        at = alert.type
    summary = summarize_alert(
        at,
        kid_name=kid_name,
        payload=alert.payload_json or {},
    )
    items.append(AlertOut(
        id=alert.id, type=alert.type, kid_id=alert.kid_id,
        offering_id=alert.offering_id, site_id=alert.site_id,
        channels=list(alert.channels or []),
        scheduled_for=alert.scheduled_for, sent_at=alert.sent_at,
        skipped=alert.skipped, dedup_key=alert.dedup_key,
        payload_json=alert.payload_json or {},
        closed_at=alert.closed_at, close_reason=alert.close_reason,
        summary_text=summary,
    ))
return AlertListResponse(items=items, total=total or 0, limit=limit, offset=offset)
```

For `get_alert` (singleton), use the same join pattern:

```python
@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert(request: Request, alert_id: int) -> AlertOut:
    async with session_scope(_engine(request)) as s:
        row = (await s.execute(
            select(Alert, Kid.name)
            .outerjoin(Kid, Kid.id == Alert.kid_id)
            .where(Alert.id == alert_id)
        )).first()
        if row is None:
            raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
        alert, kid_name = row
        try:
            at: AlertType | str = AlertType(alert.type)
        except ValueError:
            at = alert.type
        summary = summarize_alert(at, kid_name=kid_name, payload=alert.payload_json or {})
        return AlertOut(
            id=alert.id, type=alert.type, kid_id=alert.kid_id,
            offering_id=alert.offering_id, site_id=alert.site_id,
            channels=list(alert.channels or []),
            scheduled_for=alert.scheduled_for, sent_at=alert.sent_at,
            skipped=alert.skipped, dedup_key=alert.dedup_key,
            payload_json=alert.payload_json or {},
            closed_at=alert.closed_at, close_reason=alert.close_reason,
            summary_text=summary,
        )
```

The other endpoints (`/resend`, `/close`, `/reopen`) currently use `AlertOut.model_validate(alert)`. They should also be updated to populate `summary_text` — easiest is to factor a small helper:

```python
async def _to_out(s: AsyncSession, alert: Alert) -> AlertOut:
    kid_name = None
    if alert.kid_id is not None:
        kid_name = (await s.execute(
            select(Kid.name).where(Kid.id == alert.kid_id)
        )).scalar_one_or_none()
    try:
        at: AlertType | str = AlertType(alert.type)
    except ValueError:
        at = alert.type
    summary = summarize_alert(at, kid_name=kid_name, payload=alert.payload_json or {})
    return AlertOut(
        id=alert.id, type=alert.type, kid_id=alert.kid_id,
        offering_id=alert.offering_id, site_id=alert.site_id,
        channels=list(alert.channels or []),
        scheduled_for=alert.scheduled_for, sent_at=alert.sent_at,
        skipped=alert.skipped, dedup_key=alert.dedup_key,
        payload_json=alert.payload_json or {},
        closed_at=alert.closed_at, close_reason=alert.close_reason,
        summary_text=summary,
    )
```

Use `_to_out` in resend/close/reopen handlers.

### Step 6: Run tests — verify pass

```bash
uv run pytest tests/integration/test_api_alerts.py -q 2>&1 | tail -10
uv run pytest -q --no-cov 2>&1 | tail -5
```

Expected: ~594 backend (existing 593 + 1 new).

### Step 7: Backend gates

```bash
uv run ruff check src tests 2>&1 | tail -3
uv run ruff format --check src tests 2>&1 | tail -3
uv run mypy src 2>&1 | tail -3
```

Run `uv run ruff format <files>` if any touched files fail format-check.

### Step 8: Commit

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add src/yas/web/routes/alerts_schemas.py src/yas/web/routes/alerts.py tests/integration/test_api_alerts.py
git commit -m "feat(backend): AlertOut.summary_text via summarize_alert helper

Phase 7-4 outbox needs a human-readable summary per row. Mirror the
existing InboxAlert pattern: outer-join Kid for kid_name, call
summarize_alert (already importable from inbox_alert_summary —
handles all 11 AlertType branches). Names like offering_name/
site_name come from Alert.payload_json so no Offering/Site joins
needed.

Helper _to_out factored so resend/close/reopen handlers populate
summary_text consistently."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 2 — Verify backend digest preview endpoint (no-op)

**No code changes** — the endpoint already exists. This task documents the verification step so the subagent skipping it knows it was intentional.

- [ ] **Step 1: Verify endpoint exists**

```bash
ls src/yas/web/routes/digest_preview.py src/yas/web/routes/digest_preview_schemas.py
grep -n "include_router(digest_preview" src/yas/web/app.py
```

Expected: both files exist; `digest_preview.router` registered in `app.py`.

- [ ] **Step 2: Verify response shape**

```bash
grep -n "subject\|body_plain\|body_html" src/yas/web/routes/digest_preview_schemas.py
```

Expected: `DigestPreviewOut` has fields `subject: str`, `body_plain: str`, `body_html: str`. The frontend type in Task 3 must match exactly.

- [ ] **Step 3: Verify existing tests pass**

```bash
uv run pytest tests/integration/test_api_digest_preview.py -q 2>&1 | tail -5
```

Expected: all existing digest preview tests pass. No new tests needed in this phase.

---

## Task 3 — Frontend types + 3 hooks (TDD)

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/queries.ts`
- Modify: `frontend/src/lib/mutations.ts`
- Modify: `frontend/src/lib/mutations.test.tsx`
- Modify: `frontend/src/test/handlers.ts`

End state: 3 new hooks (`useAlerts`, `useDigestPreview`, `useResendAlert`) + supporting types. ~+2 frontend tests for `useResendAlert`.

### Step 1: Add types

Edit `frontend/src/lib/types.ts`. Append:

```ts
// Phase 7-4 alerts page
export type AlertStatus = 'pending' | 'sent' | 'skipped';

export interface Alert {
  id: number;
  type: AlertType | string;
  kid_id: number | null;
  offering_id: number | null;
  site_id: number | null;
  channels: string[];
  scheduled_for: string;
  sent_at: string | null;
  skipped: boolean;
  dedup_key: string;
  payload_json: Record<string, unknown>;
  closed_at: string | null;
  close_reason: CloseReason | null;
  summary_text: string;
}

export interface AlertListResponse {
  items: Alert[];
  total: number;
  limit: number;
  offset: number;
}

export interface OutboxFilterState {
  kidId: number | null;
  type: string | null;
  status: AlertStatus | null;
  since: string | null;        // YYYY-MM-DD
  until: string | null;
  page: number;                // 0-indexed
}

export interface DigestPreviewResponse {
  subject: string;
  body_plain: string;
  body_html: string;
}
```

(Verify `CloseReason` is already exported in this file — it is, from Phase 5b-1a.)

### Step 2: Add MSW handlers

Edit `frontend/src/test/handlers.ts`. Append:

```ts
// GET /api/alerts — default empty list
http.get('/api/alerts', () =>
  HttpResponse.json({ items: [], total: 0, limit: 25, offset: 0 }),
),

// POST /api/alerts/:id/resend — clones the alert
http.post('/api/alerts/:id/resend', ({ params }) =>
  HttpResponse.json(
    {
      id: 999,
      type: 'new_match',
      kid_id: 1,
      offering_id: null,
      site_id: null,
      channels: ['email'],
      scheduled_for: '2026-05-01T00:00:00Z',
      sent_at: null,
      skipped: false,
      dedup_key: `clone:${params.id}`,
      payload_json: {},
      closed_at: null,
      close_reason: null,
      summary_text: 'Resent alert',
    },
    { status: 202 },
  ),
),

// GET /api/digest/preview — default minimal render
http.get('/api/digest/preview', () =>
  HttpResponse.json({
    html: '<p>Preview body</p>',
    plain: 'Preview body',
    top_line: 'Today\'s preview',
  }),
),
```

### Step 3: Add `useAlerts` and `useDigestPreview`

Append to `frontend/src/lib/queries.ts`:

```ts
import type { AlertListResponse, DigestPreviewResponse, OutboxFilterState } from './types';

function _serializeOutboxFilters(f: OutboxFilterState, pageSize: number): string {
  const params = new URLSearchParams();
  if (f.kidId != null) params.set('kid_id', String(f.kidId));
  if (f.type) params.set('type', f.type);
  if (f.status) params.set('status', f.status);
  if (f.since) params.set('since', f.since);
  if (f.until) params.set('until', f.until);
  params.set('limit', String(pageSize));
  params.set('offset', String(f.page * pageSize));
  return params.toString();
}

export function useAlerts(filters: OutboxFilterState, pageSize = 25) {
  return useQuery({
    queryKey: ['alerts', 'list', filters, pageSize],
    queryFn: () =>
      api.get<AlertListResponse>(`/api/alerts?${_serializeOutboxFilters(filters, pageSize)}`),
  });
}

export function useDigestPreview(kidId: number | null) {
  return useQuery({
    queryKey: ['digest', 'preview', kidId],
    queryFn: () => api.get<DigestPreviewResponse>(`/api/digest/preview?kid_id=${kidId}`),
    enabled: kidId != null && Number.isFinite(kidId) && kidId > 0,
  });
}
```

### Step 4: Write failing tests for `useResendAlert`

Append to `frontend/src/lib/mutations.test.tsx`:

```tsx
describe('useResendAlert', () => {
  it('POSTs to /api/alerts/:id/resend and invalidates alerts cache', async () => {
    let called = false;
    server.use(
      http.post('/api/alerts/:id/resend', () => {
        called = true;
        return HttpResponse.json(
          {
            id: 999, type: 'new_match', kid_id: 1, offering_id: null, site_id: null,
            channels: ['email'], scheduled_for: '2026-05-01T00:00:00Z',
            sent_at: null, skipped: false, dedup_key: 'clone:7',
            payload_json: {}, closed_at: null, close_reason: null,
            summary_text: 'Resent',
          },
          { status: 202 },
        );
      }),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useResendAlert(), { wrapper: makeWrapper(qc) });
    await result.current.mutateAsync({ alertId: 7 });
    expect(called).toBe(true);
    // After settled, alerts cache should be invalidated
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['alerts'] });
  });

  it('rejects on 500', async () => {
    server.use(
      http.post('/api/alerts/:id/resend', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const { result } = renderHook(() => useResendAlert(), { wrapper: makeWrapper(qc) });
    await expect(result.current.mutateAsync({ alertId: 7 })).rejects.toThrow();
  });
});
```

### Step 5: Run tests — verify fail

```bash
cd frontend && npm run test -- mutations.test 2>&1 | tail -10
```

Expected: 2 failures with "useResendAlert is not defined".

### Step 6: Implement `useResendAlert`

Append to `frontend/src/lib/mutations.ts`:

```ts
import type { Alert } from './types';

interface ResendAlertInput {
  alertId: number;
}

export function useResendAlert() {
  const qc = useQueryClient();
  return useMutation<Alert, Error, ResendAlertInput>({
    mutationFn: ({ alertId }) => api.post<Alert>(`/api/alerts/${alertId}/resend`, {}),
    onSettled: async () => {
      await qc.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
}
```

### Step 7: Run tests — verify pass + Frontend gates

```bash
cd frontend && npm run typecheck && npm run lint && npm run test 2>&1 | tail -10
npx prettier --check src/lib/types.ts src/lib/queries.ts src/lib/mutations.ts src/lib/mutations.test.tsx src/test/handlers.ts
```

Expected: clean. Test count: 251 → 253 (+2).

### Step 8: Commit

```bash
git add frontend/src/lib/types.ts frontend/src/lib/queries.ts frontend/src/lib/mutations.ts frontend/src/lib/mutations.test.tsx frontend/src/test/handlers.ts
git commit -m "feat(frontend): types + 3 hooks for Phase 7-4 alerts page

- Alert (full shape with summary_text), AlertListResponse,
  OutboxFilterState, AlertStatus, DigestPreviewResponse types.
- useAlerts(filters, pageSize): wraps GET /api/alerts with
  serialized search-param query. Cache key includes filters object
  so different views maintain independent caches.
- useDigestPreview(kidId: number | null): null-safe gate via
  kidId != null && Number.isFinite(kidId) && kidId > 0. Returns
  {html, plain, top_line}.
- useResendAlert: non-optimistic POST /api/alerts/:id/resend;
  invalidates ['alerts'] on settle so the outbox refetches.

MSW default handlers added for the three new wire shapes."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 4 — `<OutboxFilterBar>` component (TDD)

**Files:**
- Create: `frontend/src/components/alerts/OutboxFilterBar.tsx`
- Create: `frontend/src/components/alerts/OutboxFilterBar.test.tsx`

End state: Controlled filter bar with kid select + type select + status radio + since/until date inputs + Clear button. ~4 tests.

### Step 1: Write failing tests

```tsx
// OutboxFilterBar.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OutboxFilterBar } from './OutboxFilterBar';
import type { OutboxFilterState, KidBrief } from '@/lib/types';

const baseFilters: OutboxFilterState = {
  kidId: null, type: null, status: null,
  since: null, until: null, page: 0,
};
const kids: KidBrief[] = [
  { id: 1, name: 'Sam', dob: '2019-01-01', interests: [], active: true },
  { id: 2, name: 'Alex', dob: '2020-01-01', interests: [], active: true },
];

describe('OutboxFilterBar', () => {
  it('renders kid select + type select + status radio + since/until inputs + Clear', () => {
    render(<OutboxFilterBar value={baseFilters} onChange={vi.fn()} kids={kids} />);
    expect(screen.getByLabelText(/kid/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/type/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/since/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/until/i)).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /any/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /clear/i })).toBeInTheDocument();
  });

  it('toggling status radio fires onChange with new status + page reset to 0', async () => {
    const onChange = vi.fn();
    render(<OutboxFilterBar value={{ ...baseFilters, page: 5 }} onChange={onChange} kids={kids} />);
    await userEvent.click(screen.getByRole('radio', { name: /sent/i }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ status: 'sent', page: 0 }));
  });

  it('setting since date fires onChange with the date string', async () => {
    const onChange = vi.fn();
    render(<OutboxFilterBar value={baseFilters} onChange={onChange} kids={kids} />);
    const since = screen.getByLabelText(/since/i);
    await userEvent.type(since, '2026-04-01');
    expect(onChange).toHaveBeenCalled();
    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(lastCall.since).toBe('2026-04-01');
  });

  it('Clear button resets all filters to defaults', async () => {
    const onChange = vi.fn();
    const dirty: OutboxFilterState = {
      kidId: 1, type: 'new_match', status: 'sent',
      since: '2026-04-01', until: '2026-05-01', page: 3,
    };
    render(<OutboxFilterBar value={dirty} onChange={onChange} kids={kids} />);
    await userEvent.click(screen.getByRole('button', { name: /clear/i }));
    expect(onChange).toHaveBeenCalledWith({
      kidId: null, type: null, status: null,
      since: null, until: null, page: 0,
    });
  });
});
```

### Step 2: Run tests — verify fail

### Step 3: Implement

```tsx
// OutboxFilterBar.tsx
import { Button } from '@/components/ui/button';
import type { AlertStatus, KidBrief, OutboxFilterState } from '@/lib/types';

const ALERT_TYPES = [
  'watchlist_hit', 'new_match', 'reg_opens_24h', 'reg_opens_1h', 'reg_opens_now',
  'schedule_posted', 'crawl_failed', 'digest', 'site_stagnant',
  'no_matches_for_kid', 'push_cap',
] as const;
const STATUS_OPTIONS: (AlertStatus | null)[] = [null, 'pending', 'sent', 'skipped'];

interface Props {
  value: OutboxFilterState;
  onChange: (next: OutboxFilterState) => void;
  kids: KidBrief[];
}

export function OutboxFilterBar({ value, onChange, kids }: Props) {
  const update = (patch: Partial<OutboxFilterState>) =>
    onChange({ ...value, ...patch, page: 0 });

  const handleClear = () =>
    onChange({
      kidId: null, type: null, status: null,
      since: null, until: null, page: 0,
    });

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-md border border-border bg-card p-3">
      <div>
        <label htmlFor="filter-kid" className="block text-xs font-medium uppercase text-muted-foreground">Kid</label>
        <select
          id="filter-kid"
          value={value.kidId ?? ''}
          onChange={(e) => update({ kidId: e.target.value ? Number(e.target.value) : null })}
          className="rounded border border-border bg-background px-2 py-1 text-sm"
        >
          <option value="">Any</option>
          {kids.map((k) => (
            <option key={k.id} value={k.id}>{k.name}</option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="filter-type" className="block text-xs font-medium uppercase text-muted-foreground">Type</label>
        <select
          id="filter-type"
          value={value.type ?? ''}
          onChange={(e) => update({ type: e.target.value || null })}
          className="rounded border border-border bg-background px-2 py-1 text-sm"
        >
          <option value="">Any</option>
          {ALERT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>
      <fieldset>
        <legend className="block text-xs font-medium uppercase text-muted-foreground">Status</legend>
        <div className="flex gap-2 text-sm">
          {STATUS_OPTIONS.map((s) => (
            <label key={s ?? 'any'} className="flex items-center gap-1">
              <input
                type="radio"
                name="status"
                checked={value.status === s}
                onChange={() => update({ status: s })}
              />
              {s ?? 'any'}
            </label>
          ))}
        </div>
      </fieldset>
      <div>
        <label htmlFor="filter-since" className="block text-xs font-medium uppercase text-muted-foreground">Since</label>
        <input
          id="filter-since"
          type="date"
          value={value.since ?? ''}
          onChange={(e) => update({ since: e.target.value || null })}
          className="rounded border border-border bg-background px-2 py-1 text-sm"
        />
      </div>
      <div>
        <label htmlFor="filter-until" className="block text-xs font-medium uppercase text-muted-foreground">Until</label>
        <input
          id="filter-until"
          type="date"
          value={value.until ?? ''}
          onChange={(e) => update({ until: e.target.value || null })}
          className="rounded border border-border bg-background px-2 py-1 text-sm"
        />
      </div>
      <Button type="button" variant="outline" onClick={handleClear}>Clear</Button>
    </div>
  );
}
```

### Step 4: Run tests — verify pass + Prettier

### Step 5: Commit

```bash
git add frontend/src/components/alerts/OutboxFilterBar.tsx frontend/src/components/alerts/OutboxFilterBar.test.tsx
git commit -m "feat(frontend): OutboxFilterBar component"
```

---

## Task 5 — `<OutboxRow>` component (TDD)

**Files:**
- Create: `frontend/src/components/alerts/OutboxRow.tsx`
- Create: `frontend/src/components/alerts/OutboxRow.test.tsx`

End state: One row per alert with badge + summary + scheduled-for + status indicator + channels + Resend button (with success/failure pill). ~4 tests.

### Step 1: Write failing tests

Tests cover (per spec):
1. Renders type badge + summary_text + scheduled-for date.
2. Status indicator: shows "pending" / "sent <relDate>" / "skipped" / "closed (<reason>)" per fixture status.
3. Resend button click → fires `useResendAlert` (capture POST URL via `server.use`).
4. Channels list rendered correctly (e.g. "email, ntfy" or chips).

Use the canonical render-with-QueryClient pattern from `frontend/src/components/enrollments/EnrollmentRow.test.tsx`.

### Step 2: Run tests — verify fail.

### Step 3: Implement

```tsx
// OutboxRow.tsx
import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { useResendAlert } from '@/lib/mutations';
import { relDate } from '@/lib/format';
import type { Alert } from '@/lib/types';

interface Props {
  alert: Alert;
}

export function OutboxRow({ alert }: Props) {
  const resend = useResendAlert();
  const [pillState, setPillState] = useState<'idle' | 'ok' | 'err'>('idle');
  const [pillDetail, setPillDetail] = useState<string>('');

  const handleResend = async () => {
    setPillState('idle');
    try {
      await resend.mutateAsync({ alertId: alert.id });
      setPillState('ok');
      setPillDetail('Resend queued');
    } catch (err) {
      setPillState('err');
      setPillDetail(`Failed: ${(err as Error).message}`);
    }
    // Auto-clear after 3s
    setTimeout(() => setPillState('idle'), 3000);
  };

  let statusText: string;
  if (alert.closed_at) statusText = `closed (${alert.close_reason ?? 'unknown'})`;
  else if (alert.skipped) statusText = 'skipped';
  else if (alert.sent_at) statusText = `sent ${relDate(alert.sent_at)}`;
  else statusText = 'pending';

  return (
    <Card className="p-3 space-y-1">
      <div className="flex items-center gap-2">
        <Badge variant="secondary">{alert.type}</Badge>
        <div className="flex-1 text-sm">{alert.summary_text}</div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleResend}
          disabled={resend.isPending}
        >
          {resend.isPending ? 'Resending…' : 'Resend'}
        </Button>
        {pillState === 'ok' && (
          <span className="rounded bg-green-100 px-2 py-1 text-xs text-green-800 dark:bg-green-900/30 dark:text-green-300">
            {pillDetail}
          </span>
        )}
        {pillState === 'err' && (
          <span className="rounded bg-destructive/10 px-2 py-1 text-xs text-destructive">
            {pillDetail}
          </span>
        )}
      </div>
      <div className="text-xs text-muted-foreground">
        {relDate(alert.scheduled_for)} · {statusText} · {alert.channels.join(', ') || '—'}
      </div>
    </Card>
  );
}
```

### Step 4: Run tests — verify pass + Prettier

### Step 5: Commit

```bash
git add frontend/src/components/alerts/OutboxRow.tsx frontend/src/components/alerts/OutboxRow.test.tsx
git commit -m "feat(frontend): OutboxRow component"
```

---

## Task 6 — `<OutboxPanel>` component (TDD)

**Files:**
- Create: `frontend/src/components/alerts/OutboxPanel.tsx`
- Create: `frontend/src/components/alerts/OutboxPanel.test.tsx`

End state: Composes FilterBar + paginated row list + pagination buttons + empty/loading/error states. URL search-param state. ~4 tests.

### Step 1: Write failing tests

Tests:
1. Renders FilterBar + list of OutboxRow components from seeded `useAlerts` cache.
2. Empty filtered: "No alerts match your filters" + Clear filters button.
3. Pagination: Next disabled when `offset + items.length >= total`; Prev disabled at offset 0.
4. Filter state persists in URL search params; mount with `?status=sent` reads through.

Cache seeding pattern: `qc.setQueryData(['alerts', 'list', filters, 25], { items: [...], total, limit: 25, offset: 0 })`.

URL search params via `vi.mock` on `@tanstack/react-router` to mock `useSearch` / `useNavigate` (mirror the `EnrollmentRow.test.tsx` pattern from Phase 7-3 for mocking router context).

### Step 2: Run tests — verify fail.

### Step 3: Implement

Component contract:
```ts
interface Props {
  // No props — reads filter state from URL search params via TanStack Router hooks.
}
```

Reads `Route.useSearch()` from the parent route (`alerts.tsx`). Parses untyped search params into `OutboxFilterState`:

```tsx
function parseSearchToFilters(s: Record<string, string | undefined>): OutboxFilterState {
  return {
    kidId: s.kid ? Number(s.kid) : null,
    type: s.type ?? null,
    status: (s.status as AlertStatus | undefined) ?? null,
    since: s.since ?? null,
    until: s.until ?? null,
    page: s.page ? Number(s.page) : 0,
  };
}
function filtersToSearch(f: OutboxFilterState): Record<string, string> {
  const out: Record<string, string> = { tab: 'outbox' };
  if (f.kidId != null) out.kid = String(f.kidId);
  if (f.type) out.type = f.type;
  if (f.status) out.status = f.status;
  if (f.since) out.since = f.since;
  if (f.until) out.until = f.until;
  if (f.page > 0) out.page = String(f.page);
  return out;
}
```

Inside the component:
```tsx
const search = Route.useSearch() as Record<string, string | undefined>;
const navigate = useNavigate();
const filters = parseSearchToFilters(search);
const kids = useKids();
const { data, isLoading, isError, refetch } = useAlerts(filters);

const updateFilters = (next: OutboxFilterState) => {
  navigate({ to: '/alerts', search: filtersToSearch(next) });
};

if (isLoading) return <Skeleton className="h-32 w-full" />;
if (isError || !data) return <ErrorBanner message="Failed to load alerts" onRetry={() => refetch()} />;

const { items, total, limit, offset } = data;
const start = offset + 1;
const end = offset + items.length;
const hasNext = end < total;
const hasPrev = offset > 0;

return (
  <div className="space-y-4">
    <OutboxFilterBar value={filters} onChange={updateFilters} kids={kids.data ?? []} />
    {items.length === 0 ? (
      <EmptyState>
        No alerts match your filters.{' '}
        <button type="button" className="underline"
          onClick={() => updateFilters({
            kidId: null, type: null, status: null, since: null, until: null, page: 0,
          })}
        >Clear filters</button>
      </EmptyState>
    ) : (
      <ul className="space-y-2">
        {items.map((a) => (
          <li key={a.id}><OutboxRow alert={a} /></li>
        ))}
      </ul>
    )}
    {total > 0 && (
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">
          Showing {start}–{end} of {total}
        </span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm"
            disabled={!hasPrev}
            onClick={() => updateFilters({ ...filters, page: filters.page - 1 })}
          >Prev</Button>
          <Button variant="outline" size="sm"
            disabled={!hasNext}
            onClick={() => updateFilters({ ...filters, page: filters.page + 1 })}
          >Next</Button>
        </div>
      </div>
    )}
  </div>
);
```

(Verify the route file exports a `Route` constant that has `.useSearch()` — see how Task 8's route shell exports it.)

### Step 4: Run tests — verify pass + Prettier.

### Step 5: Commit

```bash
git add frontend/src/components/alerts/OutboxPanel.tsx frontend/src/components/alerts/OutboxPanel.test.tsx
git commit -m "feat(frontend): OutboxPanel component"
```

---

## Task 7 — `<DigestPreviewPanel>` component (TDD)

**Files:**
- Create: `frontend/src/components/alerts/DigestPreviewPanel.tsx`
- Create: `frontend/src/components/alerts/DigestPreviewPanel.test.tsx`

End state: Kid picker + top-line text + iframe srcDoc render. ~5 tests.

### Step 1: Write failing tests

Tests:
1. Kid picker renders all kids from `useKids()`; default = first kid.
2. Pre-populated render: when `useDigestPreview` resolves, iframe `srcDoc` is set to response html.
3. Top-line text rendered above iframe (`getByText` for the top_line content).
4. Switching kid via picker fires the preview query for the new kid_id (capture URL via `server.use`).
5. Empty state when no kids: "Add a kid first" with link to `/kids/new`.

### Step 2: Run tests — verify fail.

### Step 3: Implement

```tsx
// DigestPreviewPanel.tsx
import { Link } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { EmptyState } from '@/components/common/EmptyState';
import { useDigestPreview, useKids } from '@/lib/queries';
import { Route } from '@/routes/alerts';
import { useNavigate } from '@tanstack/react-router';

export function DigestPreviewPanel() {
  const search = Route.useSearch() as Record<string, string | undefined>;
  const navigate = useNavigate();
  const kids = useKids();

  const selectedKidId = search.kid_digest
    ? Number(search.kid_digest)
    : (kids.data?.[0]?.id ?? null);

  const preview = useDigestPreview(selectedKidId);

  if (kids.isLoading) return <Skeleton className="h-64 w-full" />;
  if (kids.isError) return <ErrorBanner message="Failed to load kids" onRetry={() => kids.refetch()} />;

  if (!kids.data || kids.data.length === 0) {
    return (
      <EmptyState>
        Add a kid first to preview a digest.{' '}
        <Link to="/kids/new" className="underline">Add kid</Link>.
      </EmptyState>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="digest-kid" className="block text-xs font-medium uppercase text-muted-foreground">Kid</label>
        <select
          id="digest-kid"
          value={selectedKidId ?? ''}
          onChange={(e) =>
            navigate({
              to: '/alerts',
              search: (prev: Record<string, string | undefined>) => ({
                ...prev,
                tab: 'digest',
                kid_digest: e.target.value,
              }),
            })
          }
          className="rounded border border-border bg-background px-2 py-1 text-sm"
        >
          {kids.data.map((k) => (
            <option key={k.id} value={k.id}>{k.name}</option>
          ))}
        </select>
      </div>
      {preview.isLoading && <Skeleton className="h-[600px] w-full" />}
      {preview.isError && (
        <ErrorBanner message="Failed to load digest preview" onRetry={() => preview.refetch()} />
      )}
      {preview.data && (
        <>
          <div className="rounded bg-muted p-3 text-sm">
            <span className="font-medium">Subject:</span> {preview.data.subject}
          </div>
          <iframe
            srcDoc={preview.data.body_html}
            sandbox="allow-same-origin"
            className="w-full h-[600px] rounded border border-border"
            title="Digest preview"
          />
          <p className="text-xs italic text-muted-foreground">
            This is a preview of the next scheduled digest based on the last 24 hours of activity.
          </p>
        </>
      )}
    </div>
  );
}
```

### Step 4: Run tests — verify pass + Prettier.

### Step 5: Commit

```bash
git add frontend/src/components/alerts/DigestPreviewPanel.tsx frontend/src/components/alerts/DigestPreviewPanel.test.tsx
git commit -m "feat(frontend): DigestPreviewPanel component"
```

---

## Task 8 — `/alerts` route shell + tab routing + TopBar nav

**Files:**
- Create: `frontend/src/routes/alerts.tsx`
- Modify: `frontend/src/components/layout/TopBar.tsx`
- Create: `frontend/src/routes/alerts.test.tsx`
- Modify: `frontend/src/routeTree.gen.ts` (regenerated)

End state: `/alerts` route renders the right panel based on `?tab=` search param. TopBar gets a new "Alerts" link. ~2 tests for the tab-routing logic.

### Step 1: Write failing tests

Tests:
1. Default tab is "outbox" when no `?tab=` param.
2. URL `?tab=digest` activates DigestPreviewPanel.

### Step 2: Run tests — verify fail.

### Step 3: Implement route

```tsx
// frontend/src/routes/alerts.tsx
import { createFileRoute, Link } from '@tanstack/react-router';
import { OutboxPanel } from '@/components/alerts/OutboxPanel';
import { DigestPreviewPanel } from '@/components/alerts/DigestPreviewPanel';
import { cn } from '@/lib/utils';

export const Route = createFileRoute('/alerts')({
  component: AlertsPage,
  // Untyped search params — D3 of spec.
  validateSearch: (s: Record<string, unknown>) =>
    Object.fromEntries(
      Object.entries(s).filter(([, v]) => typeof v === 'string'),
    ) as Record<string, string>,
});

function AlertsPage() {
  const search = Route.useSearch();
  const tab = search.tab === 'digest' ? 'digest' : 'outbox';

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Alerts</h1>
      <nav className="border-b border-border flex gap-2 mb-4">
        <Link
          to="/alerts"
          search={{ tab: 'outbox' }}
          className={cn(
            'px-3 py-2 text-sm border-b-2 -mb-px',
            tab === 'outbox'
              ? 'border-primary text-foreground'
              : 'border-transparent text-muted-foreground hover:text-foreground',
          )}
        >Outbox</Link>
        <Link
          to="/alerts"
          search={{ tab: 'digest' }}
          className={cn(
            'px-3 py-2 text-sm border-b-2 -mb-px',
            tab === 'digest'
              ? 'border-primary text-foreground'
              : 'border-transparent text-muted-foreground hover:text-foreground',
          )}
        >Digest preview</Link>
      </nav>
      {tab === 'outbox' ? <OutboxPanel /> : <DigestPreviewPanel />}
    </div>
  );
}
```

### Step 4: Add TopBar nav link

Read `frontend/src/components/layout/TopBar.tsx` and add a new `<Link>` between Offerings and Sites with an icon:

```tsx
import { Bell, LayoutGrid, Mail, Globe, Settings } from 'lucide-react';
// ...
<Link to="/alerts" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
  <Mail className="h-4 w-4" /> Alerts
</Link>
```

(`Mail` icon is a sensible choice; `Send` or `Bell` work too. Pick one consistent with the existing aesthetic.)

### Step 5: Regenerate routeTree

```bash
cd frontend && npm run build 2>&1 | tail -5
```

Expected: build succeeds; routeTree.gen.ts has new `/alerts` route.

### Step 6: Run gates

```bash
cd frontend && npm run typecheck && npm run lint && npm run test 2>&1 | tail -10
npx prettier --check 'src/routes/alerts.tsx' 'src/routes/alerts.test.tsx' src/components/layout/TopBar.tsx
```

Expected: ~273 passing.

### Step 7: Commit

```bash
git add 'frontend/src/routes/alerts.tsx' 'frontend/src/routes/alerts.test.tsx' frontend/src/components/layout/TopBar.tsx frontend/src/routeTree.gen.ts
git commit -m "feat(frontend): /alerts route + tab routing + TopBar nav

AlertsPage renders OutboxPanel or DigestPreviewPanel based on
?tab= URL search param (default: outbox). validateSearch is the
TanStack Router pattern; we use untyped string passthrough per
D3 — no Zod schema, just a string filter.

TopBar gains an 'Alerts' link with Mail icon between Offerings
and Sites. routeTree.gen.ts regenerated by build."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 9 — Final exit gates + manual smoke + roadmap + push + PR

End state: branch shipped.

### Step 1: Final gates

```bash
cd /Users/owine/Git/youth-activity-scheduler
uv run pytest -q --no-cov 2>&1 | tail -5
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
cd frontend && npm run typecheck && npm run lint && npm run test 2>&1 | tail -10
```

Expected: backend ~594, frontend ~273.

### Step 2: Manual smoke

Bring up dev stack:

```bash
cd /Users/owine/Git/youth-activity-scheduler
YAS_DATABASE_URL="sqlite+aiosqlite:///$(pwd)/data/activities.db" uv run alembic upgrade head 2>&1 | tail -2
YAS_DATABASE_URL="sqlite+aiosqlite:///$(pwd)/data/activities.db" uv run python -m yas api &
sleep 4 && curl -sf http://localhost:8080/healthz && echo " ✓ API up"
cd frontend && npm run dev &
sleep 5 && curl -sfI http://localhost:5173/ -o /dev/null && echo "✓ frontend up"
```

Browser steps (or Playwright MCP):
1. Click "Alerts" in TopBar → lands on `/alerts` (Outbox tab default).
2. Verify outbox lists past alerts (or empty state if none).
3. Filter by status=`sent` → list narrows.
4. Click Resend on any alert → row shows "Resend queued" pill briefly; new alert appears at top after invalidation.
5. Click "Digest preview" tab → URL becomes `/alerts?tab=digest`.
6. Iframe renders the digest HTML at fixed 600px.
7. Switch kid via picker → iframe content changes; URL updates with `?kid_digest=N`.
8. Reload page → all state (tab + filters + kid) persists from URL.

Stop servers: `pkill -f "yas api"; pkill -f "vite"`.

### Step 3: Update roadmap doc

Find the row in `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md` containing `| 8 | Alerts:` and update its status:

```
| 8 | Alerts: outbox, resend, digest preview | ✅ Phase 7-4 (2026-05-01) |
```

```bash
git add docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md
git commit -m "docs(roadmap): mark master §7 page #8 closed (Phase 7-4)

Alerts page (outbox + digest preview) shipped. Master §7 page
coverage: 9 of 9 pages met. Phase 7 complete; Phases 8 (polish)
and 9 (observation) are all that remain to v1."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

### Step 4: Push + PR

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git push -u origin phase-7-4-alerts-page
gh pr create --title "phase 7-4: alerts page (outbox + digest preview)" --body "$(cat <<'EOF'
## Summary

Closes master §7 page #8 (Alerts: outbox, resend, digest preview). New top-level \`/alerts\` route with two tabs.

- **Outbox tab**: paginated list of all alerts beyond the inbox window. Filters: kid / type / status (pending|sent|skipped) / since-until date range. Resend button per row clones the alert; new clone appears at top after cache invalidation.
- **Digest preview tab**: per-kid render of the next scheduled digest in a sandboxed iframe (\`sandbox="allow-same-origin"\` for inline styles, no scripts). Top-line generated via the deterministic template fallback (\`llm=None\`) so previews never bill against the daily LLM cap.
- **URL search-param state**: \`?tab=\`, \`?kid=\`, \`?type=\`, \`?status=\`, \`?since=\`, \`?until=\`, \`?page=\`, \`?kid_digest=\` all persist filters/tab/page across reloads.
- **Backend**: \`AlertOut\` extends with \`summary_text\` (composed via existing \`summarize_alert\` helper); new \`GET /api/digest/preview?kid_id=N\` endpoint wires \`gather_digest_payload\` + \`generate_top_line(llm=None)\` + \`render_digest\`.
- **No new dependencies.** Reuses existing \`<Card>\`, \`<Badge>\`, \`<Button>\`, \`<Skeleton>\`, \`<EmptyState>\`, \`<ErrorBanner>\`. New \`Mail\` icon from lucide-react (already pinned).

Frontend tests: 251 → ~273 (+22 across 5 new test files). Backend tests: 593 → ~594 (+1 for AlertOut.summary_text). The digest preview endpoint already exists from a previous phase; its tests already pass.

## Test plan

- [x] uv run pytest -q (~594 passing)
- [x] uv run ruff check / ruff format --check / mypy clean
- [x] cd frontend && npm run typecheck && npm run lint clean
- [x] cd frontend && npm run test (~273 passing)
- [x] Manual smoke: navigated /alerts; verified outbox lists alerts with summary_text; filter by status narrows list; resend button clones; digest preview tab renders in iframe; kid picker switches preview content; URL state persists across reloads
- [ ] CI passes

## Spec / plan

- Spec: \`docs/superpowers/specs/2026-05-01-phase-7-4-alerts-page-design.md\`
- Plan: \`docs/superpowers/plans/2026-05-01-phase-7-4-alerts-page.md\`
- Roadmap: \`docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md\` (page #8 flipped to ✅)

## Master §7 page-coverage delta

- Closes master §7 page #8 (Alerts).
- After this PR: **9 of 9** master §7 pages met.
- **Phase 7 complete.** Only Phase 8 (polish) and Phase 9 (observation) remain to v1.
EOF
)"
```

Return the PR URL.

---

## Notes for the implementer

- **`summarize_alert` reads names from `Alert.payload_json`**, not from Offering/Site joins. Don't add unnecessary joins. The Alert enqueuer pre-populates `payload_json["offering_name"]` etc. when creating the alert.
- **`render_digest` returns `(plain, html)`** — plain first. The endpoint must unpack in that order or the iframe will render plain text wrapped in `<html>` from a rogue cast.
- **`generate_top_line(payload, llm=None, cost_cap_remaining_usd=0.0)`** forces the deterministic template fallback. v1 doesn't bill LLM cost for previews; future polish can thread a budget.
- **`useResendAlert` invalidation** is broad (`['alerts']` prefix) — covers all parameterized cache keys including different filter combos.
- **TanStack Router URL search state**: this codebase has no `validateSearch` precedent. The plan uses a minimal passthrough that filters non-string values; if the implementer prefers a typed schema, they can swap to Zod-based validation, but it's not required.
- **Iframe height**: 600px fixed for v1. If digests are long, the user scrolls inside the iframe.
- **No `vi.useFakeTimers()` needed for OutboxRow tests**: the 3-second auto-clear timeout doesn't need to be exercised in tests; just verify the pill appears, not that it disappears (or use `vi.useFakeTimers` if a test asserts the disappear path).
- **No GitHub auto-close keywords** in commit messages.

## Estimated test count after each task

| Task | New tests | Cumulative frontend | Cumulative backend |
|---|---|---|---|
| 1 (AlertOut.summary_text) | 0 frontend, +1 backend | 251 | 594 |
| 2 (verify digest endpoint) | 0 | 251 | 594 |
| 3 (types + 3 hooks) | +2 | 253 | 594 |
| 4 (OutboxFilterBar) | +4 | 257 | 594 |
| 5 (OutboxRow) | +4 | 261 | 594 |
| 6 (OutboxPanel) | +4 | 265 | 594 |
| 7 (DigestPreviewPanel) | +5 | 270 | 594 |
| 8 (route + nav) | +2 | 272 | 594 |
| 9 (smoke + PR) | 0 | 272 | 594 |

(Spec target was ~273 frontend; 272 is close enough.)
