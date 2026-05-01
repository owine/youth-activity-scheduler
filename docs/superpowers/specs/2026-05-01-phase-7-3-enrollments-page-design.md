# Phase 7-3 — Enrollments Page Design

**Date:** 2026-05-01
**Status:** Spec
**Author:** Claude + owine
**Closes:** Master §7 page #7 (Enrollments: list, status transitions)
**Roadmap:** `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md` (Phase 7-3)

## Goal

Add a per-kid Enrollments tab at `/kids/$id/enrollments` showing the kid's enrollment history, with inline status transitions and notes/enrolled_at editing. Backend `EnrollmentOut` extends to embed `offering: OfferingSummary` so the frontend renders rich rows without N+1. Closes master §7 page #7.

## Scope

**In scope:**
- Backend: extend `EnrollmentOut` with `offering: OfferingSummary` (mirrors `MatchOut` pattern from Phase 7-2). One small backend test extension.
- Frontend: new `/kids/$id/enrollments` route + tab in `KidTabs`.
- 3 new components in `frontend/src/components/enrollments/`.
- 1 new query hook (`useKidEnrollments`).
- 1 new mutation hook (`useUpdateEnrollment`).
- ~15 new frontend tests + 1 new backend test.

**Out of scope:**
- DELETE-from-history UI. Cancel-via-dropdown preserves history; backend DELETE endpoint is unchanged.
- Cross-kid enrollments page (per Q1). Per-kid tab covers the master §7 page #7 surface.
- Filter chips for active/history beyond the disclosure grouping.
- Bulk status changes / multi-select.
- Inline notes/enrolled_at editing on the row itself (must go through the Edit sheet).
- "Re-enroll from history" button (the status dropdown handles status reversal — same affordance).
- Refactor of existing `useCancelEnrollment` / `useEnrollOffering` hooks. Both stay; the new `useUpdateEnrollment` is broader but the calendar overlay (Phase 5c-2) keeps using its narrow hook to minimize blast radius.

## Background

The backend `/api/enrollments` endpoint suite is fully implemented:
- `GET /api/enrollments` with optional `kid_id`, `offering_id`, `status` query filters.
- `POST /api/enrollments` creates a row, applies `apply_enrollment_block` (creates an UnavailabilityBlock when status=`enrolled`), and rematches the kid.
- `PATCH /api/enrollments/{id}` updates any of `status` / `notes` / `enrolled_at`, then runs the same materializer + rematch chain.
- `DELETE /api/enrollments/{id}` removes the row + rematches.

`Enrollment` model fields: `id`, `kid_id`, `offering_id`, `status` (`EnrollmentStatus` enum: `interested | enrolled | waitlisted | completed | cancelled`), `enrolled_at: datetime | None`, `notes: str | None`, `created_at: datetime`.

`EnrollmentOut` currently exposes the model 1:1 — but it does NOT embed offering data. The frontend page would need to either fetch offerings separately (N+1), introduce a composite endpoint, or extend `EnrollmentOut` like `MatchOut` already does.

`KidTabs` (added in Phase 6-1, modified through Phase 6-3) currently has 3 tabs: Matches, Watchlist, Calendar. This phase adds a 4th: Enrollments.

Existing frontend hooks `useEnrollOffering` (POST status=`enrolled`) and `useCancelEnrollment` (PATCH status=`cancelled`) live in `frontend/src/lib/mutations.ts` and are used by the calendar match overlay (Phase 5c-2). They handle a narrow "enroll-from-match" / "cancel-from-row" use case with optimistic updates over the kid's calendar cache.

## Decisions

### D1: Per-kid tab `/kids/$id/enrollments`, not a top-level cross-kid page

Master §7 page #7 says "Enrollments: list, status transitions" without scope. The roadmap's "Per-kid history" framing makes per-kid the natural surface, and it slots cleanly into the existing `KidTabs` mental model (Matches / Watchlist / Calendar / Enrollments).

A top-level cross-kid `/enrollments` page is the offerings-browser shape (Phase 7-2), but enrollments are a different mental model — you typically work on one kid at a time. For a 1–2 kid household, opening each kid's tab is the natural workflow. Cross-kid view is a polish item if it ever comes up.

Master §7 page #7 closes by virtue of the tab being a per-kid "page" — the master design doesn't strictly require top-level pages.

### D2: Extend `EnrollmentOut` with embedded `offering: OfferingSummary` (backend change)

Three options for resolving offering data:
- **A. Extend backend** — mirrors `MatchOut`. Single API call per page load. Small join.
- **B. Frontend N+1** — `useOffering(offeringId)` per row. Pure frontend, but creates a perceptible loading shimmer per row.
- **C. New composite endpoint** — over-engineered for v1.

Picked **A**. The pattern is already proven (Phase 7-2 added `location_lat`/`location_lon` to `OfferingSummary` for the same purpose). Backend change is ~15 LOC + one test.

### D3: Inline `<select>` for status transitions

Five statuses. Three UI options for transitions:
- **A. Inline `<select>` per row** — simplest; covers every transition; tiny render footprint.
- **B. Action buttons (contextual)** — guided UX but more code per state.
- **C. Status pill + popover** — heaviest; needs popover wiring.

Picked **A**. The household app is a casual record of "we signed up / we got in / we finished," not a registration workflow that needs guard rails on transitions. The dropdown PATCH happens immediately with optimistic update + rollback (canonical 5b-1b pattern).

### D4: Linked unavailability surfaced via a clickable badge, not a re-render of block data

Three options:
- **A. Skip explicit surfacing** — offering line already shows the schedule.
- **B. Badge + link to calendar tab** — `🚫 Blocks calendar` pill on enrolled rows, click → `/kids/$id/calendar`.
- **C. Inline block summary** — backend extends EnrollmentOut a third time with linked block data.

Picked **B**. Satisfies the roadmap's "linked unavailability viewer" call-out without duplicating schedule data the row already shows. The pill makes the link to the calendar explicit; the calendar tab is where blocks are visualized.

### D5: Active/History grouping with disclosure (Q5-A)

Five status values split into two groups:
- **Active**: `interested`, `enrolled`, `waitlisted` — always visible, sorted by `created_at` desc.
- **History**: `completed`, `cancelled` — collapsed under `<details>` summary `Show N past enrollments`, sorted by `created_at` desc.

Mirrors the urgency-grouped layout of `/kids/$id/matches`. Keeps the page actionable; history is one click away when needed.

### D6: Edit sheet for notes + enrolled_at (status NOT editable in the sheet)

Status changes happen via the row's dropdown (D3). Notes and `enrolled_at` editing happens in a `<EnrollmentEditSheet>` opened by an inline `[Edit]` button per row. Reuses the radix-ui `Sheet` primitive established by Phase 6-3's `<WatchlistEntrySheet>`.

Cancel button on the sheet doesn't trigger ConfirmDialog — notes/date changes are minor edits and the dirty-cancel pattern from KidForm is overkill for two optional fields.

### D7: New `useUpdateEnrollment` hook (broader); existing hooks unchanged

`useUpdateEnrollment` PATCHes any combination of `{status, notes, enrolled_at}`. Optimistic update over `['kids', kidId, 'enrollments']` cache; rollback on error.

`onSettled` invalidates THREE caches:
- `['kids', kidId, 'enrollments']` (the row list)
- `['kids', kidId, 'calendar']` (calendar blocks may change)
- `['matches']` prefix (rematch may change scores; covers both `['matches', kidId]` and `['matches', 'all', ...]`)

Existing `useCancelEnrollment` and `useEnrollOffering` are NOT refactored. The calendar overlay keeps using its narrow hook; the enrollments page uses the broader hook. A future polish phase can collapse if it bites.

### D8: No DELETE-from-history UI in v1

Backend `DELETE /api/enrollments/{id}` exists but isn't surfaced. Cancellation via dropdown preserves history (`status=cancelled` row stays in the History disclosure). Permanent removal is power-user territory; if it bites, a future phase adds an inline `Remove` button + ConfirmDialog.

### D9: Status dropdown allows any transition

The backend permits any `EnrollmentStatus` → any `EnrollmentStatus`. The materializer correctly handles `cancelled → enrolled` (re-creates block) and `enrolled → completed` (removes block). No client-side restriction on which transitions are exposed in the dropdown — all 5 values are always selectable.

This matches casual household usage: occasional updates, rare mistakes that can be undone with one more dropdown change.

### D10: Tighten `EnrollmentCreate/Patch/Out.status` to `EnrollmentStatus` enum (backend)

`enrollments_schemas.py` currently types `status: str` (string). The dropdown PATCH sends a literal from `EnrollmentStatus`; loose `str` would allow typos to silently land in the DB. Tighten all three schemas to `status: EnrollmentStatus | None` (Patch) / `status: EnrollmentStatus = EnrollmentStatus.interested` (Create) / `status: EnrollmentStatus` (Out). Also tighten the `enrollment_status: str` query param on `list_enrollments` to `EnrollmentStatus | None`.

Frontend types follow: `EnrollmentStatus` is exported as a string-literal union from `frontend/src/lib/types.ts`. Pydantic serializes the enum as its `.value` (string) on the wire, so the frontend gets the same string it sent.

### D11: Notes-only PATCH still triggers materializer + rematch

The current `patch_enrollment` always calls `apply_enrollment_block` + `rematch_kid` on every PATCH, including notes-only edits. The materializer is idempotent (running it after a notes change re-applies the same block — no DB churn beyond the read). `rematch_kid` is the heavier call but fast for a single household.

We accept this v1 cost. If notes editing becomes frequent and rematch is sluggish, a future optimization can short-circuit when only `notes` changed. Out of scope for this PR.

### D12: Extract `<OfferingScheduleLine>` shared component

The "site_name · starts in N days · Wed 5–6pm" line is duplicated across `<MatchCard>` (Phase 5a), `<OfferingRow>` (Phase 7-2), and now `<EnrollmentRow>`. Extract to `frontend/src/components/common/OfferingScheduleLine.tsx`:

```tsx
interface Props {
  offering: OfferingSummary;
  showRegOpens?: boolean;  // MatchCard wants reg-opens; OfferingRow + EnrollmentRow don't
}
```

Then update all three call sites to use it. The new component encapsulates the formatter and unifies the visual; future tweaks land once.

### D13: `useUpdateEnrollment` pending state is per-row via component state

`useMutation` exposes one `isPending` per hook instance. With many rows sharing one hook, the spec's "select disabled while pending for that row" needs a per-row signal.

**Decision:** the `EnrollmentsList` page tracks a single `pendingEnrollmentId: number | null` in React state. Each row receives `isPending={pendingEnrollmentId === row.id}` as a prop. The list-level mutation onMutate sets it; onSettled clears it. This avoids the alternative of "one hook instance per row" (which would multiply React Query subscriptions for no benefit) and keeps the typing simple.

## Architecture

### Routes

| Route | Component | Purpose |
|---|---|---|
| `/kids/$id/enrollments` (new) | `EnrollmentsList` | Per-kid enrollments list |

### Components

```
EnrollmentsList (route page)
├── KidTabs (existing)
├── header (h1 with kid name)
├── Active section
│   └── EnrollmentRow × N
│       ├── status <select>
│       ├── 🚫 Blocks calendar pill (if status=enrolled)
│       ├── [Edit] button → opens EnrollmentEditSheet
│       └── (mute / delete affordances NOT included)
├── <details> History disclosure
│   └── EnrollmentRow × N (same component, just history rows)
└── EnrollmentEditSheet (mounted at the page level; controlled via `editing` state)
```

### Hooks

Add to `frontend/src/lib/queries.ts`:

```ts
export function useKidEnrollments(kidId: number) {
  return useQuery({
    queryKey: ['kids', kidId, 'enrollments'],
    queryFn: () => api.get<Enrollment[]>(`/api/enrollments?kid_id=${kidId}`),
    enabled: Number.isFinite(kidId) && kidId > 0,
  });
}
```

Add to `frontend/src/lib/mutations.ts`:

```ts
interface UpdateEnrollmentInput {
  enrollmentId: number;
  kidId: number;       // for cache invalidation; not sent in body
  patch: {
    status?: EnrollmentStatus;
    notes?: string | null;
    enrolled_at?: string | null;  // ISO datetime string
  };
}

export function useUpdateEnrollment() {
  const qc = useQueryClient();
  type Ctx = { snapshot: Enrollment[] | undefined };
  return useMutation<Enrollment, Error, UpdateEnrollmentInput, Ctx>({
    mutationFn: ({ enrollmentId, patch }) =>
      api.patch<Enrollment>(`/api/enrollments/${enrollmentId}`, patch),
    onMutate: async ({ enrollmentId, kidId, patch }) => {
      const key = ['kids', kidId, 'enrollments'];
      await qc.cancelQueries({ queryKey: key });
      const snapshot = qc.getQueryData<Enrollment[]>(key);
      if (snapshot) {
        qc.setQueryData<Enrollment[]>(
          key,
          snapshot.map((e) => (e.id === enrollmentId ? { ...e, ...patch } : e)),
        );
      }
      return { snapshot };
    },
    onError: (_err, { kidId }, ctx) => {
      if (ctx?.snapshot) qc.setQueryData(['kids', kidId, 'enrollments'], ctx.snapshot);
    },
    onSettled: async (_d, _e, { kidId }) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['kids', kidId, 'enrollments'] }),
        qc.invalidateQueries({ queryKey: ['kids', kidId, 'calendar'] }),
        qc.invalidateQueries({ queryKey: ['matches'] }),
      ]);
    },
  });
}
```

### Files

**Modify — backend:**
- `src/yas/web/routes/enrollments_schemas.py` — add `offering: OfferingSummary` to `EnrollmentOut` (import from `matches_schemas.py` — one-directional, no cycle). Tighten `status: str` → `status: EnrollmentStatus` on `EnrollmentOut`, `status: EnrollmentStatus = EnrollmentStatus.interested` on `EnrollmentCreate`, `status: EnrollmentStatus | None = None` on `EnrollmentPatch` (per D10).
- `src/yas/web/routes/enrollments.py` — `list_enrollments` and the singleton `get_enrollment` / `create_enrollment` / `patch_enrollment` join Offering + Site (and Location for lat/lon). Build the offering dict the same way `matches.py` does. Tighten the `enrollment_status: str` query param on `list_enrollments` to `EnrollmentStatus | None` per D10.
- `tests/integration/test_api_enrollments.py` — extend with one assertion that `EnrollmentOut.offering` is populated. Existing tests should keep passing under the tightened enum types (they pass valid string values).

**Create — frontend:**
- `frontend/src/routes/kids.$id.enrollments.tsx` — thin route shell.
- `frontend/src/components/enrollments/EnrollmentsList.tsx` + `.test.tsx`
- `frontend/src/components/enrollments/EnrollmentRow.tsx` + `.test.tsx`
- `frontend/src/components/enrollments/EnrollmentEditSheet.tsx` + `.test.tsx`
- `frontend/src/components/common/OfferingScheduleLine.tsx` (per D12) — small shared formatter; covered by existing call-site tests, no dedicated test file in this PR.

**Modify — frontend:**
- `frontend/src/components/layout/KidTabs.tsx` — add Enrollments tab.
- `frontend/src/lib/queries.ts` — add `useKidEnrollments`.
- `frontend/src/lib/mutations.ts` — add `useUpdateEnrollment`.
- `frontend/src/lib/types.ts` — **add** `Enrollment` interface (does not currently exist) with `offering: OfferingSummary`; add `EnrollmentStatus` string-literal union (`'interested' | 'enrolled' | 'waitlisted' | 'completed' | 'cancelled'`).
- `frontend/src/test/handlers.ts` — verify default `/api/enrollments` GET handler returns the new `offering` field.
- `frontend/src/components/matches/MatchCard.tsx` — replace inline schedule formatter with `<OfferingScheduleLine showRegOpens />` per D12.
- `frontend/src/components/offerings/OfferingRow.tsx` — replace inline schedule formatter with `<OfferingScheduleLine />` per D12.
- `frontend/src/routeTree.gen.ts` — regenerated.

**No new dependencies.**

## Layout details

### Row layout (`<EnrollmentRow>`)

```
┌────────────────────────────────────────────────────────────┐
│ T-Ball Spring 2026   [Status: enrolled ▾]   🚫 Blocks      │
│ Lil Sluggers · starts Jun 1 · Wed 5–6pm                    │
│ Enrolled May 12 · Notes: "Coach Mike, field 3"  [Edit]     │
└────────────────────────────────────────────────────────────┘
```

- **Top line (flex):** offering.name (`flex-1`) | status `<select>` | `🚫 Blocks calendar` pill if status=`enrolled`.
- **Second line (text-sm muted-foreground):** site_name + start_date (relDate) + days/times. Reuse the offering line shape from `<OfferingRow>` and `<MatchCard>`.
- **Third line (text-xs muted-foreground, flex):** `Enrolled <relDate(enrolled_at)>` if enrolled_at non-null + `· Notes: "<notes>"` if notes non-null + `[Edit]` button right-aligned (`ml-auto`).
- Pill is a `<Link>` to `/kids/$kidId/calendar` with `aria-label="View block on calendar"` for screen readers.
- Status `<select>` width is content-based (~120px) with all 5 EnrollmentStatus options.
- `<select>` `disabled` while `useUpdateEnrollment.isPending` for that row.

### Edit sheet (`<EnrollmentEditSheet>`)

```
┌──────────────────────────────────────┐
│ Edit enrollment                      │
├──────────────────────────────────────┤
│ Notes:                               │
│ ┌──────────────────────────────────┐ │
│ │ Coach Mike, field 3              │ │
│ │                                  │ │
│ └──────────────────────────────────┘ │
│                                      │
│ Enrolled at: [2026-05-12___]  [×]    │
│                                      │
│       [Cancel]   [Save]              │
└──────────────────────────────────────┘
```

- Uses radix-ui `Sheet` (right-side drawer); see `<WatchlistEntrySheet>` for the canonical wiring.
- Form: TanStack Form + zod schema with `notes: z.string().max(500).nullable()` and `enrolled_at: z.string().datetime().nullable()`.
- "Edit" button on the row passes the enrollment to the sheet via React state.
- Save → `useUpdateEnrollment.mutateAsync({ enrollmentId, kidId, patch: { notes, enrolled_at } })`. On success, sheet closes.
- Cancel just closes (no ConfirmDialog).

### Empty states

- No enrollments at all: `<EmptyState>No enrollments yet. Sign up via <Link to="/kids/$id/matches">Matches</Link>.</EmptyState>`
- No active enrollments but history exists: small inline note in the Active section, "No active enrollments. Past enrollments below."
- Loading: `<Skeleton className="h-32 w-full" />`
- Error: `<ErrorBanner message="Failed to load enrollments" onRetry={() => refetch()} />`

### Tab integration

`KidTabs.tsx` adds a 4th tab. Order: **Matches | Watchlist | Enrollments | Calendar**. The label "Enrollments" with `to: '/kids/$id/enrollments'`. The active-tab regex (`loc.pathname.endsWith('/enrollments')`) follows the existing pattern.

## Data flow

### Page load
```
useKidEnrollments(kidId)
  → GET /api/enrollments?kid_id=N
  → Enrollment[] with embedded .offering
Group client-side:
  active = enrollments.filter(e => ['interested','enrolled','waitlisted'].includes(e.status))
  history = enrollments.filter(e => ['completed','cancelled'].includes(e.status))
Sort each by created_at desc.
Render Active section + History disclosure.
```

### Status transition
```
User changes <select> from 'interested' to 'enrolled'
  → useUpdateEnrollment.mutateAsync({enrollmentId, kidId, patch: {status: 'enrolled'}})
  → optimistic: cache updates immediately; row re-renders in same Active section (no group change since both are in Active)
  → backend PATCH → applies enrollment block + rematches kid
  → onSettled: invalidate enrollments + calendar + matches caches
```

If the new status crosses the active/history boundary (e.g. `enrolled → completed`), the row visually moves on next render (due to client-side filter). No special handling needed — the status filter in `EnrollmentsList` re-runs.

### Edit notes/enrolled_at
```
User clicks [Edit] on row
  → EnrollmentEditSheet opens, pre-populated
User types in notes field, picks new date, clicks Save
  → useUpdateEnrollment.mutateAsync({enrollmentId, kidId, patch: {notes, enrolled_at}})
  → optimistic: row updates immediately; sheet closes
  → backend PATCH → materializer fires (idempotent if status unchanged), rematch
```

## Testing

**Frontend test count target:** ~15 new tests, raising 237 → ~252.
**Backend:** +1 test, raising 592 → 593.

### Backend (`tests/integration/test_api_enrollments.py`)
1. New test `test_enrollment_includes_offering_summary`: create kid + offering with location + enrollment; GET; assert `enrollment.offering.name`, `offering.site_name`, `offering.location_lat` are populated.

### Frontend `mutations.test.tsx` extensions (~2 tests)
1. `useUpdateEnrollment` happy path: PATCH `{status: 'enrolled'}` updates cache optimistically; assertion on captured request body.
2. `useUpdateEnrollment` rolls back on 500.

### `EnrollmentRow.test.tsx` (~5 tests)
1. Renders offering.name + site_name + status `<select>` with current status + offering schedule line.
2. Status dropdown change → fires `useUpdateEnrollment` with `{status: <new>}` (capture body).
3. `🚫 Blocks calendar` pill present when status=`enrolled`; absent when status=`cancelled`.
4. Pill is a `<Link>` to `/kids/$kidId/calendar` (assert via `getByRole('link', {name: /blocks calendar/i})` and `closest('a').getAttribute('href')`).
5. `[Edit]` button click invokes `onEdit(enrollment)` callback (sheet ownership lives in parent).

### `EnrollmentEditSheet.test.tsx` (~3 tests)
1. Pre-populates from passed-in enrollment data (notes textarea + enrolled_at date input).
2. Save click PATCHes `{notes: <new>, enrolled_at: <new>}` (capture body).
3. Cancel button closes sheet without firing PATCH.

### `EnrollmentsList.test.tsx` (~4 tests)
1. Renders Active section with rows where status ∈ active.
2. History section behind `<details>`; rows hidden by default.
3. Empty state: no enrollments → "No enrollments yet" with link to Matches.
4. Filter logic: enrollment with status=`completed` appears in History; status=`waitlisted` in Active.

### Manual smoke (master §7 page #7 verification)

After implementation:
1. Open `/kids/$id` → click "Enrollments" tab → empty state with link to Matches.
2. Open `/kids/$id/matches` → enroll in an offering via the existing match overlay.
3. Return to Enrollments tab → row appears in Active with status=`enrolled` + `🚫 Blocks calendar` pill.
4. Click the pill → lands on `/kids/$id/calendar` showing the linked block.
5. Back to Enrollments → change status to `completed` via dropdown → row moves to History (after disclosure expand). Block disappears from calendar.
6. Click `[Edit]` on the row → edit notes → Save → row updates with new notes.
7. Verify `useKidEnrollments` cache stays in sync with backend after each mutation.

## Acceptance criteria

- ✅ New `/kids/$id/enrollments` route accessible from KidTabs (4th tab).
- ✅ Active section visible by default; History collapsed under disclosure.
- ✅ Status dropdown PATCHes immediately with optimistic update + rollback on error.
- ✅ `🚫 Blocks calendar` pill on enrolled rows links to `/kids/$id/calendar`.
- ✅ `[Edit]` button opens `<EnrollmentEditSheet>` with notes + enrolled_at editable.
- ✅ Empty / loading / error states render the right copy.
- ✅ Backend `EnrollmentOut.offering` populated; frontend types match.
- ✅ Backend gates clean; ~593 tests passing.
- ✅ Frontend gates clean; ~252 tests passing.

## Risks

- **`useUpdateEnrollment` cache invalidation breadth.** The hook invalidates `['matches']` (broad prefix) covering both per-kid and cross-kid match caches. Slightly over-invalidates but is safer than under-invalidating; the cost is one extra refetch on the offerings browser when an enrollment changes. Acceptable.
- **Existing `useCancelEnrollment` overlap.** The narrow hook stays in `mutations.ts` for the calendar overlay; the new broad hook is for the enrollments page. Both are correct; future refactor can collapse if maintenance feels heavy.
- **Backend OfferingSummary location join.** The same join introduced in Phase 7-2 (`outerjoin(Location, Location.id == Offering.location_id)`) is needed in `enrollments.py`. Implementer must port the same pattern verbatim. Risk of subtle drift between matches.py and enrollments.py.
- **Status dropdown immediate PATCH.** A click-and-hold or accidental scroll-on-mobile could trigger an unintended PATCH. Mitigation: native `<select>` requires explicit selection; no chance of mis-fire on desktop. Acceptable v1 risk.
- **`onSettled` invalidates `['kids', kidId, 'calendar']` AND `['matches']` AND `['kids', kidId, 'enrollments']`** — three queries refetch on each PATCH. With small datasets this is fine; bigger ones could feel sluggish. v1 acceptable.

## Out of scope (explicit non-goals)

- Cross-kid `/enrollments` page.
- DELETE-from-history button.
- Bulk multi-select status changes.
- Inline notes/enrolled_at editing on the row.
- Filter chips beyond Active/History grouping.
- Export to CSV / iCal.
- Refactor of existing `useCancelEnrollment` / `useEnrollOffering` hooks.
- Custom transition validation (cancelled → interested is allowed).
- Batch enrollment from offerings browser.

## After this lands

Master §7 page status:
- 7 of 9 met (after Phase 7-2)
- **8 of 9 met** (after this) — page #7 Enrollments closed.
- Remaining: page #3 combined calendar (Phase 8-1), page #8 Alerts outbox/preview (Phase 7-4).
