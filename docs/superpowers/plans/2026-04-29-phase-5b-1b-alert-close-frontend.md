# Phase 5b-1b — Alert Close Frontend Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire backend alert close/reopen into the React inbox UI with optimistic mutations, add a "Show closed" toggle, and stop the worker from sending pending alerts that are already closed.

**Architecture:** Establish the codebase's first TanStack Query mutation pattern in a new `lib/mutations.ts` module (optimistic `setQueryData` + rollback on error). Wire two action buttons into `AlertDetailDrawer` that branch on `closed_at`. Extend `useInboxSummary` with an `includeClosed` flag, surface a checkbox on `AlertsSection`. One-line worker change to skip closed alerts in the pending-sends query.

**Tech Stack:** React 19, TanStack Query 5, MSW for tests, Vitest + React Testing Library, FastAPI/SQLAlchemy backend, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-04-29-phase-5b-1b-alert-close-frontend-design.md`

**Project conventions to maintain:**
- Frontend gates: `npm run lint`, `npm run typecheck`, `npm run test`, `npm run format:check` (run from `frontend/`).
- Backend gates: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` (run from repo root).
- All commits signed via 1Password SSH agent. Set `SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"` before each `git commit` in fresh shells (subagents do NOT inherit it). After each commit, verify with `git cat-file commit HEAD | grep -q '^gpgsig '`.
- Branch already exists: `phase-5b-1b-alert-close-frontend`. Do NOT commit to `main`.
- Hand-maintained types in `frontend/src/lib/types.ts` mirror Pydantic schemas in `src/yas/web/routes/`. When backend types change, update both — they don't drift silently because integration tests catch shape mismatches.

---

## File Structure

**Create:**
- `frontend/src/lib/mutations.ts` — `useCloseAlert`, `useReopenAlert` hooks + `keyIncludesClosed` helper.
- `frontend/src/lib/mutations.test.tsx` — tests for both mutations including rollback paths.
- `frontend/src/components/inbox/AlertDetailDrawer.test.tsx` — drawer state-machine tests (open vs closed alert, error path).

**Modify:**
- `frontend/src/lib/api.ts` — add `api.post<T>(path, body)`.
- `frontend/src/lib/types.ts` — add `CloseReason`, extend `InboxAlert`.
- `frontend/src/lib/queries.ts` — extend `useInboxSummary` to accept `{ days?, includeClosed? }`.
- `frontend/src/components/inbox/AlertDetailDrawer.tsx` — render close/reopen buttons + inline `ErrorBanner`.
- `frontend/src/components/inbox/AlertsSection.tsx` — "Show closed" toggle, greyed closed rows, pass selected alert through.
- `frontend/src/components/inbox/AlertsSection.test.tsx` — toggle test + closed-row styling assertion.
- `frontend/src/test/handlers.ts` — MSW handlers for close/reopen.
- `frontend/src/routes/index.tsx` (if it calls `useInboxSummary` directly) — pass through `includeClosed` if needed.
- `src/yas/worker/delivery_loop.py:39-44` — add `Alert.closed_at.is_(None)` to pending-sends query.
- `tests/integration/test_alerts_delivery_loop.py` — add `test_closed_pending_alert_is_not_delivered`.

---

## Task 1 — Worker change: skip closed alerts in pending-sends (TDD, backend)

**Files:**
- Modify: `tests/integration/test_alerts_delivery_loop.py`
- Modify: `src/yas/worker/delivery_loop.py`

End state: A closed pending alert is not delivered. New regression test passes; existing 542 backend tests still pass.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_alerts_delivery_loop.py`. Reuse the file's existing `_make_engine`, `_alert`, `_email_notifier`, `_settings` helpers and the `seed_default_routing` import:

```python
@pytest.mark.asyncio
async def test_closed_pending_alert_is_not_delivered(tmp_path):  # type: ignore[no-untyped-def]
    """Regression: closing an alert before scheduled_for cancels its delivery."""
    engine = await _make_engine(tmp_path)
    now = datetime.now(UTC)

    async with session_scope(engine) as s:
        await seed_default_routing(s)
        a = _alert(
            alert_type=AlertType.new_match.value,
            scheduled_for=now - timedelta(seconds=1),
        )
        # Close it before the worker tick.
        a.closed_at = now
        s.add(a)
        await s.flush()

    email_notifier = _email_notifier("email")
    notifiers: dict[str, FakeNotifier] = {"email": email_notifier}
    settings = _settings(alert_delivery_tick_s=1, alert_coalesce_normal_s=600)

    task = asyncio.create_task(alert_delivery_loop(engine, settings, notifiers))
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=2.5)
    except (TimeoutError, asyncio.CancelledError):
        pass
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async with session_scope(engine) as s:
        alerts = (await s.execute(select(Alert))).scalars().all()
    assert len(alerts) == 1
    assert alerts[0].sent_at is None  # not delivered
    assert email_notifier.sent == []  # notifier never called
```

- [ ] **Step 2: Run the new test; confirm it fails**

```bash
uv run pytest tests/integration/test_alerts_delivery_loop.py::test_closed_pending_alert_is_not_delivered -q --no-cov
```

Expected: FAIL — without the worker filter, `sent_at` will be set (delivery happened).

- [ ] **Step 3: Add the filter clause**

In `src/yas/worker/delivery_loop.py`, find the pending-sends query around line 39-44. The query currently reads:

```python
select(Alert)
.where(
    Alert.sent_at.is_(None),
    Alert.skipped.is_(False),
    Alert.scheduled_for <= now,
)
```

Add one clause:

```python
select(Alert)
.where(
    Alert.sent_at.is_(None),
    Alert.skipped.is_(False),
    Alert.closed_at.is_(None),
    Alert.scheduled_for <= now,
)
```

- [ ] **Step 4: Re-run the new test; confirm pass**

```bash
uv run pytest tests/integration/test_alerts_delivery_loop.py::test_closed_pending_alert_is_not_delivered -q --no-cov
```

Expected: PASS.

- [ ] **Step 5: Run full backend suite + gates**

```bash
uv run pytest -q --no-cov && uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: 543 passed (542 + 1); ruff/format/mypy clean.

- [ ] **Step 6: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add tests/integration/test_alerts_delivery_loop.py src/yas/worker/delivery_loop.py
git commit -m "fix(worker): skip closed alerts in delivery loop pending-sends query

Closing an alert before its scheduled_for time now cancels the
pending send, matching user intent. Carved out from 5b-1a §6 as a
follow-up to be resolved during 5b-1b."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 2 — Frontend types + `api.post` (no behavior change)

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`

End state: `InboxAlert` has the two new fields, a `CloseReason` type alias is exported, and `api.post<T>(path, body)` exists. Existing frontend tests still pass.

- [ ] **Step 1: Extend `InboxAlert` and export `CloseReason`**

In `frontend/src/lib/types.ts`, find the `InboxAlert` interface. Append two fields after `summary_text`:

```ts
  summary_text: string;
  closed_at: string | null;
  close_reason: CloseReason | null;
}
```

Add the `CloseReason` export near the top of the file (next to `AlertType`):

```ts
export type CloseReason = 'acknowledged' | 'dismissed';
```

- [ ] **Step 2: Add `api.post` to `lib/api.ts`**

In `frontend/src/lib/api.ts`, extend the exported `api` object:

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
};
```

- [ ] **Step 3: Update test fixtures so existing tests still type-check**

In `frontend/src/components/inbox/AlertsSection.test.tsx`, the `alerts` fixture object now needs the two new fields. Add to each entry:

```ts
    closed_at: null,
    close_reason: null,
```

(Add the same two fields to the `inboxSummaryFixture` test data in `frontend/src/test/handlers.ts` *only if* MSW responses are typed — they aren't, the response is loose JSON, so the file may not need changes. Leave as-is unless typecheck fails.)

- [ ] **Step 4: Run frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test && cd ..
```

Expected: typecheck clean, lint clean, all tests pass.

- [ ] **Step 5: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add frontend/src/lib/types.ts frontend/src/lib/api.ts frontend/src/components/inbox/AlertsSection.test.tsx
git commit -m "feat(frontend): InboxAlert.closed_at + close_reason; api.post helper"
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 3 — Mutation hooks: `useCloseAlert` + `useReopenAlert` (TDD)

**Files:**
- Create: `frontend/src/lib/mutations.ts`
- Create: `frontend/src/lib/mutations.test.tsx`
- Modify: `frontend/src/test/handlers.ts`

End state: Two mutation hooks exist with optimistic update + rollback. 4 new tests pass. Frontend suite stays green.

- [ ] **Step 1: Add MSW handlers for close + reopen**

In `frontend/src/test/handlers.ts`, append to the `handlers` array:

```ts
import { http, HttpResponse } from 'msw';

// (add inside the existing handlers list)
  http.post('/api/alerts/:id/close', async ({ request, params }) => {
    const body = (await request.json()) as { reason: 'acknowledged' | 'dismissed' };
    return HttpResponse.json({
      id: Number(params.id),
      type: 'watchlist_hit',
      kid_id: 1,
      offering_id: null,
      site_id: null,
      channels: ['email'],
      scheduled_for: '2026-04-24T12:00:00Z',
      sent_at: null,
      skipped: false,
      dedup_key: 'k',
      payload_json: {},
      closed_at: '2026-04-29T12:00:00Z',
      close_reason: body.reason,
    });
  }),
  http.post('/api/alerts/:id/reopen', ({ params }) => {
    return HttpResponse.json({
      id: Number(params.id),
      type: 'watchlist_hit',
      kid_id: 1,
      offering_id: null,
      site_id: null,
      channels: ['email'],
      scheduled_for: '2026-04-24T12:00:00Z',
      sent_at: null,
      skipped: false,
      dedup_key: 'k',
      payload_json: {},
      closed_at: null,
      close_reason: null,
    });
  }),
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/lib/mutations.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { useCloseAlert, useReopenAlert } from './mutations';
import type { InboxSummary } from './types';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

const seed = (overrides: Partial<InboxSummary['alerts'][number]> = {}) => ({
  id: 1,
  type: 'watchlist_hit' as const,
  kid_id: 1,
  kid_name: 'Sam',
  offering_id: null,
  site_id: null,
  channels: ['email'],
  scheduled_for: '2026-04-24T12:00:00Z',
  sent_at: null,
  skipped: false,
  dedup_key: 'k',
  payload_json: {},
  summary_text: 'Watchlist hit for Sam',
  closed_at: null,
  close_reason: null,
  ...overrides,
});

const seedSummary = (alerts: ReturnType<typeof seed>[]): InboxSummary => ({
  window_start: '2026-04-17T00:00:00Z',
  window_end: '2026-04-24T00:00:00Z',
  alerts,
  new_matches_by_kid: [],
  site_activity: { refreshed_count: 0, posted_new_count: 0, stagnant_count: 0 },
});

describe('useCloseAlert', () => {
  it('removes the alert from the open-only inbox cache', async () => {
    const qc = new QueryClient();
    qc.setQueryData(['inbox', 'summary', 7, 'open-only'], seedSummary([seed()]));

    const { result } = renderHook(() => useCloseAlert(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ alertId: 1, reason: 'acknowledged' });
    });

    const after = qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'open-only']);
    expect(after?.alerts).toEqual([]);
  });

  it('updates (does not remove) the alert in the with-closed inbox cache', async () => {
    const qc = new QueryClient();
    qc.setQueryData(['inbox', 'summary', 7, 'with-closed'], seedSummary([seed()]));

    const { result } = renderHook(() => useCloseAlert(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ alertId: 1, reason: 'dismissed' });
    });

    const after = qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'with-closed']);
    expect(after?.alerts).toHaveLength(1);
    expect(after?.alerts[0].close_reason).toBe('dismissed');
    expect(after?.alerts[0].closed_at).not.toBeNull();
  });

  it('rolls back on server error', async () => {
    server.use(
      http.post('/api/alerts/:id/close', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const original = seedSummary([seed()]);
    qc.setQueryData(['inbox', 'summary', 7, 'open-only'], original);

    const { result } = renderHook(() => useCloseAlert(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ alertId: 1, reason: 'acknowledged' }).catch(() => {});
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const after = qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'open-only']);
    expect(after?.alerts).toHaveLength(1);
    expect(after?.alerts[0].closed_at).toBeNull();
  });
});

describe('useReopenAlert', () => {
  it('clears closed_at and close_reason in cached row', async () => {
    const qc = new QueryClient();
    qc.setQueryData(
      ['inbox', 'summary', 7, 'with-closed'],
      seedSummary([seed({ closed_at: '2026-04-29T12:00:00Z', close_reason: 'acknowledged' })]),
    );

    const { result } = renderHook(() => useReopenAlert(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ alertId: 1 });
    });

    const after = qc.getQueryData<InboxSummary>(['inbox', 'summary', 7, 'with-closed']);
    expect(after?.alerts[0].closed_at).toBeNull();
    expect(after?.alerts[0].close_reason).toBeNull();
  });
});
```

- [ ] **Step 3: Run the tests; confirm they fail**

```bash
cd frontend && npm run test -- mutations 2>&1 | tail -20 && cd ..
```

Expected: FAIL — `useCloseAlert`/`useReopenAlert` not exported yet.

- [ ] **Step 4: Implement the mutations**

Create `frontend/src/lib/mutations.ts`:

```ts
import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { api } from './api';
import type { CloseReason, InboxAlert, InboxSummary } from './types';

const keyIncludesClosed = (key: QueryKey): boolean => key[3] === 'with-closed';

type Snapshot = ReadonlyArray<readonly [QueryKey, InboxSummary | undefined]>;

interface CloseInput {
  alertId: number;
  reason: CloseReason;
}

export function useCloseAlert() {
  const qc = useQueryClient();
  return useMutation<InboxAlert, Error, CloseInput, { snapshots: Snapshot }>({
    mutationFn: ({ alertId, reason }) =>
      api.post<InboxAlert>(`/api/alerts/${alertId}/close`, { reason }),

    onMutate: async ({ alertId, reason }) => {
      await qc.cancelQueries({ queryKey: ['inbox', 'summary'] });
      const snapshots = qc.getQueriesData<InboxSummary>({ queryKey: ['inbox', 'summary'] });

      for (const [key, data] of snapshots) {
        if (!data) continue;
        const closedAt = new Date().toISOString();
        const updated = data.alerts.map((a) =>
          a.id === alertId ? { ...a, closed_at: closedAt, close_reason: reason } : a,
        );
        const filtered = keyIncludesClosed(key)
          ? updated
          : updated.filter((a) => a.closed_at == null);
        qc.setQueryData<InboxSummary>(key, { ...data, alerts: filtered });
      }
      return { snapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['inbox', 'summary'] });
    },
  });
}

export function useReopenAlert() {
  const qc = useQueryClient();
  return useMutation<InboxAlert, Error, { alertId: number }, { snapshots: Snapshot }>({
    mutationFn: ({ alertId }) => api.post<InboxAlert>(`/api/alerts/${alertId}/reopen`),

    onMutate: async ({ alertId }) => {
      await qc.cancelQueries({ queryKey: ['inbox', 'summary'] });
      const snapshots = qc.getQueriesData<InboxSummary>({ queryKey: ['inbox', 'summary'] });

      for (const [key, data] of snapshots) {
        if (!data) continue;
        const updated = data.alerts.map((a) =>
          a.id === alertId ? { ...a, closed_at: null, close_reason: null } : a,
        );
        qc.setQueryData<InboxSummary>(key, { ...data, alerts: updated });
      }
      return { snapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['inbox', 'summary'] });
    },
  });
}
```

- [ ] **Step 5: Re-run tests; confirm all 4 pass**

```bash
cd frontend && npm run test -- mutations 2>&1 | tail -10 && cd ..
```

Expected: 4 passed.

- [ ] **Step 6: Run all frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test && cd ..
```

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add frontend/src/lib/mutations.ts frontend/src/lib/mutations.test.tsx frontend/src/test/handlers.ts
git commit -m "feat(frontend): useCloseAlert + useReopenAlert with optimistic rollback

Establishes the codebase's first TanStack Query mutation pattern:
optimistic setQueryData across both open-only and with-closed
inbox cache variants, with onError snapshot rollback."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 4 — Drawer affordance: close/reopen buttons + inline error (TDD)

**Files:**
- Create: `frontend/src/components/inbox/AlertDetailDrawer.test.tsx`
- Modify: `frontend/src/components/inbox/AlertDetailDrawer.tsx`

End state: Drawer renders Acknowledge + Dismiss for open alerts and Reopen for closed alerts. Mutation errors render via `ErrorBanner`. Buttons disabled while in-flight. New tests pass.

- [ ] **Step 1: Write the failing test file**

Create `frontend/src/components/inbox/AlertDetailDrawer.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { AlertDetailDrawer } from './AlertDetailDrawer';
import type { InboxAlert } from '@/lib/types';

const openAlert: InboxAlert = {
  id: 1,
  type: 'watchlist_hit',
  kid_id: 1,
  kid_name: 'Sam',
  offering_id: null,
  site_id: null,
  channels: ['email'],
  scheduled_for: '2026-04-24T12:00:00Z',
  sent_at: null,
  skipped: false,
  dedup_key: 'k',
  payload_json: {},
  summary_text: 'Watchlist hit for Sam',
  closed_at: null,
  close_reason: null,
};

const closedAlert: InboxAlert = {
  ...openAlert,
  closed_at: '2026-04-29T11:00:00Z',
  close_reason: 'dismissed',
};

function renderDrawer(alert: InboxAlert | null, onOpenChange = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AlertDetailDrawer alert={alert} open={alert !== null} onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  );
}

describe('AlertDetailDrawer', () => {
  it('renders Acknowledge and Dismiss for an open alert', () => {
    renderDrawer(openAlert);
    expect(screen.getByRole('button', { name: /acknowledge/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /dismiss/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reopen/i })).not.toBeInTheDocument();
  });

  it('renders Reopen for a closed alert', () => {
    renderDrawer(closedAlert);
    expect(screen.getByRole('button', { name: /reopen/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /acknowledge/i })).not.toBeInTheDocument();
  });

  it('closes the drawer after a successful close mutation', async () => {
    const onOpenChange = vi.fn();
    renderDrawer(openAlert, onOpenChange);

    await userEvent.click(screen.getByRole('button', { name: /acknowledge/i }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it('shows an inline error banner if the mutation fails', async () => {
    server.use(
      http.post('/api/alerts/:id/close', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    renderDrawer(openAlert);

    await userEvent.click(screen.getByRole('button', { name: /acknowledge/i }));

    await waitFor(() => expect(screen.getByText(/couldn't load|boom|error/i)).toBeInTheDocument());
    // Buttons re-enabled after error.
    expect(screen.getByRole('button', { name: /acknowledge/i })).not.toBeDisabled();
  });
});
```

- [ ] **Step 2: Run tests; confirm they fail**

```bash
cd frontend && npm run test -- AlertDetailDrawer 2>&1 | tail -10 && cd ..
```

Expected: FAIL — buttons not rendered yet.

- [ ] **Step 3: Update the drawer component**

Replace `frontend/src/components/inbox/AlertDetailDrawer.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import type { CloseReason, InboxAlert } from '@/lib/types';
import { AlertTypeBadge } from '@/components/alerts/AlertTypeBadge';
import { fmt } from '@/lib/format';
import { useCloseAlert, useReopenAlert } from '@/lib/mutations';

export function AlertDetailDrawer({
  alert,
  open,
  onOpenChange,
}: {
  alert: InboxAlert | null;
  open: boolean;
  onOpenChange: (b: boolean) => void;
}) {
  const close = useCloseAlert();
  const reopen = useReopenAlert();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const inFlight = close.isPending || reopen.isPending;

  // Clear any prior error when the drawer's alert changes.
  useEffect(() => {
    setErrorMsg(null);
    close.reset();
    reopen.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alert?.id]);

  if (!alert) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent />
      </Sheet>
    );
  }

  const handleClose = (reason: CloseReason) => {
    setErrorMsg(null);
    close.mutate(
      { alertId: alert.id, reason },
      {
        onSuccess: () => onOpenChange(false),
        onError: (err) => setErrorMsg(err.message || 'Failed to close alert'),
      },
    );
  };

  const handleReopen = () => {
    setErrorMsg(null);
    reopen.mutate(
      { alertId: alert.id },
      {
        onSuccess: () => onOpenChange(false),
        onError: (err) => setErrorMsg(err.message || 'Failed to reopen alert'),
      },
    );
  };

  return (
    <Sheet
      open={open}
      onOpenChange={(o) => {
        // Suppress user-initiated dismiss while a mutation is in-flight.
        if (inFlight && !o) return;
        onOpenChange(o);
      }}
    >
      <SheetContent>
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <AlertTypeBadge type={alert.type} /> {alert.kid_name ?? '—'}
          </SheetTitle>
          <SheetDescription>{alert.summary_text}</SheetDescription>
        </SheetHeader>
        <dl className="mt-6 space-y-2 text-sm">
          <div>
            <dt className="text-muted-foreground">Scheduled for</dt>
            <dd>{fmt(alert.scheduled_for)}</dd>
          </div>
          {alert.sent_at && (
            <div>
              <dt className="text-muted-foreground">Sent at</dt>
              <dd>{fmt(alert.sent_at)}</dd>
            </div>
          )}
          <div>
            <dt className="text-muted-foreground">Channels</dt>
            <dd>{alert.channels.join(', ') || '—'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Status</dt>
            <dd>
              {alert.closed_at
                ? `Closed (${alert.close_reason}) at ${fmt(alert.closed_at)}`
                : alert.skipped
                  ? 'Skipped'
                  : alert.sent_at
                    ? 'Sent'
                    : 'Pending'}
            </dd>
          </div>
        </dl>
        <pre className="mt-6 text-xs bg-muted p-3 rounded-md overflow-auto">
          {JSON.stringify(alert.payload_json, null, 2)}
        </pre>

        {errorMsg && (
          <div className="mt-4">
            <ErrorBanner message={errorMsg} />
          </div>
        )}

        <div className="mt-6 flex gap-2">
          {alert.closed_at == null ? (
            <>
              <Button onClick={() => handleClose('acknowledged')} disabled={inFlight}>
                Acknowledge
              </Button>
              <Button
                variant="outline"
                onClick={() => handleClose('dismissed')}
                disabled={inFlight}
              >
                Dismiss
              </Button>
            </>
          ) : (
            <Button onClick={handleReopen} disabled={inFlight}>
              Reopen
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 4: Re-run drawer tests; confirm pass**

```bash
cd frontend && npm run test -- AlertDetailDrawer 2>&1 | tail -10 && cd ..
```

Expected: 4 passed.

- [ ] **Step 5: Run all frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test && cd ..
```

Expected: all clean. The existing `AlertsSection.test.tsx` "renders rows and opens drawer on click" test should still pass — adjust if button labels collide with the existing assertion (the existing test only checks for summary text, so it should be unaffected).

- [ ] **Step 6: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add frontend/src/components/inbox/AlertDetailDrawer.tsx frontend/src/components/inbox/AlertDetailDrawer.test.tsx
git commit -m "feat(frontend): drawer renders close/reopen buttons + inline error

Open alerts get Acknowledge + Dismiss; closed alerts get Reopen.
Buttons disabled while mutation in-flight; user-initiated dismiss
of the drawer is suppressed mid-flight to keep rollback coherent."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 5 — Inbox toggle: "Show closed" + greyed closed rows (TDD)

**Files:**
- Modify: `frontend/src/lib/queries.ts`
- Modify: `frontend/src/components/inbox/AlertsSection.tsx`
- Modify: `frontend/src/components/inbox/AlertsSection.test.tsx`
- Modify (if needed): `frontend/src/routes/index.tsx`

End state: A "Show closed" checkbox on the inbox card flips `include_closed=true`. Closed rows render with `opacity-60` and a "Closed" pill. New tests pass.

- [ ] **Step 1: Update `useInboxSummary` signature**

In `frontend/src/lib/queries.ts`, replace the `useInboxSummary` implementation:

```ts
export function useInboxSummary(opts?: { days?: number; includeClosed?: boolean }) {
  const days = opts?.days ?? 7;
  const includeClosed = opts?.includeClosed ?? false;
  return useQuery({
    queryKey: ['inbox', 'summary', days, includeClosed ? 'with-closed' : 'open-only'],
    queryFn: () => {
      const since = minus(days);
      const until = new Date().toISOString();
      const url = `/api/inbox/summary?since=${encodeURIComponent(since)}&until=${encodeURIComponent(until)}${
        includeClosed ? '&include_closed=true' : ''
      }`;
      return api.get<InboxSummary>(url);
    },
    refetchInterval: 60_000,
  });
}
```

- [ ] **Step 2: Update callers of `useInboxSummary`**

```bash
grep -rn "useInboxSummary" frontend/src/
```

For each caller: if it called `useInboxSummary()` or `useInboxSummary(7)` with a number, update to `useInboxSummary({ days: 7 })`. The new signature is backwards-compatible for the no-arg case but NOT for the positional-number case.

For example, `frontend/src/routes/index.tsx` (or wherever the dashboard root lives) likely calls it positionally — update each call site.

- [ ] **Step 3: Add a failing test for the toggle**

In `frontend/src/components/inbox/AlertsSection.test.tsx`, the existing test currently passes `alerts` directly into the component. We're going to change that — the toggle owns its own state inside the section. Replace the test file body with:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AlertsSection } from './AlertsSection';
import type { InboxAlert } from '@/lib/types';

const open: InboxAlert = {
  id: 1,
  type: 'watchlist_hit',
  kid_id: 1,
  kid_name: 'Sam',
  offering_id: null,
  site_id: null,
  channels: ['email'],
  scheduled_for: '2026-04-24T12:00:00Z',
  sent_at: null,
  skipped: false,
  dedup_key: 'k',
  payload_json: {},
  summary_text: 'Watchlist hit for Sam',
  closed_at: null,
  close_reason: null,
};
const closed: InboxAlert = {
  ...open,
  id: 2,
  summary_text: 'Closed alert',
  closed_at: '2026-04-29T11:00:00Z',
  close_reason: 'dismissed',
};

function renderSection(
  alerts: InboxAlert[],
  opts?: { onIncludeClosedChange?: (b: boolean) => void },
) {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <AlertsSection alerts={alerts} onIncludeClosedChange={opts?.onIncludeClosedChange} />
    </QueryClientProvider>,
  );
}

describe('AlertsSection', () => {
  it('renders empty state', () => {
    renderSection([]);
    expect(screen.getByText(/no alerts this week/i)).toBeInTheDocument();
  });

  it('renders rows and opens drawer on click', async () => {
    renderSection([open]);
    await userEvent.click(screen.getByText('Watchlist hit for Sam'));
    expect(screen.getAllByText('Watchlist hit for Sam').length).toBeGreaterThan(0);
  });

  it('toggling "Show closed" calls onIncludeClosedChange so the parent can refetch', async () => {
    const onIncludeClosedChange = vi.fn();
    renderSection([open], { onIncludeClosedChange });
    await userEvent.click(screen.getByLabelText(/show closed/i));
    expect(onIncludeClosedChange).toHaveBeenCalledWith(true);
  });

  it('renders a "Closed" pill on closed rows', () => {
    renderSection([open, closed]);
    expect(screen.getByText(/closed/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Decide ownership of `includeClosed` and update `AlertsSection`**

Two responsibilities collide here: the **section** owns the user-visible toggle; the **route** owns the data fetch. Pick the simplest split:

- The section accepts an optional `onIncludeClosedChange` callback prop. It owns the local checkbox state and calls the prop on change.
- The route (`routes/index.tsx` or wherever) holds the `includeClosed` boolean and passes it to `useInboxSummary({ includeClosed })`.

Replace `frontend/src/components/inbox/AlertsSection.tsx`:

```tsx
import { useState } from 'react';
import type { InboxAlert } from '@/lib/types';
import { AlertTypeBadge } from '@/components/alerts/AlertTypeBadge';
import { AlertDetailDrawer } from './AlertDetailDrawer';
import { EmptyState } from '@/components/common/EmptyState';

export function AlertsSection({
  alerts,
  onIncludeClosedChange,
}: {
  alerts: InboxAlert[];
  onIncludeClosedChange?: (b: boolean) => void;
}) {
  const [selected, setSelected] = useState<InboxAlert | null>(null);
  const [includeClosed, setIncludeClosed] = useState(false);

  return (
    <section aria-labelledby="alerts-heading" className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 id="alerts-heading" className="text-xs font-semibold uppercase text-muted-foreground">
          Alerts ({alerts.length})
        </h2>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={includeClosed}
            onChange={(e) => {
              setIncludeClosed(e.target.checked);
              onIncludeClosedChange?.(e.target.checked);
            }}
          />
          Show closed
        </label>
      </div>
      {alerts.length === 0 ? (
        <EmptyState>No alerts this week. Quiet is good.</EmptyState>
      ) : (
        <ul className="space-y-1.5">
          {alerts.map((a) => {
            const isClosed = a.closed_at != null;
            return (
              <li
                key={a.id}
                className={`rounded-md border border-border p-3 cursor-pointer hover:bg-accent transition ${
                  isClosed ? 'opacity-60' : ''
                }`}
                onClick={() => setSelected(a)}
              >
                <div className="flex items-start gap-3">
                  <AlertTypeBadge type={a.type} />
                  <span className="flex-1 text-sm">{a.summary_text}</span>
                  {isClosed && (
                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground border border-border rounded px-1.5 py-0.5">
                      Closed
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <AlertDetailDrawer
        alert={selected}
        open={selected !== null}
        onOpenChange={(o) => !o && setSelected(null)}
      />
    </section>
  );
}
```

- [ ] **Step 5: Wire the callback at the dashboard root**

```bash
grep -n "AlertsSection\b" frontend/src/routes/index.tsx
```

Update the route to keep `includeClosed` state, pass it to `useInboxSummary`, and pass `onIncludeClosedChange={setIncludeClosed}` into `<AlertsSection>`. Sketch:

```tsx
const [includeClosed, setIncludeClosed] = useState(false);
const { data } = useInboxSummary({ includeClosed });
// …
<AlertsSection alerts={data?.alerts ?? []} onIncludeClosedChange={setIncludeClosed} />
```

(If `routes/index.tsx` doesn't render `<AlertsSection>` directly, find the file that does — `grep -rn "<AlertsSection" frontend/src/`. Wire the callback at that level.)

- [ ] **Step 6: Run frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test && cd ..
```

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add frontend/src/lib/queries.ts frontend/src/components/inbox/AlertsSection.tsx frontend/src/components/inbox/AlertsSection.test.tsx frontend/src/routes/
git commit -m "feat(frontend): 'Show closed' toggle on inbox + greyed closed rows

useInboxSummary gains an includeClosed option that flips
include_closed=true on the request and varies the cache key.
Closed rows render with opacity-60 and a 'Closed' pill."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 6 — Manual smoke + final exit gates

End state: All exit criteria from spec §9 verified. Branch ready to push and PR.

- [ ] **Step 1: Backend gates (full)**

```bash
uv run pytest -q --no-cov && uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: 543 passed; lint/format/type clean.

- [ ] **Step 2: Frontend gates (full)**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test && npm run format:check && cd ..
```

Expected: all clean.

- [ ] **Step 3: Manual smoke test**

In one terminal:

```bash
uv run uvicorn yas.web.app:app --reload --port 8000
```

In another:

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173`. Walk through:

1. **Seed an alert.** Easiest path: use an existing fixture or hit the API to create one — `curl -X POST http://localhost:8000/api/...` (use whichever creation path exists), or run a fixture script if one exists. If no easy seed exists in dev, skip to step 4 and rely on automated tests.
2. **Click a row → drawer opens → click Acknowledge.** Row should vanish from the list immediately (optimistic) and the drawer should close. Refresh the page; row stays gone.
3. **Tick "Show closed".** The closed row reappears greyed with a "Closed" pill.
4. **Click the closed row → drawer shows Reopen.** Click Reopen. Row's pill disappears (still in list because toggle is on); untick the toggle and confirm row is back in the open list.

If steps 1-4 work, you're done. Any UI breakage that wasn't caught by tests goes back into the test suite as a regression.

- [ ] **Step 4: Push and open PR**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git push -u origin phase-5b-1b-alert-close-frontend
gh pr create --title "phase 5b-1b: alert close frontend wiring" --body "$(cat <<'EOF'
## Summary
- First TanStack Query mutation pattern: `useCloseAlert` + `useReopenAlert` with optimistic `setQueryData` and `onError` rollback
- AlertDetailDrawer renders Acknowledge + Dismiss for open alerts; Reopen for closed alerts; inline ErrorBanner on mutation failure
- AlertsSection: "Show closed" toggle flips `include_closed=true`; closed rows greyed with "Closed" pill
- Worker no longer delivers closed pending alerts (resolves the carve-out from 5b-1a §6)

## Test plan
- [x] uv run pytest -q (543 passed; +1 worker regression test)
- [x] uv run ruff check . && uv run ruff format --check . clean
- [x] uv run mypy src clean
- [x] cd frontend && npm run typecheck clean
- [x] cd frontend && npm run lint clean
- [x] cd frontend && npm run test (mutations + drawer + section all pass)
- [x] Manual smoke: close → row vanishes; toggle → row reappears greyed; reopen → row returns
- [ ] CI passes
EOF
)"
```

- [ ] **Step 5: Wait for CI and merge**

After CI is green and any reviewer comments are addressed, merge with `gh pr merge <N> --squash` (matches this repo's convention).

---

## Notes for the implementer

- **No new dependencies.** Everything in this slice uses libraries already in `frontend/package.json` (`@tanstack/react-query`, `msw`, `@testing-library/*`).
- **The mutation pattern in Task 3 is canonical.** Future mutations in this codebase should follow the same `onMutate` (snapshot + optimistic) + `onError` (restore) + `onSettled` (invalidate) shape.
- **`api.post` is intentionally minimal** — `body` is JSON-stringified or omitted. Don't add headers, retries, or timeout logic until a use case demands it.
- **The drawer's `useEffect` clears mutation state on alert change** — this is what prevents a stale error banner from appearing when the user switches between alerts.
- **The `routes/index.tsx` wiring in Task 5 Step 5 is approximate** — read the file before editing. The shape may differ; the goal is just to lift `includeClosed` state to whatever component renders `<AlertsSection>` and feed it into `useInboxSummary`.
