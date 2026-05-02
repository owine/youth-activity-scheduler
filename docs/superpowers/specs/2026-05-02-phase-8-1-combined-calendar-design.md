# Phase 8-1: Combined Multi-Kid Calendar — Design

**Date:** 2026-05-02
**Status:** Approved
**Roadmap:** `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md` §6 Phase 8-1
**Master:** §7 page #3 ("Calendar (per-kid + combined)")

## 1. Problem

Master §7 page #3 calls for both per-kid and combined calendar views. Per-kid (`/kids/$id/calendar`) shipped in 5c-1 + 5c-2; the combined view was deferred. A single-household scheduler with 2–4 kids needs a "what's everyone up to this week" view — overlapping enrollments, school blocks, and (optionally) matches in one place.

## 2. Approach: frontend-only, parallel client fetches

The existing `GET /api/kids/{kid_id}/calendar?from&to&include_matches` endpoint already returns everything needed. The combined view fans out to it once per active kid in parallel and merges client-side.

**Why not a new combined endpoint?** Considered. Rejected because (a) for a single household with 2–4 kids the network savings (1 RTT vs N) are immaterial; (b) it would duplicate the per-kid endpoint's filtering/joining logic; (c) every additional backend surface costs schema/route/tests. The existing endpoint is already paginated by date range, so the parallel-fan-out scales fine.

**Why a new top-level route, not a toggle on the existing per-kid page?** The combined view isn't tied to a specific kid in the URL — putting it under `/kids/$id/calendar` would break deep-linking and make the route URL semantically lie. New top-level `/calendar` matches master §7's framing as two distinct pages.

## 3. Components and files

### Create

| File | Responsibility |
|---|---|
| `frontend/src/routes/calendar.tsx` | Route + state (date, view, filters), URL-search-param plumbing, fan-out queries |
| `frontend/src/components/calendar/CombinedCalendarFilters.tsx` | Kid checkboxes (with color swatches) + event-type checkboxes + Clear button |
| `frontend/src/lib/calendarColors.ts` | 8-color palette + stable `colorForKid(kidId)` indexer |
| `frontend/src/lib/combinedCalendar.ts` | Pure `mergeKidCalendars(responses, kidsById, filters): CombinedCalendarEvent[]` |
| `frontend/src/lib/calendarRange.ts` | `rangeFor(view, cursor)` + `BUFFER_DAYS` constant — extracted from per-kid route so combined route imports the same helper |

### Modify

| File | Change |
|---|---|
| `frontend/src/components/layout/TopBar.tsx` (+ test) | Add `Calendar` link with `CalendarDays` icon between Kids and Offerings |
| `frontend/src/components/calendar/CalendarView.tsx` | Accept an optional `eventStyle?(event): { className?: string; style?: React.CSSProperties }` prop. **Composition rule:** the existing kind-based `className` (e.g. `rbc-event-enrollment`) is preserved; `eventStyle`'s `className` is concatenated, and `style` is shallow-merged on top. This way kid-color overlays work without losing kind styling from `calendar-overrides.css`. |
| `frontend/src/components/calendar/CalendarEventPopover.tsx` | No code change — already takes a `kidId` prop. Combined route resolves it from `event.kid_id` (see D3a) when wiring the click handler. |
| `frontend/src/routes/kids.$id.calendar.tsx` | Replace inline `rangeFor` / `BUFFER_DAYS` with import from `lib/calendarRange.ts`. Pure refactor, no behavior change. |
| `frontend/src/lib/types.ts` | Add `CombinedCalendarEvent extends CalendarEvent { kid_id: number }` and `CombinedCalendarFilterState { kidIds, types, includeMatches }` |

### Tests (create)

| File | Coverage |
|---|---|
| `frontend/src/lib/calendarColors.test.ts` | Stable assignment by `kid_id`, no collisions inside palette length, palette length sanity |
| `frontend/src/lib/combinedCalendar.test.ts` | Merge ordering, kid filter, type filter, `include_matches=false` excludes match events |
| `frontend/src/components/calendar/CombinedCalendarFilters.test.tsx` | Render, toggle kid checkbox, toggle type checkbox, Clear-filters button visibility |
| `frontend/src/routes/-calendar.test.tsx` | Renders skeleton then events; filter change updates URL; empty states (0 active kids, all unchecked) |

## 4. Decisions

**D1. Color by kid, not by event type.** In a combined view "whose event is this?" is the new question that justifies the page existing. Type already comes through in the title text and where the event sits (school blocks recur weekday-wide, matches start with "Match:"). Color encodes kid identity; type encodes nothing visually beyond the existing react-big-calendar default styling.

**D2. 8-color palette indexed by `kid.id % palette.length`.** Stable across renames, predictable in tests. Tailwind classes (`bg-blue-500`, `bg-emerald-500`, …) chosen for color-blind contrast (no red+green pair). 8 covers any realistic household size; document the wrap-around so >8 kids reuses colors but the page still works.

**D3. Title prefix `"{kid_name}: {original_title}"`** applied in the merge step. Raw `CalendarEvent.title` stays untouched in API responses; prefix is a render-layer concern only. Keeps deep-link to per-kid view (where titles aren't prefixed) consistent.

**D3a. Merge output carries `kid_id`.** The fan-out produces one `KidCalendarResponse` per kid. The merge step injects `kid_id` into each event, returning `CombinedCalendarEvent extends CalendarEvent { kid_id: number }`. This is required for (a) `colorForKid(event.kid_id)` in the `eventStyle` callback, (b) the `"{kid_name}: {title}"` prefix lookup, (c) passing `kidId` to `CalendarEventPopover` on click, and (d) the kid-checkbox filter. The base `CalendarEvent` type stays untouched so per-kid pages don't need changes.

**D4. URL search params (untyped string passthrough, Phase 7-4 pattern).**
- `?view=week|month` (default `week`)
- `?date=YYYY-MM-DD` (default today)
- `?kids=1,3,4` (default = all active kid ids; absent means all)
- `?types=enrollment,unavailability,match` (default = all)
- `?include_matches=true` (default `false`)

`validateSearch` filters non-strings (matches `routes/alerts.tsx` precedent — Phase 7-4). Components are decoupled from `Route.useSearch()` directly — they take a `searchParams` prop, simplifying tests.

**D5. Filters: kid checkboxes + event-type checkboxes.** Both default to all-on. Risk: combinatoric noise. Mitigation: keep the filter bar in one row, hide event-type filters behind a "More filters" disclosure if it gets ugly during implementation. **Defer the disclosure decision to implementation review** — start with one row.

**D6. `include_matches` defaults to `false`.** Same as per-kid view. Matches are noisy for a "what's everyone up to" view; user can flip the toggle on. The roadmap's deferred "user-controllable match score threshold" question is irrelevant here — we just respect the kid's existing threshold.

**D7. Empty states.**
- 0 active kids → "Add a kid to see a combined calendar" with `Link` to `/kids/new`
- 1 active kid → render normally (combined view of one kid is still a valid view, no redirect)
- All kids unchecked → "No kids selected" with a Clear-filters button

**D8. Conflict highlighting: out of scope for v1.** YAGNI. Once the view is in use we'll see if it matters; the roadmap's open-question "soft conflicts as warnings" applies if it does.

**D9. Loading + error UX.** `useQueries` returns one result per kid. Render `<Skeleton>` until *all* are settled. If any error: render the calendar with the kids that succeeded + an `<ErrorBanner>` listing the failed kid names with a "Retry these" button (same pattern as `kids.$id.matches.tsx` for partial failures).

## 5. Backwards compatibility

Per-kid calendar at `/kids/$id/calendar` unchanged. The new `eventStyle?` prop on `<CalendarView>` is optional; per-kid call site doesn't pass it and gets the existing default styling.

## 6. Master §10 terminal criteria delta

None — Phase 8 is polish. This closes roadmap §6 Phase 8-1 and master §7 page #3 (combined-calendar half).

## 7. Out of scope

- Holiday / school-year visual integration (Phase 8-2)
- Watchlist on calendar (Phase 8-3)
- Drag-to-reschedule, ICS import/export (master §9 deferred)
- Soft-conflict warnings
- Backend combined-calendar endpoint (parallel client fetches are sufficient)
- Color palette customization (8-color fixed)
- Per-kid color persistence in DB (computed from `kid.id`)
