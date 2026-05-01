# Phase 7-2 — Offerings Browser Design

**Date:** 2026-05-01
**Status:** Spec
**Author:** Claude + owine
**Closes:** Master §7 page #2 (Offerings browser, cross-kid)
**Roadmap:** `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md` (Phase 7-2)

## Goal

Build a `/offerings` page that lists every offering matching at least one kid, with a rich filter bar (kids, score, program type, days, registration timing, time-of-day, distance, age range, watchlist hits, hide-muted), sorting (best score / soonest start / soonest reg), and inline match-reason chips. After this ships, master §7 page #2 closes.

## Scope

**In scope:**
- New `/offerings` route + page component.
- 5 new components under `frontend/src/components/offerings/`.
- 1 new pure-functions module `frontend/src/lib/offeringsFilters.ts`.
- 1 new query hook `useAllMatches({ minScore, limit })` in `frontend/src/lib/queries.ts`.
- ~24 new frontend tests.

**Out of scope:**
- **Cross-kid watchlist view.** Per-kid watchlist editing already shipped (Phase 6-3); a cross-kid aggregator view would be its own page with no new mutation paths. Roadmap line 67 will be updated to reflect this is no longer a Phase 7-2 deliverable.
- **Backend changes.** `/api/matches` already supports `min_score`, `kid_id`, `offering_id`, `limit`, `offset` filters. The page calls it with `min_score` server-side; everything else is client-side over the result set.
- **URL-based filter state.** Filter state persists in `localStorage` (single user; no shareable URLs needed). URL params would add code for no real benefit.
- **Pagination.** v1 uses a soft cap of 500 matches with a "narrow filters" notice if exceeded. Real pagination can land later if datasets grow.
- **Tooltip library.** Chip explanations use plain `title=""` HTML attributes.
- **Browser-nav guards (`useBlocker`).** Read-only page; no dirty state to guard.
- **Mobile-first layout work.** Single-column matches existing app shape; the "More filters" disclosure is the only collapsible.

## Background

The frontend already has the per-kid matches view at `/kids/$id/matches`, which uses `<MatchCard>` + `<UrgencyGroup>` + `<MatchDetailDrawer>` and groups by registration urgency. That view filters by `kid_id` server-side via `useKidMatches(kidId)`.

Cross-kid browsing requires:
1. Fetching all matches (no `kid_id` filter) up to a soft cap.
2. Grouping by `offering_id` so each offering shows once with all matching kids.
3. A filter bar covering the master design's "browse mode" use cases.

The backend `/api/matches` already supports the filters we need:
- `min_score: float | None = Query(default=None, ge=0.0, le=1.0)` — pushes the score floor server-side, reducing payload.
- `limit: int = Query(default=50, ge=1, le=500)` — capped at 500 backend-side, which we use as the soft cap.
- Other filters (program_type, days_of_week, time-of-day, distance, age, watchlist) live client-side because the backend has no fields/indexes for them, and the dataset is small enough.

Existing UI primitives we reuse without modification:
- `<MatchDetailDrawer>` — opens on row click, shows the best match's full reasons.
- `<MuteButton>` + `useUpdateOfferingMute` — per-row mute control.
- `<EmptyState>`, `<ErrorBanner>`, `<Skeleton>`, `<Card>`, `<Badge>`.
- `useKids()`, `useHousehold()` for filter dropdown data and distance calc.

## Decisions

### D1: Browse offerings, not matches (one row per offering)

The page treats each Offering as the primary row, with all matching kids listed inside. The alternative — one row per (kid, offering) pair — duplicates rows for offerings that match multiple kids, making the page noisier and burying repeat-popular activities. Treating offerings as the subject also matches the master §7 name "Offerings browser."

Trade-off: when only one kid in the household, the one-row-per-offering view is identical to one-row-per-match. So the difference matters only as kid count grows; designing for the 2+ case is right.

### D2: Filter state in localStorage, not URL

Single-user app; no sharing or bookmarking story. URL params would force serializing 11 filters into a query string, parsing on every render, and reconciling with internal state — cost without benefit. Filters live in a single `FilterState` object persisted to `localStorage` under `yas:offerings-filter-v1`. The "More filters" panel collapsed/expanded state goes in the same blob.

### D3: Top filter bar with collapsible "More filters"

11 filters is too many to surface always. Layout:
- **Always visible:** Kids (multi-select chips), Min score (slider), Sort (dropdown).
- **Behind a "More filters (N active)" disclosure:** Hide muted, Program type, Days of week, Reg timing, Time-of-day range, Distance, Age range, Watchlist hits.

Matches the existing single-column app shape (Inbox / Sites / Kids list). A persistent left sidebar would break that pattern; a modal sheet would hide active-filter state. The disclosure adds one click for power use, which is a fair trade for a clean default page.

### D4: Full master-scope filter set

11 filters: 3 primary + 8 secondary. The minimal "Kids + Min score + Hide muted" set covers the 80% case but defeats the page's purpose — without program type and days-of-week, "what soccer is on Saturdays?" is unanswerable. Distance and age-range get included even though the v1 dataset is small, because they're cheap client-side computations and prevent re-cracking the filter bar in Phase 8.

### D5: Categorical chips, not numeric breakdowns

Chips show categorical signals not already in the visible row fields. Five types, max 3 per row, prioritized:
1. `⭐ Watchlist` — any kid match has `reasons.watchlist_hit` truthy.
2. `🎯 Top match` — max kid score ≥ 0.85.
3. `🔥 Opens this week` — `registration_opens_at` within next 7d.
4. `📍 Near home` — any match has `reasons.score_breakdown.distance >= 0.7` (this is the **normalized distance signal** from the matcher, in `[0, 1]`, not raw miles — higher = closer).
5. `🏷 In interests` — `offering.program_type` matches at least one kid's interests array.

Numeric breakdowns (`availability 0.95`, `distance 0.80`) duplicate info already in the score number and are harder to scan. The detail drawer (already built) shows full breakdowns on demand.

### D6: Days-of-week filter is AND-match

When the user selects `[mon, wed, fri]`, only show offerings whose `days_of_week` includes ALL three (i.e., the offering meets on Mon AND Wed AND Fri). This matches "show me Mon/Wed/Fri programs" — a reasonable interpretation of "filter for these days." OR-match (any-of) would be confusing because most v1 offerings only meet on one day, so OR-match would reduce to "did any of these chips light up?"

Empty selection = no filter (don't drop anything).

### D7: Soft 500-row cap with "narrow filters" notice

`/api/matches` accepts up to `limit=500`; we hit it. If the response has exactly 500 matches, render a small inline notice: "Showing 500 of 500+ matches — narrow filters to see more." No pagination UI in v1; the household is unlikely to have >500 distinct kid×offering pairs in practice. If it becomes painful later, Phase 8 adds pagination.

### D8: Pure functions in `lib/offeringsFilters.ts` (testable in isolation)

Three pure helpers:
```ts
export function groupByOffering(matches: Match[]): OfferingRow[];
export function applyFilters(rows: OfferingRow[], filters: FilterState, household: Household | undefined): OfferingRow[];
export function sortOfferingRows(rows: OfferingRow[], sort: SortKey): OfferingRow[];
```
Plus chip computation:
```ts
export function chipsForOffering(row: OfferingRow, kidsById: Map<number, KidBrief>, now: Date): Chip[];
```

All four take their inputs explicitly (no hooks, no globals). 8 of the ~24 tests are unit tests on these functions — fast and exhaustive without mounting React.

### D9: Reuse `<MatchDetailDrawer>` for inspect

Click row → opens the existing `<MatchDetailDrawer>` showing the best-scoring match's full reasons. The drawer already exists and works; no need to introduce an offering-specific detail panel. The drawer's `match` prop is the row's top match (highest score across the kids matched).

When multiple kids match an offering with similar scores, the drawer only shows the top kid's match. v1 accepts this; users who want to compare can re-filter to a different kid and re-click. A multi-kid breakdown panel could be added in Phase 8 if it bites.

### D10: Hide muted is a checkbox, not "show all" / "show muted only" tristate

Default ON. Filters out offerings where `muted_until > now`. v1 doesn't need a "show only muted" inverse view — the user mutes things to dismiss them, not to file them.

### D11: Distance filter no-ops when data is missing; backend extension to surface coords

If `household.home_lat`/`home_lon` is null OR the offering's location has null coords OR the offering has no location, the distance filter is a pass-through for that row. We don't drop rows just because we can't compute distance — that would create a confusing "where did they go?" effect.

**Backend change is required.** `OfferingSummary` (verified in `src/yas/web/routes/matches_schemas.py`) currently exposes `site_id` and `site_name` but no location coords. This PR includes a small backend extension:
- `OfferingSummary` gains `location_lat: float | None`, `location_lon: float | None`.
- `matches.py` `list_matches` joins/loads `Offering.location_id → Location` and populates them. (The existing query already builds `offering_data` dict; add the two fields to the projection.)
- One backend test extending `tests/integration/test_api_matches.py` (or similar): asserts the two new fields are present in the response when the offering has a location with coords, and `null` when it doesn't.

Frontend `OfferingSummary` type gains the same fields. `lib/offeringsFilters.ts` `applyFilters` uses haversine when both household and offering coords are non-null; pass-through otherwise.

### D14: `minScore` default is hardcoded 0.6

`Household` does NOT have `alert_score_threshold`; that field is on `Kid` (per-kid). The earlier draft of D-section text saying "default to `household.alert_score_threshold ?? 0.6`" was wrong. There's no obvious "household-wide threshold" because thresholds are per-kid.

**Decision:** v1 hardcodes the default `minScore = 0.6` on first mount (matches the existing `Kid.alert_score_threshold` Pydantic default). Reasoning:
- Deriving from selected kids (e.g. `min(kid.alert_score_threshold)`) is principled but makes the slider's default value jump around as the user toggles kid chips. Confusing.
- A single hardcoded default keeps the page predictable; users adjust the slider to taste, and the value persists in `localStorage`.
- No backend change needed.

If this proves wrong, Phase 8 can introduce a household-level "browse threshold" setting; not worth it for v1.

### D15: `days_of_week` normalization

Offering schedules in the matcher (`gates.py:139`, `scoring.py:69`) lowercase day strings before comparing — implying upstream values may be mixed-case or full-name. The frontend filter chip values are exactly `'mon'|'tue'|'wed'|'thu'|'fri'|'sat'|'sun'`.

**Normalize at the filter boundary.** `applyFilters` builds a normalized set of an offering's days by mapping `d => d.toLowerCase().slice(0, 3)` before comparing against the filter's selected days. This handles `'Monday'`, `'MON'`, `'mon'` uniformly. Pure function; one line of normalization in `applyFilters`.

### D16: Time-of-day comparison format

Pydantic serializes Python `time` as `"HH:MM:SS"` over the wire; an `<input type="time">` produces `"HH:MM"`. Comparing the two requires alignment.

**Decision:** filter values stored as `"HH:MM"` (from the time input). When comparing against an offering's `time_start: "HH:MM:SS"`, take the first 5 chars: `offering.time_start.slice(0, 5) >= filter.timeOfDayMin`. Simple lexicographic compare on `"HH:MM"` works correctly for valid time strings. Document this in `applyFilters`.

### D17: Reset/Clear scope

Two distinct controls:
- **`Reset` button inside `<MoreFiltersPanel>`** — resets ONLY the 8 secondary filters back to their defaults. Doesn't touch the 3 primary filters (Kids / Min score / Sort) or the panel-open state. Local affordance.
- **`Clear filters` button in the all-filtered-out `<EmptyState>`** — resets ALL 11 filters back to defaults (and re-selects all kid IDs). Recovers the user from "I've narrowed too far."

Both call into the same `lib/offeringsFilters.ts` `defaultFilterState(allKidIds: number[])` factory but with different scopes.

### D18: Empty `selectedKidIds` recovery affordance

`selectedKidIds: []` (user manually unchecked all kid chips) → page shows the all-filtered-out empty state with the `Clear filters` button. Additionally, the kid chip group ALWAYS shows a small "Select all" text link to its right when at least one kid is unselected. This handles both the "manually cleared all" case and the "new kid added; not in persisted selection" case with one affordance.

### D19: Sort tiebreaker

When two rows have the same primary sort key (e.g. same best-score, or both null start_date), break ties by `offering.id` desc (newer offerings first). Stable across renders.

### D12: Soft validation only on age-range filter

The age-range filter (min, max) is two number inputs. Both nullable. Validation: if both set, min must be ≤ max — show inline error and disable the row-level filter (don't apply junk values). Otherwise pass-through. No backend round-trip; just client-side guard.

## Architecture

### Routes

| Route | Component | Purpose |
|---|---|---|
| `/offerings` (new) | `OfferingsBrowserPage` | Main page; reads `useAllMatches` + filters + groups + sorts + renders rows |

Top-banner navigation: add an "Offerings" link between "Inbox" and "Sites" (or wherever it fits). Verify the existing nav pattern when implementing.

### Components

```
OfferingsBrowserPage
├── FilterBar               primary filters (Kids / Min score / Sort) + More-filters toggle
│   └── MoreFiltersPanel    secondary filters (8 controls), collapsed by default
├── (truncation notice)
├── (empty / error states)
└── OfferingRow × N
    ├── MatchReasonChips
    ├── MuteButton (existing)
    └── click → MatchDetailDrawer (existing)
```

`OfferingsBrowserPage` owns `FilterState` (in React state, hydrated from + persisted to `localStorage`). All filter children mutate via `onChange(next)`.

### Data flow

```
useAllMatches({ minScore, limit: 500 }) → Match[]
  ↓
groupByOffering(matches) → OfferingRow[]
  ↓
applyFilters(rows, filterState, household) → OfferingRow[]
  ↓
sortOfferingRows(rows, sortKey) → OfferingRow[]
  ↓
render rows
```

Re-runs on every filter change; pure-function chain means it's cheap and testable.

### Files

**Create — frontend:**
- `frontend/src/routes/offerings.tsx` — thin route shell.
- `frontend/src/components/offerings/OfferingsBrowserPage.tsx`
- `frontend/src/components/offerings/OfferingsBrowserPage.test.tsx`
- `frontend/src/components/offerings/FilterBar.tsx`
- `frontend/src/components/offerings/FilterBar.test.tsx`
- `frontend/src/components/offerings/MoreFiltersPanel.tsx`
- `frontend/src/components/offerings/MoreFiltersPanel.test.tsx`
- `frontend/src/components/offerings/OfferingRow.tsx`
- `frontend/src/components/offerings/OfferingRow.test.tsx`
- `frontend/src/components/offerings/MatchReasonChips.tsx`
- `frontend/src/components/offerings/MatchReasonChips.test.tsx`
- `frontend/src/lib/offeringsFilters.ts`
- `frontend/src/lib/offeringsFilters.test.ts`

**Modify — frontend:**
- `frontend/src/lib/queries.ts` — add `useAllMatches({ minScore, limit })`.
- `frontend/src/lib/types.ts` — add `OfferingRow`, `FilterState`, `SortKey`, `Chip` types. Possibly extend `OfferingSummary` with `location_lat`/`location_lon` if backend changes are needed.
- `frontend/src/components/layout/Header.tsx` (or wherever the nav lives) — add "Offerings" link.
- `frontend/src/routeTree.gen.ts` — regenerated by build.
- `frontend/src/test/handlers.ts` — confirm `/api/matches` GET handler exists; verify it accepts the limit/min_score query params and returns a default fixture (likely already there from earlier phases).

**Modify — backend (required, per D11):**
- `src/yas/web/routes/matches_schemas.py` — add `location_lat: float | None`, `location_lon: float | None` to `OfferingSummary`.
- `src/yas/web/routes/matches.py` — load Location for each offering (eagerly via the same join pattern used for `Site.name`, or a separate query) and populate the two fields in the response. Must handle `offering.location_id is None` (returns null/null).
- Extend `tests/integration/test_api_matches.py` with one test asserting the new fields populate when the offering has a Location with coords and are null otherwise.

**No new dependencies.**

## Filter semantics (precise)

```ts
interface FilterState {
  // Primary
  selectedKidIds: number[];          // empty = none selected (show nothing); default = all kid IDs
  minScore: number;                  // 0..1
  sort: 'best_score' | 'soonest_start' | 'soonest_reg';
  // Secondary
  hideMuted: boolean;                // default true
  programTypes: string[];            // empty = no filter; populated dropdown is the ProgramType enum minus 'unknown'
  days: ('mon'|'tue'|'wed'|'thu'|'fri'|'sat'|'sun')[]; // empty = no filter; AND-match
  regTiming: 'any' | 'opens_this_week' | 'open_now' | 'closed';
  timeOfDayMin: string | null;       // 'HH:MM' or null
  timeOfDayMax: string | null;       // 'HH:MM' or null
  maxDistanceMi: number | null;      // null = no filter
  ageMin: number | null;
  ageMax: number | null;
  watchlistOnly: boolean;
  // Persistent UI
  moreFiltersOpen: boolean;          // disclosure state
}
```

Defaults on first mount:
- `selectedKidIds`: all kids from `useKids()`. (If a kid is added later, current filter selection doesn't include them — surfaces a small "(N kids hidden)" notice next to the chip group with a "Select all" link.)
- `minScore`: `0.6` hardcoded (per D14).
- `sort`: `best_score`.
- All others: defaults shown above.

`applyFilters` order (cheapest first; short-circuits early when possible): kids → hideMuted → programTypes → days → time-of-day → regTiming → distance → ageRange → watchlistOnly.

## Chips

```ts
type ChipKind = 'watchlist' | 'top_match' | 'opens_this_week' | 'near_home' | 'in_interests';

interface Chip {
  kind: ChipKind;
  label: string;     // '⭐ Watchlist', '🎯 Top match', etc.
  className: string; // Tailwind classes for the badge styling
}

export function chipsForOffering(
  row: OfferingRow,
  kidsById: Map<number, KidBrief>,
  now: Date,
): Chip[] {
  // Compute eligibility for each kind in priority order, return first 3 that pass.
}
```

Priority order: watchlist > top_match > opens_this_week > near_home > in_interests. Chips render right-aligned in the row's top line, before the score number.

## Truncation notice

When `useAllMatches` returns exactly 500 matches:
```tsx
<div className="rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-900/20 dark:text-amber-200">
  Showing 500 of 500+ matches — narrow your filters to see more.
</div>
```

## Empty / error states

- `useKids().data?.length === 0`: `<EmptyState>Add a kid first to see offerings. <Link to="/kids/new">Add kid</Link></EmptyState>`.
- `useAllMatches.isError`: `<ErrorBanner message="Failed to load matches" onRetry={...} />`.
- `useAllMatches` returns empty: `<EmptyState>No matches yet — pages need to be crawled before offerings appear here.</EmptyState>`.
- All-filtered-out: `<EmptyState>No offerings match your filters. <Button onClick={resetFilters}>Clear filters</Button></EmptyState>`.

## Testing

**Frontend test count target:** ~24 new tests, raising 200 → ~224.

### `offeringsFilters.test.ts` (~8 tests, pure functions)
1. `groupByOffering` collapses N matches per offering into one row sorted by kid-match score desc.
2. `applyFilters` kids-filter drops non-selected kids' matches; row drops if no matches remain.
3. `applyFilters` days AND-match: row days `['mon','wed','fri']` passes filter `['mon','wed']`; fails filter `['mon','sat']`.
4. `applyFilters` reg-timing branches (opens_this_week / open_now / closed) tested with fixture dates.
5. `applyFilters` distance: passes through when household lat/lon null; applies haversine when both sides have coords.
6. `applyFilters` age-range overlap: row `age_min=5/age_max=10` passes filter `min=8/max=12`; fails filter `min=11/max=14`.
7. `applyFilters` watchlist-only drops rows where no match has truthy `reasons.watchlist_hit`.
8. `sortOfferingRows` for each sort key with ties + null handling.

### `MatchReasonChips.test.tsx` (~5 tests)
1. All 5 chips potentially apply → only top 3 shown in priority order.
2. Watchlist always first when present.
3. `In interests` resolves through passed-in `kidsById` (kid's interests array).
4. None applicable → renders nothing (no empty `<div>`).
5. `Near home` requires a kid match's `reasons.score_breakdown.distance >= 0.7`.

### `OfferingRow.test.tsx` (~3 tests)
1. Renders name + site_name + dates + price + best-score-across-kids + chips + matched kids list.
2. Click row opens `<MatchDetailDrawer>` with the highest-scoring match for that offering.
3. Mute button click does NOT trigger row click (stopPropagation works).

### `MoreFiltersPanel.test.tsx` (~4 tests)
1. Collapsed by default; click toggle expands.
2. Each filter group control mutates state via `onChange` (illustrative: program-type select + days chip toggle).
3. Persists open/closed state to localStorage (mock `localStorage`; render twice; assert second mount restores).
4. Reset button clears all secondary filters back to defaults.

### `OfferingsBrowserPage.test.tsx` (~4 tests)
1. Renders rows from grouped matches; one row per offering even when multiple kids match.
2. Empty matches → "No matches yet" empty state.
3. Kid multi-select filter narrows visible rows.
4. Filter state persists to `localStorage` on change; mount-2 restores from localStorage.

## Acceptance criteria

- ✅ `/offerings` route renders an OfferingRow per offering with at least one selected-kid match.
- ✅ All 11 filters function per the precise semantics above.
- ✅ Up to 3 chips per row in priority order.
- ✅ Default sort is best score across kids desc; the dropdown switches to soonest-start or soonest-reg.
- ✅ Filter state + panel collapsed state persist in `localStorage` under `yas:offerings-filter-v1`.
- ✅ Click row opens `<MatchDetailDrawer>`; mute button works without firing row click.
- ✅ Empty/error/truncation states render the right copy.
- ✅ Frontend gates clean; ~224 tests passing.
- ✅ Manual smoke: navigate `/offerings`, scan rows, narrow with one chip filter, mute one offering, open detail drawer.

## Risks

- **Backend `OfferingSummary` may lack location coords.** D11 includes a fallback (small backend extension); verify during implementation. If the backend change is needed, it expands the PR scope by a small backend commit + tests.
- **Filter reactivity performance.** With ~500 matches and 11 filters, each filter change re-runs the whole pipeline. Pure functions + small dataset means this should be sub-frame; if it bites, memoize via `useMemo` keyed on filterState + household.
- **Empty default state for `selectedKidIds`.** Deciding default = all-kids vs default = none can confuse first-time users. Defaulting to all-kids is the right "everything's interesting until I narrow it" UX. Document the "+ Select all when new kid added" subtle behavior; if it's surprising, easy to flip.
- **MatchOut size.** With 500 matches × current shape, response could be ~50-100KB. Acceptable for v1; if it bites later, a more compact "summary" endpoint is straightforward.

## Out of scope (explicit non-goals)

- Cross-kid watchlist view (deferred per Q2 / spec scope above).
- Backend pagination beyond limit=500.
- URL-based filter state.
- Multi-kid match breakdown panel (drawer shows top kid only).
- Offering favoriting / bookmarking.
- "Compare two offerings side-by-side."
- Per-offering inline note editing.

## After this lands

Master §7 page status:
- 6 of 9 met (after Phase 7-1)
- **7 of 9 met** (after this) — page #2 Offerings browser closed.
- Remaining: page #3 combined calendar (Phase 8-1), page #7 (Enrollments → Phase 7-3), page #8 outbox/preview (Phase 7-4).
