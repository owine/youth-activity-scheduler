# Phase 6 (1, 3, 4) — Setup-flow Mutation UIs (Design)

**Date:** 2026-04-30
**Master design:** `docs/superpowers/specs/2026-04-21-youth-activity-scheduler-design.md`
**Roadmap:** `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md` § 6
**Predecessors (already merged):**
- Phase 5b-1b — canonical TanStack Query mutation pattern.
- Phase 5d-1 — `MuteButton` Popover primitive (provides Popover-via-radix-ui template).
**Succeeds into:** Phase 6-2 (Add Site wizard with `/discover` integration; brainstormed separately).

## 1. Purpose and scope

Build the setup-flow mutation UIs that close the master design's terminal-state criteria #1 and #6. v1 ships today as a deployable backend with a viewer pasted on top — no UI for adding kids, editing kids, mutating watchlist entries, or kicking off a site crawl. This phase introduces the codebase's first form patterns and is the gate for any meaningful real usage of v1.

This is a three-slice cluster brainstormed together because they share UX patterns:
- **6-1 Add Kid + Edit Kid** — full-page forms.
- **6-3 Watchlist mutations** — sheet-based add/edit/delete.
- **6-4 Site Crawl-now + Pause** — buttons on the existing site detail page.

**Out:** Phase 6-2 (Add Site wizard) — structurally different (multi-step wizard with AI-in-the-loop step), brainstormed separately.

### 1.1 In scope

- New routes: `/kids` (list), `/kids/new`, `/kids/$id/edit`.
- One shared `<KidForm>` component with `mode: 'create' | 'edit'`.
- Edit pencil icon on kid header (visible across `/kids/$id/*` tabs).
- New sheet `<WatchlistEntrySheet>` for add/edit; delete-with-confirm on each row.
- Add buttons + click-to-edit affordances on `/kids/$id/watchlist`.
- "Crawl now" + "Pause/Resume" buttons on `/sites/$id`.
- Seven new TanStack Query mutation hooks (canonical 5b-1b pattern).
- Backend: no changes — every mutation route already exists.
- Frontend deps: `@tanstack/react-form` 1.29.1, `zod` 4.4.1, `react-day-picker` 9.14.0.

### 1.2 Out of scope

- **Add Site wizard** — Phase 6-2.
- **Kid hard-delete** — soft-delete via `active=false` is the v1 model.
- **Cross-kid watchlist view** (master §7.6) → Phase 7.
- **Bulk import of school holidays from district `.ics`** → Phase 8 / master §9 deferred.
- **`availability` JSON field UI** — unused in current matcher; revisit if a use case appears.
- **Notification preview** ("this change will start firing alerts for X new offerings") — power-user feature, defer.
- **Cancel-an-in-flight-crawl** — out; no backend route for it today.
- **Add-a-page-to-an-existing-site** UI — covered by Phase 6-2 wizard.

## 2. New dependencies

Three new frontend deps. All current/maintained as of 2026-04-30:

| Package | Version | Why |
|---|---|---|
| `@tanstack/react-form` | 1.29.1 | First form library for the codebase. Same author family as TanStack Query (already used). Standard Schema validation API. |
| `zod` | 4.4.1 | Schema-driven validation. Implements Standard Schema natively; works with TanStack Form v1+ without an adapter package. |
| `react-day-picker` | 9.14.0 | Multi-range + multi-date picker for school year ranges and school holidays. shadcn's Calendar component is built on this — keeps us aligned with shadcn ecosystem. |

No backend deps. Both frontend deps pinned exact patch per project convention.

## 3. Architecture

```
                     Phase 6 cluster
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
     6-1 Kid           6-3 Watchlist        6-4 Site
   (full-page form)   (sheet on tab)     (buttons on page)

   ┌────────────────┐  ┌─────────────────┐  ┌──────────────┐
   │ /kids          │  │ /kids/$id/      │  │ /sites/$id   │
   │ /kids/new      │  │  watchlist      │  │              │
   │ /kids/$id/edit │  │ + sheet on Add  │  │ +Crawl now   │
   │                │  │ + sheet on row  │  │ +Pause/Resume│
   │ <KidForm>      │  │   click         │  │              │
   │ <KidsListPage> │  │ <WatchlistEntry │  │ (existing    │
   │                │  │   Sheet>        │  │  page edits) │
   └────────────────┘  └─────────────────┘  └──────────────┘
                                │
                                ▼
              Shared mutation pattern (canonical 5b-1b shape)
                cancelQueries → snapshot → setQueryData
                → onError restore → awaited invalidate
```

All three slices ship together in one PR (or as 2-3 sub-PRs from one branch if total diff is too large for review).

## 4. Phase 6-1: Add Kid + Edit Kid

### 4.1 Routes

| Route | Component | Behavior |
|---|---|---|
| `/kids` | `<KidsListPage>` | Lists all kids as cards (name, DOB, age, interests, active toggle, link to `/kids/$id/matches`). "Add kid" button at top. Empty state: "No kids yet — Add your first kid to start matching." |
| `/kids/new` | `<KidForm mode="create" />` | Add form. Submit success → `/kids/$id/matches` (the just-created kid's matches view). Cancel → `/kids`. |
| `/kids/$id/edit` | `<KidForm mode="edit" id={id} />` | Edit form. Submit success → `/kids/$id/matches`. Cancel → `/kids/$id/matches`. |

`/kids/$id/edit` is **NOT** a tab in `KidTabs` (semantically odd; Edit is an action, not a view). Entry point is the **edit pencil icon in the kid header** rendered across all `/kids/$id/*` tab pages.

### 4.2 `<KidForm>` field UX

Backed by TanStack Form + zod. Single component, `mode: 'create' | 'edit'`. In edit mode, pre-populates from `useKid(id)`.

| Field | Type | UX | Validation (zod) |
|---|---|---|---|
| `name` | string, required | text input, autofocus on Add | 1–80 chars, trimmed |
| `dob` | date, required | `<input type="date">` | ≤ today; ≥ 100y ago |
| `interests` | `list[str]` | tag/chip input. Type + Enter or comma to add; click chip × to remove | array of trimmed non-empty strings, ≤20 items |
| `school_weekdays` | `list[str]` | row of 7 toggle buttons (Sun–Sat). Default Mon–Fri | subset of `{mon,tue,wed,thu,fri,sat,sun}` |
| `school_time_start` / `school_time_end` | time, optional | two `<input type="time">` side-by-side. If both empty, school unavailability is skipped | start < end if both set; both empty allowed |
| `school_year_ranges` | `list[{start, end}]` | `react-day-picker mode="multiple"` of date ranges. Selected ranges as chips below the calendar (`Sep 2 2026 → Jun 14 2027 ×`) | each range start ≤ end; ranges may overlap (matcher unions them) |
| `school_holidays` | `list[date]` | `react-day-picker mode="multiple"` of single dates. Selected dates as chips below | all valid dates; no past restriction |
| `max_distance_mi` | `float | None` | slider 1–50 mi + "no limit" checkbox. Default: no limit | 1–500 if set |
| `alert_score_threshold` | float | slider 0.0–1.0 (step 0.05). Default 0.6. Tooltip explains "matches below this score don't trigger alerts" | 0.0 ≤ x ≤ 1.0 |
| `alert_on` | `dict[str, bool]` | collapsed "Alert types" section — list of 6 toggles (new_match, watchlist_hit, reg_opens_*, schedule_posted, site_stagnant, no_matches_for_kid). All default true | object with bool values |
| `notes` | `str | None` | `<textarea>` | ≤2000 chars |
| `active` | bool | toggle, **edit-only** (Add always creates `active=true`). Soft-delete affordance | bool |
| `availability` | free-form JSON | **excluded from form** — unused in current matcher | n/a |

### 4.3 Submit / cancel semantics

- **Submit button** disabled until form is dirty AND valid.
- **"Saving…"** state during mutation; button re-enables on settle.
- **Server error** → inline `<ErrorBanner>` above the form; buttons re-enable.
- **Cancel button**:
  - If form is clean: navigate immediately
  - If dirty: confirm dialog "Discard changes?" → user picks "Discard" or "Keep editing"
- **Browser-level navigation away from dirty form** (back button, route change) → same confirm dialog. Implementation via TanStack Router's `useBlocker` or equivalent.

### 4.4 `<KidsListPage>`

Simple list. Each card:
- Kid name (large, link to `/kids/$id/matches`)
- DOB → computed age in years
- Interests as small chips
- "Active" badge (or "Inactive" if `active=false`)
- Edit pencil icon (link to `/kids/$id/edit`)

Header: page title, "Add kid" button (links to `/kids/new`).

Empty state copy: *"No kids yet — Add your first kid to start matching."*

## 5. Phase 6-3: Watchlist mutations

### 5.1 Existing surface

`/kids/$id/watchlist` is a tab in `KidTabs` showing per-kid watchlist entries read-only. We add mutation affordances to this surface.

### 5.2 Trigger UI on the watchlist tab

- **"Add watchlist entry"** button at the top of the tab content. Click → opens `<WatchlistEntrySheet mode="create" />`.
- **Click any row** → opens `<WatchlistEntrySheet mode="edit" entryId={id} />`.
- **Each row** gets a small × delete button (right-aligned). Click → confirm dialog "Delete this watchlist entry?" → on confirm, dispatches `useDeleteWatchlistEntry`.

### 5.3 `<WatchlistEntrySheet>` field UX

Right-side sheet matching `AlertDetailDrawer`. Same dirty-confirm and error patterns as `<KidForm>`.

| Field | Type | UX | Validation |
|---|---|---|---|
| `pattern` | string, required | text input. Helper text: "Wildcards: `*` matches any, `?` matches one char (e.g., `t*ball*`)" | 1–200 chars |
| `priority` | enum | segmented control: low / normal / high. Default normal | one of three values |
| `site_id` | int \| null | dropdown: "Any site" (default) or pick from registered sites via `useSites()` | int or null |
| `ignores_hard_gates` | bool | toggle, default `true` (matches existing semantics — watchlist entries bypass age/distance/etc.) | bool |
| `notes` | str \| null | textarea | ≤500 chars |
| `active` | bool | toggle, edit-only | bool |

Sheet header: "Add watchlist entry" or "Edit watchlist entry". Footer: Save (primary) + Cancel.

### 5.4 Cross-kid watchlist view

Out of scope. Master §7.6 calls for a cross-kid view; ship in Phase 7 if real usage demands it. Per-kid surface is sufficient for setup-flow needs.

## 6. Phase 6-4: Site Crawl-now + Pause

### 6.1 Existing surface

`/sites/$id` shows site name + mute button + crawl history + offerings list. We add two affordances to the page header.

### 6.2 "Crawl now" button

- Position: page header, next to the existing mute button.
- Action: `POST /api/sites/{id}/crawl-now` (route already exists).
- Behavior: button shows spinner during in-flight; on settle, briefly shows "Queued ✓" for 2s then resets.
- Confirm dialog: **none** — non-destructive (worst case, an extra crawl runs).
- Idempotent: backend just bumps `next_check_at` to `now`; clicking twice is harmless.

### 6.3 "Pause / Resume" toggle

- Position: page header, next to "Crawl now".
- Reads `site.active`.
- Action: `PATCH /api/sites/{id}` with `{active: false}` or `{active: true}`.
- Visual: button label shows "Pause" when active, "Resume" when paused. Paused sites get a small "Paused" badge next to the site name in the header.
- Confirm dialog: **none** — toggling is reversible and one-click is the goal.
- Race: toggling pause while a crawl is in-flight is OK. The in-flight crawl completes (worker doesn't yank it); future ticks skip the site.

## 7. Mutation hooks

All seven hooks follow the canonical 5b-1b pattern: `cancelQueries → snapshot → setQueryData → onError restore → awaited onSettled invalidate`. Defined in `frontend/src/lib/mutations.ts`.

| Hook | mutationFn | Optimistic surgery | Invalidate |
|---|---|---|---|
| `useCreateKid` | `POST /api/kids` | none (need server-assigned id) | `['kids']` |
| `useUpdateKid` | `PATCH /api/kids/{id}` | update cached `useKid(id)` immediately | `['kids']`, `['kids', id]`, `['matches']` (school changes affect matches) |
| `useCreateWatchlistEntry` | `POST /api/kids/{kid_id}/watchlist` | none | `['kids', kidId, 'watchlist']`, `['matches']` |
| `useUpdateWatchlistEntry` | `PATCH /api/watchlist/{id}` | update in-place in list cache | `['kids', kidId, 'watchlist']`, `['matches']` |
| `useDeleteWatchlistEntry` | `DELETE /api/watchlist/{id}` | remove from list cache | `['kids', kidId, 'watchlist']`, `['matches']` |
| `useCrawlNow` | `POST /api/sites/{id}/crawl-now` | none | `['sites', id]` (refetches after crawl scheduled) |
| `useToggleSiteActive` | `PATCH /api/sites/{id}` `{active}` | flip in cache | `['sites']`, `['sites', id]` |

All `onSettled` invalidations are `await`-ed so callers don't race subsequent refetches.

`api.delete` (added in 5c-2) and `api.patch` (added in 5c-2) and `api.post` (5b-1b) are already in place.

## 8. Edge cases

- **Add Kid with no school fields** — valid; matching has no school-conflict gate. School year ranges + holidays both empty is fine.
- **Edit Kid that's currently `active=false`** — form loads as normal; user can flip back to `active=true`. Inactive kids are filtered out of the matcher's run.
- **Add Watchlist entry with `site_id` pointing at a deleted site** — backend returns 404 on POST; surface as inline error.
- **Edit watchlist entry that another tab just deleted** — PATCH 404; rollback + error banner; row vanishes after invalidate.
- **Add Kid with name colliding with existing kid** — backend allows duplicates (no unique constraint on name); we don't add one client-side.
- **Form submit while another mutation in-flight on the same surface** — same `inFlight` pattern as 5b-1b: button disabled, second click ignored.
- **User opens Edit form, server returns 404 (kid was deleted in another tab)** — show "kid not found" empty state, link back to `/kids`.
- **`react-day-picker` keyboard accessibility** — the lib ships keyboard nav + ARIA out of the box; we don't have to implement those.
- **Crawl-now button when site already in progress** — backend's `crawl-now` is idempotent (just bumps `next_check_at` to now); button shows "Queued ✓" regardless.
- **Pause toggle while a crawl is in-flight** — pause sets `active=false`; the in-flight crawl completes (worker doesn't yank it); future ticks skip the site.
- **Browser-level navigation away from dirty form** — TanStack Router's `useBlocker` triggers the same confirm dialog as the Cancel button.

## 9. Testing

Backend (extend existing files; no new routes to test):
1. `tests/integration/test_api_kids.py` — extend if missing fields; verify POST creates with all fields, PATCH partial updates, validation errors round-trip cleanly.
2. `tests/integration/test_api_watchlist.py` — extend or create. POST/PATCH/DELETE round-trip; 404 paths.
3. `tests/integration/test_api_sites.py` (extend) — `crawl-now` and `active` toggle paths.

Frontend:
4. `frontend/src/lib/mutations.test.tsx` (extend) — 7 new hooks. Optimistic + rollback for the 5 that have surgery; happy-path for the 2 that don't.
5. `frontend/src/components/kids/KidForm.test.tsx` (new) — Add mode submits, Edit mode pre-populates, validation errors render, dirty-confirm fires on cancel, school-year-range picker renders, `react-day-picker` interaction smoke (selecting a range emits the right shape).
6. `frontend/src/routes/kids.index.test.tsx` (new) — list renders, "Add kid" navigates, empty state copy.
7. `frontend/src/components/watchlist/WatchlistEntrySheet.test.tsx` (new) — Add/Edit modes, delete confirm.
8. `frontend/src/routes/sites.$id.test.tsx` (extend) — Crawl-now button fires mutation, Pause toggle flips state.

MSW handlers extended for: `POST /api/kids`, `PATCH /api/kids/:id`, `POST /api/kids/:kid_id/watchlist`, `PATCH /api/watchlist/:id`, `DELETE /api/watchlist/:id`, `POST /api/sites/:id/crawl-now`, `PATCH /api/sites/:id`.

Manual smoke (before merge):
- Navigate to `/kids` (empty state). Click "Add kid". Fill name + DOB + school weekdays + Mon–Fri 8–3 + a school year range + 2 holidays. Submit → lands on `/kids/$id/matches`.
- Click edit pencil on header. Change distance slider. Save → matches list refreshes (school-affecting changes invalidate matches).
- Navigate to `/kids/$id/watchlist`. Add an entry with pattern `t*ball*`, priority high. Edit the entry (priority → normal). Delete (confirm dialog).
- Navigate to `/sites/$id`. Click "Crawl now" → "Queued ✓" briefly. Click "Pause" → badge appears, button changes to "Resume". Click "Resume" → badge disappears.
- Soft-delete a kid (Edit → toggle `active` → save). Navigate to `/kids` — kid still listed but with "Inactive" badge.

## 10. Open questions

None blocking. Field-level UX choices are captured per-table above.

## 11. Master §10 terminal-criteria delta

This phase **closes criterion #6**: *"Setting a kid's school hours produces an `unavailability_blocks` row that causes activities inside those hours on school-year weekdays (minus holidays) to be filtered from matches."* The backend behavior shipped in Phase 1; the criterion specifically requires a UI affordance, which `<KidForm>`'s school fields now provide.

Does **NOT** close criterion #1 (Add Site wizard); that's Phase 6-2.

After Phase 6-1/3/4 + 6-2 ship, the v1 terminal-state will be 7 of 8 met. Criterion #4 (30-day observation, <$5 LLM, zero silent failures) becomes runnable as soon as #1 is met (the user can seed real data and start the clock).

## 12. Exit criteria

Phase 6 cluster is complete when:

- All routes (`/kids`, `/kids/new`, `/kids/$id/edit`) exist and render.
- `<KidForm>` works in both modes; all field types + validation behave as specified.
- Edit pencil icon visible in kid header on every `/kids/$id/*` tab.
- `<WatchlistEntrySheet>` works for add/edit; delete confirm fires.
- `/sites/$id` has working "Crawl now" + "Pause/Resume" buttons.
- All 7 mutation hooks follow the canonical pattern.
- All backend gates green (`pytest`, `ruff`, `mypy`).
- All frontend gates green (`vitest`, `tsc --noEmit`, ESLint).
- Manual smoke: complete the §9 walkthrough end-to-end.
- Master §10 criterion #6 explicitly verified: a kid created with school hours via the form produces an unavailability block that filters a known-conflicting offering from matches.
