# Phase 5c-2 — Calendar Match Overlay + Click-to-Enroll (Design)

**Status:** Approved (brainstorming complete 2026-04-29).
**Predecessor:** Phase 5c-1 (`docs/superpowers/specs/2026-04-29-phase-5c-1-kid-calendar-design.md`) — established the per-kid calendar route, the `expand_recurring` helper, the `CalendarView`/`CalendarEventPopover` components, and the canonical mutation pattern for cancel-enrollment / delete-unavailability.
**Master design:** `docs/superpowers/specs/2026-04-21-youth-activity-scheduler-design.md`.
**Succeeds into:** No immediate successor planned. Future possibilities (multi-kid combined view, watchlist on calendar, score-threshold control) are tracked as out of scope below.

## 1. Purpose and scope

Make the calendar a discovery surface, not just a viewer. When the user toggles "Show matches" on, the calendar overlays high-score offerings the kid isn't enrolled in. Click a match → popover with an "Enroll" button. Confirming creates an enrollment server-side, which (via existing `apply_enrollment_block` + `rematch_kid` plumbing) auto-creates the linked unavailability block and updates the match list.

This is what the master design called the discovery → action loop on the calendar.

### 1.1 In scope

- **Backend:** extend `GET /api/kids/{kid_id}/calendar` with `include_matches: bool = False`. When true, merge match occurrences (score ≥ 0.6) into the response as a third event kind, excluding offerings the kid already has any non-`cancelled` enrollment for.
- **Schema extension:** `CalendarEventOut` gains `kind="match"` plus `score: float | None` and `registration_url: str | None` (only populated for match events).
- **Frontend route:** new component-local "Show matches" toggle on the calendar header. Component-local state, not persisted, defaults to off.
- **Frontend query:** `useKidCalendar` accepts an `includeMatches` flag; cache key gains a `'with-matches' | 'no-matches'` discriminator at index 5.
- **Frontend styling:** match events render with a dashed outline and transparent background — visually subordinate to enrollments and unavailability.
- **Frontend popover:** `CalendarEventPopover` gains an "Enroll" branch for `kind === 'match'`, plus a "View details" external link when the match's offering has a `registration_url`.
- **New mutation:** `useEnrollOffering` follows the canonical 5b-1b/5c-1 optimistic + rollback pattern.
- **Tests:** backend integration coverage for the new flag; frontend tests for the new mutation, the styling branch, the popover Enroll action.

### 1.2 Out of scope

- **User-controllable score threshold.** Locked at 0.6. The existing `/kids/$id/matches` page remains the place to see the long tail at any score.
- **Status picker on Enroll.** v1 always sets `enrolled`. Marking as `interested` or `waitlisted` happens elsewhere.
- **Watchlist on calendar.** Separate concept; not surfaced here.
- **Bulk enroll / multi-select.** Single match, single click.
- **Drag a match to reschedule.** Offerings have fixed times.
- **Confirm dialog before enroll.** Symmetry with cancel (already destructive without confirm); the popover is the confirm step.
- **Persisted toggle state.** Component-local; resets on navigation.
- **Per-kid "ignore this match" affordance.** A future watchlist concept.
- **Match overlay on multi-kid combined view.** Multi-kid view itself is deferred.

## 2. API

### 2.1 Endpoint extension

`GET /api/kids/{kid_id}/calendar?from=&to=&include_matches=true`

Existing query params unchanged. New optional `include_matches: bool = False`.

When `include_matches=true`:
1. Pull `Match` rows for `kid_id` where `score >= _MATCH_THRESHOLD` (`0.6`), joined to `Offering`.
2. Exclude offerings the kid has any non-`cancelled` enrollment for. SQLAlchemy: `~Match.offering_id.in_(select(Enrollment.offering_id).where(Enrollment.kid_id == kid_id, Enrollment.status != 'cancelled'))`.
3. For each surviving match, run `expand_recurring` against the offering's recurring fields (`days_of_week`, `time_start`, `time_end`, `start_date`, `end_date`).
4. Tag each occurrence as `kind="match"` with `score`, `offering_id`, `registration_url`, `title=offering.name`.

When `include_matches=false` (default), behavior is unchanged from 5c-1.

### 2.2 Response shape extension

`CalendarEventOut` gains:

```python
class CalendarEventOut(BaseModel):
    # ...existing fields...
    kind: Literal["enrollment", "unavailability", "match"]   # extended union
    # match-only:
    score: float | None = None
    registration_url: str | None = None
```

The composite event id for matches is `match:{offering_id}:{date}` (no separate match-row id is needed in this codebase since matches are uniquely keyed by `(kid_id, offering_id)`).

Match events MUST populate `offering_id` (the join key for `useEnrollOffering`) and SHOULD populate `location_id` from the joined offering when set. Both reuse existing optional fields on `CalendarEventOut`.

### 2.3 Existing endpoints used

- `POST /api/enrollments` with `{ kid_id, offering_id, status: 'enrolled' }` — already exists. The route runs `apply_enrollment_block(s, enrollment.id)` then `rematch_kid(s, kid_id)`, so the linked unavailability block and updated match list appear server-side automatically.

No backend mutation work in this slice beyond the GET extension.

## 3. Server-side filter constants

```python
# src/yas/web/routes/kid_calendar.py
_MATCH_THRESHOLD: float = 0.6
```

Co-located with the existing `_MAX_RANGE_DAYS = 90`.

## 4. Frontend

### 4.1 Type changes

`frontend/src/lib/types.ts`:

```ts
export type CalendarEventKind = 'enrollment' | 'unavailability' | 'match';   // extended

export interface CalendarEvent {
  // ...existing fields...
  // match-only:
  score?: number | null;
  registration_url?: string | null;
}
```

### 4.2 Query hook

`useKidCalendar` accepts `includeMatches: boolean` (default `false`):

```ts
export function useKidCalendar({
  kidId,
  from,
  to,
  includeMatches = false,
}: {
  kidId: number;
  from: string;
  to: string;
  includeMatches?: boolean;
}) {
  return useQuery({
    queryKey: ['kids', kidId, 'calendar', from, to, includeMatches ? 'with-matches' : 'no-matches'],
    queryFn: () =>
      api.get<KidCalendarResponse>(
        `/api/kids/${kidId}/calendar?from=${from}&to=${to}${includeMatches ? '&include_matches=true' : ''}`,
      ),
    enabled: Number.isFinite(kidId) && !!from && !!to,
  });
}
```

The 6-segment cache key is independent from the no-matches variant — flipping the toggle does not invalidate or refetch the existing cached page.

The optimistic mutation pattern from 5c-1 already iterates all `['kids', kidId, 'calendar']` prefix-matching caches via `getQueriesData`, so existing mutations (cancel-enrollment, delete-unavailability) Just Work across the new variant. Same applies to the new `useEnrollOffering`.

### 4.3 Route + toggle

`frontend/src/routes/kids.$id.calendar.tsx` gains one new piece of state:

```tsx
const [includeMatches, setIncludeMatches] = useState(false);
const calendar = useKidCalendar({ kidId, from, to, includeMatches });
```

Toggle UI: a checkbox in the calendar header (left of the existing react-big-calendar toolbar):

```tsx
<label className="flex items-center gap-1 text-xs text-muted-foreground">
  <input
    type="checkbox"
    checked={includeMatches}
    onChange={(e) => setIncludeMatches(e.target.checked)}
  />
  Show matches
</label>
```

### 4.4 Match event styling

`frontend/src/components/calendar/calendar-overrides.css` gains:

```css
.rbc-event-match {
  background-color: transparent;
  color: hsl(var(--foreground));
  border: 1px dashed hsl(var(--primary));
}
```

`CalendarView.tsx`'s `eventPropGetter` extends to a three-way branch on `kind`:

```ts
className:
  resource.kind === 'enrollment'  ? 'rbc-event-enrollment'  :
  resource.kind === 'match'       ? 'rbc-event-match'       :
                                    'rbc-event-unavailability'
```

### 4.5 Popover behavior

`CalendarEventPopover.tsx` gains a `kind === 'match'` branch:

```
Match popover content:
─────────────────────
{event.title}
{Day} {time_start–time_end}
Score: {score.toFixed(2)}
[Enroll]   [View details ↗]   ← View details only when registration_url is set
```

Behavior:
- "Enroll" button dispatches `useEnrollOffering({ kidId, offeringId: event.offering_id })`.
- "View details" is an `<a target="_blank" rel="noopener noreferrer" href={event.registration_url}>` — opens in a new tab.
- Inline `<ErrorBanner>` on mutation failure (same plumbing as cancel/delete).
- On success, the popover closes via the existing `onSuccess: onClose` plumbing.
- Buttons disabled while mutation in-flight (`inFlight = cancel.isPending || del.isPending || enroll.isPending`).

### 4.6 Mutation: `useEnrollOffering`

`frontend/src/lib/mutations.ts` adds a third hook following the canonical pattern:

```ts
interface EnrollOfferingInput {
  kidId: number;
  offeringId: number;
}

export function useEnrollOffering() {
  const qc = useQueryClient();
  type Ctx = {
    snapshots: ReadonlyArray<readonly [QueryKey, KidCalendarResponse | undefined]>;
  };
  return useMutation<unknown, Error, EnrollOfferingInput, Ctx>({
    mutationFn: ({ kidId, offeringId }) =>
      api.post('/api/enrollments', {
        kid_id: kidId,
        offering_id: offeringId,
        status: 'enrolled',
      }),

    onMutate: async ({ kidId, offeringId }) => {
      await qc.cancelQueries({ queryKey: ['kids', kidId, 'calendar'] });
      const snapshots = qc.getQueriesData<KidCalendarResponse>({
        queryKey: ['kids', kidId, 'calendar'],
      });
      for (const [key, data] of snapshots) {
        if (!data) continue;
        const filtered = data.events.filter(
          (e) => !(e.kind === 'match' && e.offering_id === offeringId),
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
```

Optimistic-only: removes the match. The new enrollment occurrences and the new linked unavailability block come from the server invalidate (rather than synthesizing them client-side, which would require knowing the just-created enrollment.id and block.id ahead of the response).

## 5. Edge cases

- **Match for an offering with empty `days_of_week`** → `expand_recurring` returns nothing, no event renders.
- **Score exactly 0.6** → included (threshold is `>=`).
- **Already-`interested` enrollment** → excluded from match overlay (status filter is `!= 'cancelled'`). User expectation: don't surface as a "match" something already shortlisted.
- **Toggle off "Show matches" while a match popover is open** → popover stays open (controlled by `selected` state, not by visible event list). Closing it clears selection cleanly.
- **Concurrent: user clicks Enroll twice quickly** → button disabled while in-flight; second click ignored.
- **Server returns 4xx/5xx on `POST /api/enrollments`** → rollback restores the match event; banner shows. Retry available.
- **Existing tests calling without `include_matches`** → unchanged behavior; no match events appear.
- **Race: cancel-enrollment in flight, user toggles "Show matches" on** → cancel mutation's optimistic update applies to all variants via the `['kids', kidId, 'calendar']` prefix; toggle on triggers a fresh fetch on the new key. Both consistent with the canonical pattern.
- **Toggle on, kid has zero matches** → server returns the same shape with no `kind="match"` events. Toggle remains visible and active; calendar simply has no extra overlay. We do NOT hide or disable the toggle based on emptiness — that would require an extra request just to gate the toggle.

## 6. Testing

Backend:
1. `tests/integration/test_api_kids_calendar.py` (extend) —
   - `?include_matches=true` returns match events with correct `kind`, `score`, `offering_id`.
   - Score threshold: a match at `0.59` is excluded; a match at `0.6` is included; a match at `0.61` is included.
   - Excludes offerings the kid is already enrolled in (`status='enrolled'`).
   - Excludes offerings the kid is interested in (`status='interested'`).
   - Excludes offerings the kid is waitlisted for (`status='waitlisted'`).
   - Includes offerings only cancelled (`status='cancelled'`) — the kid is no longer committed.
   - When the flag is absent, response shape is unchanged (no match events).

Frontend:
2. `frontend/src/lib/mutations.test.tsx` (extend) — `useEnrollOffering`:
   - Removes match events with the matching `offering_id` from cached calendar variants.
   - Rolls back on 500.
   - Survives cache that contains a `with-matches` AND `no-matches` variant simultaneously (no-matches variant has no match events to remove; should not crash).
3. `frontend/src/components/calendar/CalendarView.test.tsx` (extend) — match events render with `rbc-event-match` class.
4. `frontend/src/components/calendar/CalendarEventPopover.test.tsx` (extend) — match event renders Enroll button with score; clicking dispatches `useEnrollOffering`; success closes popover.
5. `frontend/src/test/handlers.ts` (extend) — MSW handlers: extend `GET /api/kids/:id/calendar` to honor the `include_matches` query param (return at least one match event when set); add `POST /api/enrollments` returning a created Enrollment.

Manual smoke (before merge):
- Navigate to `/kids/1/calendar`. Tick "Show matches" — dashed-outline events appear if any matches scored ≥ 0.6 exist.
- Click a match → popover with Enroll + (optional) View details external link.
- Click Enroll → match disappears optimistically; new enrollment + linked unavailability block appear after server invalidate.
- Tick the box off → match overlay vanishes, base events still present.

## 7. Open questions

None blocking. All four brainstorming decisions are recorded:

- **Q1** (overlay vs side panel): grid overlay. §4.4.
- **Q2** (threshold): fixed 0.6. §3.
- **Q3** (visual treatment): dashed outline, transparent background. §4.4.
- **Q4** (toggle semantics): default off, opt-in component-local toggle. §4.3.

## 8. Exit criteria

Phase 5c-2 is complete when:

- The calendar endpoint accepts `include_matches=true` and returns match occurrences within the date range, score-filtered and enrollment-excluded.
- `CalendarEventOut` schema gains `kind="match"` + `score` + `registration_url`.
- Frontend renders match events with a dashed outline; "Show matches" toggle works.
- `CalendarEventPopover` shows Enroll for matches; click dispatches `useEnrollOffering`.
- `useEnrollOffering` follows the canonical 5b-1b/5c-1 pattern (optimistic + rollback + awaited invalidate).
- All backend gates green (`pytest`, `ruff`, `mypy`).
- All frontend gates green (`vitest`, `tsc --noEmit`, ESLint).
- Manual smoke: enroll → match disappears optimistically; new enrollment + linked block appear after server confirms; toggle off hides match overlay.
