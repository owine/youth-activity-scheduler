# Phase 5c-1 — Per-kid Calendar View (Design)

**Status:** Approved (brainstorming complete 2026-04-29).
**Predecessor:** Phase 5b-1b (`docs/superpowers/specs/2026-04-29-phase-5b-1b-alert-close-frontend-design.md`) — established the canonical TanStack Query mutation pattern with optimistic updates and rollback. This slice copies that pattern.
**Master design:** `docs/superpowers/specs/2026-04-21-youth-activity-scheduler-design.md` §10 — the v1 terminal-state criterion explicitly calls out: *"Calendar page renders a week view containing offerings, enrollments, and unavailability for a single kid within 1s on a realistic dataset."*
**Succeeds into:** Phase 5c-2 (calendar with match overlay + click-to-enroll), and eventually multi-kid combined view. Both are out of scope here.

## 1. Purpose and scope

Add a per-kid calendar view that renders the kid's enrollments and unavailability blocks on either a week or month grid. Click an event → popover with details + a single mutation action (cancel enrollment, delete unavailability block). One new aggregated backend endpoint feeds the calendar; mutations reuse existing routes.

This is the v1 terminal-state criterion's calendar deliverable, scoped narrowly: *enrolled* offerings (not all matches), *single kid* (not multi-kid overlay), week + month views with toggle. Match overlay and click-to-enroll are deferred to 5c-2 to keep this slice reviewable.

### 1.1 In scope

- **Backend endpoint** `GET /api/kids/{kid_id}/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD` returning a flat list of dated occurrences (enrollments and unavailability blocks) for the date range.
- **Server-side recurring expansion**: a new pure-function helper `src/yas/calendar/occurrences.py` expands recurring patterns (`days_of_week + time_start/end + date_start/end`) into concrete date occurrences within `[from, to)`. The codebase has no existing expansion utility — matching code only checks `days_of_week` for set membership.
- **Frontend route** `/kids/$id/calendar` using TanStack Router, fed by a new `useKidCalendar({ kidId, from, to })` query hook.
- **`CalendarView` component** wrapping `react-big-calendar` (~25 KB) with project-specific defaults: `react-big-calendar` is the new dep; no other libraries added.
- **Week + month views** with a controlled toggle. Default: week. Time range on week: 6:00–22:00.
- **Event popover** with details + a single action button. Read-only popover for unavailability sourced from a still-active enrollment (the action there belongs on the enrollment popover, not the linked block).
- **Two new mutation hooks** in `frontend/src/lib/mutations.ts`: `useCancelEnrollment`, `useDeleteUnavailability`. Both follow the canonical 5b-1b optimistic + rollback pattern.
- **Tests** at three levels: pure-function expansion tests, integration tests for the new endpoint, frontend tests for the calendar component and mutations.

### 1.2 Out of scope

- **Match overlay** (rendering offerings the kid scored well on but isn't enrolled in). Deferred to 5c-2.
- **Click-to-enroll from calendar.** Same — 5c-2.
- **Multi-kid combined view.** Deferred.
- **Drag-and-drop reschedule.** Out of scope; not a v1 terminal criterion.
- **ICS export / import.** Master design §1 lists this as v1 out of scope.
- **Holiday calendar integration.** A school unavailability block today renders every weekday in its date range; spring break is a separate `manual`/`custom` block. A real holiday-aware school calendar is a future slice.
- **Edit-in-place from the popover.** Popover is read + cancel/delete only. Full edit lives elsewhere.
- **Dynamic time-range clamp** on the week grid. Hard-coded 6:00–22:00 in v1; lift if a real event ever falls outside.
- **Pagination / infinite scroll.** Calendar always queries a finite `[from, to)` range derived from the visible view.

## 2. API

### 2.1 New endpoint

`GET /api/kids/{kid_id}/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD`

**Path params:**
- `kid_id` (int) — must exist and belong to the household. 404 if not found.

**Query params:**
- `from` (date, required, inclusive) — start of the date range.
- `to` (date, required, exclusive) — end of the date range.
- 422 if `from >= to`.
- 422 if the range is unreasonably large (cap at 90 days, returns 422 with explanation; the frontend never requests more than ~6 weeks).

**Response shape:**

```json
{
  "kid_id": 1,
  "from": "2026-04-27",
  "to": "2026-05-04",
  "events": [
    {
      "id": "enrollment:42:2026-04-29",
      "kind": "enrollment",
      "date": "2026-04-29",
      "time_start": "16:00:00",
      "time_end": "17:00:00",
      "all_day": false,
      "title": "Lil Sluggers T-Ball",
      "enrollment_id": 42,
      "offering_id": 7,
      "location_id": 3,
      "status": "enrolled"
    },
    {
      "id": "unavailability:11:2026-04-29",
      "kind": "unavailability",
      "date": "2026-04-29",
      "time_start": "08:30:00",
      "time_end": "15:00:00",
      "all_day": false,
      "title": "School",
      "block_id": 11,
      "source": "school",
      "from_enrollment_id": null
    }
  ]
}
```

**Event id:** Composite `kind:source-row-id:date` so react-big-calendar's per-event keys are stable across renders, and so the popover handler can resolve back to the source row + date.

**all_day flag:** Set when `time_start IS NULL` and `time_end IS NULL` on the source row.

**from_enrollment_id:** Populated for unavailability blocks whose `source_enrollment_id` is set. The popover uses this to suppress the "Delete block" action on those blocks (the user should cancel the enrollment instead).

### 2.2 Existing endpoints used

- `PATCH /api/enrollments/{id}` with `{ status: "cancelled" }` — already exists, used by `useCancelEnrollment`.
- `DELETE /api/unavailability/{id}` — already exists, used by `useDeleteUnavailability`.

No backend mutation work in this slice beyond the new GET endpoint.

## 3. Server-side recurring expansion

The codebase has no existing recurring-expansion helper. New module:

```
src/yas/calendar/
  __init__.py
  occurrences.py        # pure functions, no DB
```

**Public surface:**

```python
def expand_recurring(
    *,
    days_of_week: list[str],   # e.g. ["mon", "wed", "fri"]
    time_start: time | None,
    time_end: time | None,
    date_start: date | None,    # inclusive lower bound (None = unbounded)
    date_end: date | None,      # inclusive upper bound (None = unbounded)
    range_from: date,           # inclusive
    range_to: date,             # exclusive
) -> Iterator[OccurrenceTuple]:
    """Yield (date, time_start, time_end, all_day) tuples for each
    weekday in `days_of_week` falling within the intersection of
    [range_from, range_to) and [date_start, date_end].

    Treats `time_start`/`time_end` both being None as an all-day event.
    """
```

The route handler calls `expand_recurring` once per source row (enrollment's joined offering + each active unavailability block) and tags the resulting occurrences with the right kind/ids.

The expansion is a pure function over date arithmetic — easy to unit-test exhaustively without a database.

## 4. Frontend

### 4.1 Dependency

Add `react-big-calendar` (exact patch pin in `frontend/package.json`). The library ships its own CSS (`react-big-calendar/lib/css/react-big-calendar.css`) — imported once at the route level so the bundle is tree-shakable for non-calendar pages.

`react-big-calendar`'s `dateFnsLocalizer` reuses our existing `date-fns` dep — no second date library.

### 4.2 Route

```
frontend/src/routes/kids.$id.calendar.tsx
```

Renders:
- A heading with the kid's name.
- A week/month toggle (controlled).
- A back/forward navigation pair.
- The `<CalendarView>`.

Uses the existing `useKid(id)` query for the kid name; uses a new `useKidCalendar({ kidId, from, to })` for events.

### 4.3 Components

Create:
- `frontend/src/components/calendar/CalendarView.tsx` — wraps `<Calendar>` from `react-big-calendar`. Accepts events, view, cursorDate, onView, onNavigate, onSelectEvent. Adds the project-specific event class names (enrollment vs unavailability) via `eventPropGetter`.
- `frontend/src/components/calendar/CalendarEventPopover.tsx` — renders details + action button. Inline `<ErrorBanner>` on mutation error. Closes itself on successful mutation.

The popover anchors via Radix's `Popover.Trigger` wrapped around react-big-calendar's event element. Selection state lives in the route (`selected: CalendarEvent | null`) to keep the popover controlled and testable.

### 4.4 Query hook

`frontend/src/lib/queries.ts` gains:

```ts
export function useKidCalendar({
  kidId,
  from,
  to,
}: {
  kidId: number;
  from: string;  // YYYY-MM-DD
  to: string;
}) {
  return useQuery({
    queryKey: ['kids', kidId, 'calendar', from, to],
    queryFn: () =>
      api.get<KidCalendarResponse>(
        `/api/kids/${kidId}/calendar?from=${from}&to=${to}`,
      ),
    enabled: Number.isFinite(kidId),
  });
}
```

Cache key prefix `['kids', kidId, 'calendar']` is what mutations invalidate — see §4.6.

### 4.5 Visible date range

The route computes `from`/`to` from the calendar's controlled `view + cursorDate`:
- Week view: `from = startOfWeek(cursor)`; `to = startOfWeek(cursor) + 7d`.
- Month view: `from = startOfMonth(cursor) - <leading days>`; `to = endOfMonth(cursor) + <trailing days>`. (Includes the surrounding partial weeks the month grid renders.)

A small lookback buffer (3 days each side) is added so navigating one cell doesn't always trigger a refetch. The cache key tracks the actual `from`/`to`, so adjacent ranges are independently cached.

### 4.6 Mutations

`frontend/src/lib/mutations.ts` extended with two hooks. Both follow the canonical 5b-1b shape: `onMutate` cancels in-flight queries, snapshots all matching caches, applies optimistic update; `onError` restores from snapshots; `onSettled` awaits invalidation.

```ts
export function useCancelEnrollment() { /* PATCH /api/enrollments/{id} { status: 'cancelled' } */ }
export function useDeleteUnavailability() { /* DELETE /api/unavailability/{id} */ }
```

**Optimistic surgery details:**
- `useCancelEnrollment`: removes from cached calendar all events whose `kind == 'enrollment' && enrollment_id == X`. Also removes any unavailability events with `from_enrollment_id == X` (the backend cancels the linked block; we mirror it in the cache so the UI doesn't briefly show a now-orphaned block).
- `useDeleteUnavailability`: removes events where `kind == 'unavailability' && block_id == X`.
- Both invalidate the prefix `['kids', kidId, 'calendar']`. The mutation's input includes `kidId` so the snapshot loop can be precise (no need to walk every kid's cache).

### 4.7 Time range and styling

- Week view: `min={6:00}`, `max={22:00}`. Hard-coded.
- Enrollment events: `bg-primary text-primary-foreground` (or theme equivalent).
- Unavailability events: `bg-muted text-muted-foreground`.
- All-day events render in react-big-calendar's all-day strip on the week view, and span the cell in the month view (library default).
- Overlapping events at the same time render side-by-side in week view (library default).
- The library's CSS is imported at the route level; we override the few classes that conflict with our Tailwind v4 theme via a small CSS module or `@layer` block in `globals.css`. (TBD during implementation; spec leaves the exact override list for the plan.)

## 5. Edge cases

- **Cancelled enrollment between fetch and click.** Mutation returns 404; rollback restores; banner shows. User refreshes.
- **Unavailability block tied to a still-active enrollment.** Popover suppresses the "Delete block" action and shows a hint: *"This block was created by your '{title}' enrollment. Cancel the enrollment to remove it."*
- **All-day event overlapping a timed event.** react-big-calendar handles natively (all-day strip + grid).
- **Empty calendar (no enrollments, no unavailability).** Calendar grid renders normally with zero events. No empty-state copy needed; the grid itself is the empty state.
- **Range > 90 days.** Backend returns 422; the frontend never requests more, so this is purely a backend defensive bound.
- **Recurring offering whose `date_end < range_from` or `date_start >= range_to`.** Returns no occurrences; the expansion helper handles this without iteration.
- **Block with `time_start IS NULL` and `time_end IS NOT NULL` (or vice versa).** Treated as malformed; expansion helper skips with a log warning. Existing data shouldn't have this shape (model allows it but UI never produces it).

## 6. Testing

Backend:
1. `tests/unit/test_calendar_occurrences.py` — pure-function tests for `expand_recurring`. Cases: weekly recurring within range; date_start/date_end clipping; range clipping; all-day; empty `days_of_week`; range_from == range_to.
2. `tests/integration/test_api_kids_calendar.py` — endpoint smoke + correctness:
   - 404 for unknown kid_id.
   - 422 for `from >= to` and for ranges > 90 days.
   - Returns enrollment occurrences with correct `enrollment_id`, `offering_id`, `status: 'enrolled'`.
   - Returns unavailability occurrences with `from_enrollment_id` populated for enrollment-linked blocks.
   - Cancelled enrollments are excluded.
   - Inactive blocks (`active=false`) are excluded.
   - Other kids' events are excluded.
   - Expansion correctness: a Mon/Wed/Fri offering in a Mon–Sun range returns exactly 3 occurrences with the correct dates and times.

Frontend:
3. `frontend/src/components/calendar/CalendarView.test.tsx` — events render; clicking an event opens the popover; week/month toggle reflects in the rendered grid (assert via library-rendered DOM).
4. `frontend/src/components/calendar/CalendarEventPopover.test.tsx` — renders enrollment details with "Cancel enrollment" button; renders unavailability details; suppresses delete on enrollment-linked blocks.
5. `frontend/src/lib/mutations.test.tsx` (extend) — `useCancelEnrollment` removes all enrollment + linked-block events optimistically; rolls back on 500. `useDeleteUnavailability` removes the matching block; rolls back.
6. MSW handlers in `frontend/src/test/handlers.ts`: `GET /api/kids/:id/calendar`, `PATCH /api/enrollments/:id`, `DELETE /api/unavailability/:id`.

Manual smoke (before merge):
- Navigate to `/kids/1/calendar`; see week view with school block + an enrolled offering.
- Click offering → popover with Cancel enrollment → click → row vanishes optimistically.
- Toggle to month view → cursor next month → events present.
- Click a school block (no `from_enrollment_id`) → Delete block; click → vanishes.
- Click an enrollment-linked block → no Delete button; helper text shown.

## 7. Open questions

None blocking. All six brainstorming decisions are recorded in §1–§4:

- **Q1** (events on calendar): enrollments + unavailability only. §1.1.
- **Q2** (single vs multi-kid): single-kid only. §1.1, 1.2.
- **Q3** (week vs month): both with toggle. §4.2, 4.3.
- **Q4** (click behavior): popover with Cancel enrollment / Delete block actions. §4.3.
- **Q5** (time range): fixed 6:00–22:00 in week view. §4.7.
- **Q6** (library): `react-big-calendar`. §4.1.

## 8. Exit criteria

Phase 5c-1 is complete when:

- The new endpoint is implemented, tested, and matches the response shape in §2.1.
- `expand_recurring` is implemented and exhaustively unit-tested.
- The frontend calendar route renders enrollments + unavailability for a kid; week and month toggle works; popover renders and dispatches the correct mutation.
- `useCancelEnrollment` and `useDeleteUnavailability` follow the canonical 5b-1b pattern (optimistic + rollback + awaited invalidation).
- All backend gates green (`pytest`, `ruff`, `mypy`).
- All frontend gates green (`vitest`, `tsc --noEmit`, ESLint, format check).
- Manual smoke: enrollment cancel → row vanishes; week/month toggle works; enrollment-linked block can't be deleted from the popover.
- v1 terminal-state calendar criterion satisfied: *"calendar page renders a week view containing offerings, enrollments, and unavailability for a single kid within 1s on a realistic dataset."* (We satisfy "offerings" via enrollments — the offering data is denormalized into each enrollment occurrence's `title`/`offering_id`.)
