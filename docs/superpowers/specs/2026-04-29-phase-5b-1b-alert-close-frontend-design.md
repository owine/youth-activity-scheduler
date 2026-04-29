# Phase 5b-1b — Alert Close Frontend Wiring (Design)

**Status:** Approved (brainstorming complete 2026-04-29).
**Predecessor:** Phase 5b-1a (`docs/superpowers/specs/2026-04-28-phase-5b-1a-alert-close-design.md`) — backend close/reopen routes and `include_closed` query param.
**Succeeds into:** No immediate successor planned. Future closed-alerts route or bulk operations are tracked as out-of-scope below.

## 1. Purpose and scope

Wire the alert close/reopen affordances into the React inbox UI. This is the codebase's first TanStack Query mutation, so it also establishes the optimistic-update + rollback pattern future mutations will follow. As part of the same slice, the delivery worker is tightened so closed alerts no longer fire pending sends — closing the latent footgun carved out in 5b-1a §6.

### 1.1 In scope

- Two TanStack Query mutation hooks (`useCloseAlert`, `useReopenAlert`) in a new `frontend/src/lib/mutations.ts` module, with optimistic cache surgery and rollback on error.
- Drawer affordance: when an alert is open, two buttons (Acknowledge, Dismiss); when closed, a single Reopen button. Mutation errors render inline via the existing `ErrorBanner` component.
- Inbox-summary toggle: a "Show closed" checkbox on `AlertsSection` that flips `include_closed=true` on the existing `useInboxSummary` query.
- Frontend type changes: `InboxAlert` gains `closed_at: string | null` and `close_reason: 'acknowledged' | 'dismissed' | null`.
- Worker change: `delivery_loop.py` adds `Alert.closed_at.is_(None)` to the pending-sends query, so a close cancels any not-yet-sent delivery. One regression test.
- Frontend tests (Vitest + RTL) for both mutations, the drawer state machine, and the toggle behavior. MSW handler additions for `POST /close` and `POST /reopen`.

### 1.2 Out of scope

- **Toast/snackbar library** (e.g. `sonner`). The drawer is open at click time, so inline error is contextual; introducing a toast system here is premature. Revisit when a second mutation needs an error surface that fires from outside a contextual UI.
- **Undo affordance.** Gmail-style "Closed. Undo?" toast was considered and declined for the same reason. Reopen is reachable via "Show closed" → drawer.
- **Bulk operations.** No "mark all closed" / multi-id close.
- **Dedicated closed-alerts route.** Toggle on the existing inbox card is sufficient for a single-household app.
- **`?closed` filter on `GET /api/alerts` list endpoint.** Not needed without a closed-alerts route.
- **Audit trail / history.** The `closed_at` + `close_reason` columns are sufficient; no separate history table.
- **Inline list-row close buttons.** Drawer-only flow; revisit if alert volumes ever justify it.

## 2. Mutation pattern

Establishes the canonical optimistic-mutation pattern for this codebase:

```ts
// frontend/src/lib/mutations.ts
export function useCloseAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ alertId, reason }: { alertId: number; reason: 'acknowledged' | 'dismissed' }) =>
      api.post<AlertOut>(`/api/alerts/${alertId}/close`, { reason }),

    onMutate: async ({ alertId, reason }) => {
      // Cancel in-flight inbox queries so they don't overwrite our optimistic update.
      await qc.cancelQueries({ queryKey: ['inbox', 'summary'] });

      // Snapshot every cached InboxSummary (covers both include_closed=false and =true variants).
      const snapshots = qc.getQueriesData<InboxSummary>({ queryKey: ['inbox', 'summary'] });

      for (const [key, data] of snapshots) {
        if (!data) continue;
        qc.setQueryData<InboxSummary>(key, {
          ...data,
          alerts: data.alerts
            .map((a) =>
              a.id === alertId
                ? { ...a, closed_at: new Date().toISOString(), close_reason: reason }
                : a,
            )
            // Drop closed rows from views where include_closed is false.
            .filter((a) => keyIncludesClosed(key) || a.closed_at == null),
        });
      }

      return { snapshots };
    },

    onError: (_err, _vars, ctx) => {
      // Restore every cache we touched.
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: () => qc.invalidateQueries({ queryKey: ['inbox', 'summary'] }),
  });
}
```

`useReopenAlert` is analogous: `mutationFn` calls `POST /api/alerts/{id}/reopen`; `onMutate` clears `closed_at`/`close_reason` in the cached row; `onError` restores; `onSettled` invalidates.

Both mutations share a tiny helper for snapshot/rollback to avoid duplication.

## 3. Drawer affordance

`AlertDetailDrawer.tsx` gains a state-machine-style action footer:

```
┌─ Open alert (closed_at == null) ──────────────────┐
│   …existing detail rendering…                     │
│                                                   │
│   [ Acknowledge ]  [ Dismiss ]                    │
│                                                   │
└───────────────────────────────────────────────────┘

┌─ Closed alert (closed_at != null) ────────────────┐
│   …existing detail rendering…                     │
│   Closed: dismissed at 2026-04-29 11:42           │
│                                                   │
│   [ Reopen ]                                      │
│                                                   │
└───────────────────────────────────────────────────┘
```

- Buttons disabled while mutation is in-flight; spinner inside the active button.
- On success, the drawer closes (selection state cleared in `AlertsSection`).
- On failure, the drawer stays open and renders an `<ErrorBanner>` above the action footer with the error message; buttons re-enable.
- Drawer cannot be dismissed (overlay click / Escape) while a mutation is in-flight, to keep the rollback path coherent.

## 4. Inbox toggle

`AlertsSection.tsx`:

```tsx
<section …>
  <div className="flex items-center justify-between">
    <h2 …>Alerts ({alerts.length})</h2>
    <label className="flex items-center gap-1 text-xs">
      <input
        type="checkbox"
        checked={includeClosed}
        onChange={(e) => setIncludeClosed(e.target.checked)}
      />
      Show closed
    </label>
  </div>
  …
</section>
```

`useInboxSummary` accepts an optional `{ includeClosed?: boolean }` argument:

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

Closed rows render with `opacity-60` and a small "Closed" pill; clicking opens the same drawer in its closed-state variant.

`AlertsSection` owns the `includeClosed` state (component-local, no URL param). Initial value: `false`.

The `keyIncludesClosed(key)` helper used in `onMutate` reads the toggle state from the query key (`'with-closed'` vs `'open-only'`), since `setQueryData` updates run against every cached `InboxSummary` variant.

## 5. Worker change

`src/yas/worker/delivery_loop.py:39-44` — pending-sends query gains one clause:

```python
select(Alert)
.where(
    Alert.sent_at.is_(None),
    Alert.skipped.is_(False),
    Alert.closed_at.is_(None),   # NEW
    Alert.scheduled_for <= now,
)
```

A regression test in `tests/integration/test_alerts_delivery_loop.py`: seed an alert with `closed_at` set and `scheduled_for` in the past, run one tick of the delivery loop, assert nothing was sent and `sent_at` remains null.

**Reopen interaction.** After this change, reopening an alert clears `closed_at` and the worker's next tick picks it up (by design: the user explicitly un-cancelled the send).

## 6. Type changes

`frontend/src/lib/types.ts`:

```ts
export type CloseReason = 'acknowledged' | 'dismissed';

export interface InboxAlert {
  // …existing fields…
  closed_at: string | null;
  close_reason: CloseReason | null;
}
```

(Backend already returns these fields — see 5b-1a.)

## 7. Testing

Frontend (Vitest + React Testing Library; match the file naming and fixture style of existing `*.test.tsx` files):

1. **`frontend/src/lib/mutations.test.tsx`** *(new)* —
   - `useCloseAlert` removes the alert from cached open-only inbox.
   - `useCloseAlert` updates (does not remove) the alert in cached with-closed inbox.
   - `useCloseAlert` rolls back cache on server error.
   - `useReopenAlert` clears `closed_at`/`close_reason` and rolls back on error.

2. **`frontend/src/components/inbox/AlertDetailDrawer.test.tsx`** *(new)* —
   - Open alert renders Acknowledge + Dismiss; closed alert renders Reopen.
   - Clicking Acknowledge fires the mutation with `reason: 'acknowledged'`.
   - Mutation error renders the error banner; buttons re-enable.

3. **`frontend/src/components/inbox/AlertsSection.test.tsx`** *(extend existing)* —
   - Toggling "Show closed" changes the request URL to include `include_closed=true`.
   - Closed rows render with a "Closed" pill.

4. **MSW handlers** in `frontend/src/test/handlers.ts` —
   - `POST /api/alerts/:id/close` → returns updated AlertOut.
   - `POST /api/alerts/:id/reopen` → returns updated AlertOut.

Backend:

5. **`tests/integration/test_alerts_delivery_loop.py`** *(extend existing)* —
   - `test_closed_pending_alert_is_not_delivered`: alert with `closed_at` set and `scheduled_for` in the past is skipped by the loop.

Existing 542 backend tests must remain green; existing frontend test suite must remain green.

## 8. Open questions

None blocking. All five decisions from brainstorming are recorded in §1–§5:

- **Q1** (close affordance): drawer-only, two buttons. §3.
- **Q2** (optimistic strategy): optimistic with rollback, no toast. §2.
- **Q3** (closed-alerts visibility): inbox-summary toggle. §4.
- **Q4** (worker suppression): yes — closed alerts are skipped by the delivery loop. §5.
- **Q5** (error surface): inline `ErrorBanner` in the drawer. §3.

## 9. Exit criteria

Phase 5b-1b is complete when:

- `useCloseAlert` and `useReopenAlert` exist and are tested.
- The drawer renders the correct buttons based on `closed_at` and dispatches the right mutation.
- The "Show closed" toggle on the inbox card flips `include_closed` and renders closed rows distinctly.
- The delivery loop skips closed alerts; the regression test pins it down.
- All backend gates green (`pytest`, `ruff`, `mypy`).
- All frontend gates green (`vitest`, `tsc --noEmit`, ESLint).
- Smoke-tested manually in a browser: close an alert → row vanishes; toggle "Show closed" → row reappears greyed; reopen → row returns to the open list.
