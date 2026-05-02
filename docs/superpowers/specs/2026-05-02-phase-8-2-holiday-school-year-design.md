# Phase 8-2: Holiday / School-Year Calendar Integration — Design

**Date:** 2026-05-02
**Status:** Approved
**Roadmap:** `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md` §6 Phase 8-2

## 1. Problem

`Kid.school_holidays` is a list of ISO-date strings the user already maintains via the Kid edit form (Phase 6-1). The matcher correctly skips conflict checks on those dates (`yas.matching.matcher._school_holidays`). But `GET /api/kids/{id}/calendar` ignores them — the calendar happily renders a "School" recurring block on every weekday in `school_year_ranges`, including holidays. The roadmap entry called this out: today users have to also create a separate manual `UnavailabilityBlock` for spring break to make the calendar match reality. That's a workaround for a bug.

Two gaps:
- **Bug:** the calendar renders school on holiday dates.
- **UX gap:** even after the bug fix, holidays render as "nothing." Users see a weekday with no school and no obvious reason. An explicit marker makes the calendar self-explanatory.

## 2. Approach

Two coordinated changes:

**(1) Backend bug fix.** When expanding `UnavailabilityBlock`s in `kid_calendar.py`, skip occurrences whose date is in `kid.school_holidays` AND whose `block.source == 'school'`. Non-school blocks (manual unavailability, enrollment-derived blocks) are unaffected — those still render even on holidays, since they represent the kid being unavailable for non-school reasons.

**(2) Add `holiday` event kind.** The endpoint emits one `holiday` event per date in `kid.school_holidays` that falls within the request range AND inside at least one `school_year_range`. Frontend gets a matching CSS class and the combined calendar's type-filter list grows by one.

**Why filter holidays to the school-year range?** A date in `school_holidays` outside the school year (e.g., July 4) doesn't represent a school holiday — it represents a free day that's already free. Rendering it as "Holiday" would imply school is being cancelled, which is misleading.

## 3. Components and files

### Backend

| File | Change |
|---|---|
| `src/yas/web/routes/kid_calendar_schemas.py` | Extend the `kind` `Literal` to include `"holiday"`. |
| `src/yas/web/routes/kid_calendar.py` | (a) Build a `school_holiday_dates: set[date]` from `kid.school_holidays`; (b) when expanding `UnavailabilityBlock` with `source=school`, skip occurrences whose date is in that set; (c) after expanding blocks, emit one `holiday` event per holiday date that falls in range AND inside `school_year_ranges`. |
| `tests/integration/test_api_kid_calendar.py` | Add tests: school block skipped on holiday; holiday event emitted; holiday outside school year not emitted; non-school blocks not affected by holidays. |

### Frontend

| File | Change |
|---|---|
| `frontend/src/lib/types.ts` | Add `'holiday'` to `CalendarEventKind` union. |
| `frontend/src/components/calendar/CalendarView.tsx` | Extend the kind→className mapping to include `'holiday' → 'rbc-event-holiday'`. |
| `frontend/src/components/calendar/calendar-overrides.css` | Add `.rbc-event-holiday` rule with a soft amber/yellow palette (festive, non-alarming, distinct from the muted unavailability gray). |
| `frontend/src/components/calendar/CombinedCalendarFilters.tsx` | Add `{ kind: 'holiday', label: 'Holiday' }` to `ALL_TYPES`. Default on (matches other types). |
| `frontend/src/components/calendar/CombinedCalendarFilters.test.tsx` | Update test that asserts the type-checkbox set; add coverage for toggling Holiday. |
| `frontend/src/lib/combinedCalendar.test.ts` | Confirm holiday events flow through merge (filtered by `types` correctly). |

### No change needed

- `frontend/src/components/kids/KidForm.tsx` — already manages `school_holidays`.
- `src/yas/matching/matcher.py` — already respects `school_holidays`.
- `src/yas/unavailability/school_materializer.py` — still emits one school block per `school_year_range`; the calendar layer is now responsible for excluding holidays during render. (We deliberately don't materialize holiday-cuts as block boundaries; that would explode block count and conflate "schedule reality" with "calendar rendering.")

## 4. Decisions

**D1. Skip school occurrences on holiday dates, but emit a separate `holiday` event.** Two layers of change rather than one. Rationale: skipping alone leaves a confusing gap; emitting alone leaves school still rendered (worse). Both together produce the right UX.

**D2. `holiday` is a new event kind, not a sub-type of `unavailability`.** A holiday is *not* the kid being unavailable — it's a day they're explicitly free. Conflating with unavailability would distort the type filter ("uncheck Unavailability hides holidays"). New kind is two-line additions in the type system; cheap.

**D3. Holiday events are all-day with title `"Holiday"`.** No name field on `school_holidays` (it's a flat list of date strings). Adding labels would require a DB migration to change the column shape — out of scope. Title `"Holiday"` plus the date being on the calendar is enough context.

**D4. Holidays render only inside `school_year_ranges`.** A holiday date outside the school year is meaningless ("today is a school holiday" doesn't apply when it's summer). Filter in the endpoint, not the frontend.

**D5. Holiday filter defaults ON.** Matches enrollment/unavailability/match defaults. User can hide via the type filter.

**D6. CSS color: soft amber.** `.rbc-event-holiday` uses an amber-100/amber-700 pair (light amber bg, dark amber text). Distinct from the gray of unavailability and the primary blue of enrollment. Color-blind safe.

**D7. Per-kid calendar: no UI change needed beyond CSS + kind mapping.** No type-filter UI on per-kid view. Holidays just appear with their CSS class.

**D8. Combined calendar `eventStyle` for kid-color overlay still applies to `holiday` events.** Each holiday is per-kid (school holidays are kid-specific), so coloring by kid is consistent. The CSS class provides the holiday-shape baseline; the inline kid-color overlays it via `eventStyle`'s `style` prop.

## 5. Test plan

### Backend (`tests/integration/test_api_kid_calendar.py`)

- Holiday on a school weekday → school occurrence skipped, holiday event emitted.
- Holiday on a non-school weekday → no school to skip, holiday event still emitted.
- Holiday outside any `school_year_range` → no holiday event emitted.
- Manual (`source=manual`) unavailability block on a holiday date → still emits unavailability event (only school blocks honor holidays).
- Holiday outside the request `from`/`to` range → not in response.

### Frontend

- Combined calendar filter: Holiday checkbox renders, defaults on, toggles off filters out events.
- Merge function: holiday events flow through, respect `types` filter.

## 6. Master §10 terminal criteria delta

None — Phase 8 is polish. Closes roadmap §6 Phase 8-2.

## 7. Out of scope

- Holiday names/labels (would require DB schema change to `school_holidays`).
- Auto-importing public-holiday calendars (Google Calendar / iCal).
- Holiday rendering as recurring across multiple school-year ranges (each entry in `school_holidays` is a single date).
- Materializing holidays as block boundaries in the materializer (kept as render-time exclusion; matcher already handles its own logic).
- Per-kid color tweaking for holidays (uses the same kid color as other events; holiday-vs-other-event differentiation comes from the CSS class baseline).
