# Phase 6-2 — Add Site Wizard Design

**Date:** 2026-04-30
**Status:** Spec
**Author:** Claude + owine
**Closes:** Master §10 terminal criterion #1 ("User can add a site via the UI in <2 min")
**Roadmap:** `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md` (Phase 6-2)

## Goal

Build the frontend Add-Site wizard that lets a user paste a site URL, see Claude-discovered candidate schedule pages, optionally add URLs manually, and create the site with one click. After this ships, master criterion #1 closes and Phase 6 is fully complete.

## Scope

**In scope:** Frontend only. New `/sites/new` route; new components (`SiteWizard`, `CandidateList`, `ManualPageEntry`); new mutation hooks for discover/page-add (the create-site and crawl-now hooks already exist or are trivial extensions). MSW handler updates. Tests.

**Out of scope:**
- **No backend changes.** All four endpoints exist: `POST /api/sites`, `POST /api/sites/{id}/discover`, `POST /api/sites/{id}/pages`, `POST /api/sites/{id}/crawl-now`. Frontend orchestrates them.
- **No DELETE-site UI** for cleaning up orphaned shells (sites created when user bails mid-wizard). Accepted v1 cost; future polish.
- **No `useBlocker` browser-nav guard.** KidForm has it; wizard is a one-shot flow where over-engineering doesn't pay. Phase 7 can revisit.
- **No re-styling of the kind selector.** Native `<select>` for v1.
- **No "Add another site" success state.** Wizard navigates straight to `/sites/$id` on success.

## Background

The roadmap describes Phase 6-2 as "two-path flow: paste URL → either (a) confirm a known schedule URL, or (b) call `/api/sites/{id}/discover` and let the user pick from Claude-ranked candidates." This spec resolves that into a single always-discover flow with a manual-URL escape hatch — see Decisions below.

Existing backend pieces (no changes):
- `POST /api/sites` — body `{name, base_url, needs_browser?, default_cadence_s?, crawl_hints?, pages?}`. Returns `SiteOut` with `id`. The optional `pages` array is unused by the wizard; we add pages after discover.
- `POST /api/sites/{id}/discover` — body `{min_score?, max_candidates?}` (both optional). Returns `{site_id, seed_url, stats, candidates: [{url, title, kind, score, reason}]}`. Calls Claude under the hood; can take 5–30s. Returns 502 on LLM error, 503 if LLM not configured.
- `POST /api/sites/{id}/pages` — body `{url, kind}` where `kind ∈ {schedule, registration, list, other}`. Returns `PageOut`.
- `POST /api/sites/{id}/crawl-now` — 202-no-body; queues a crawl.

Existing frontend reusable infrastructure:
- `<ErrorBanner>`, `<Button>`, `<Card>`, `<Skeleton>`, `<Badge>`, `<ConfirmDialog>`
- TanStack Form + zod (Standard Schema validation, no adapter)
- Canonical 5b-1b mutation pattern (cancelQueries → snapshot → setQueryData → onError restore → awaited onSettled invalidate)
- MSW + Vitest test conventions (see `frontend/src/components/kids/KidForm.test.tsx` for the form-with-mutation-capture template)

## Decisions

### D1: Pure frontend orchestration (no backend changes)

The natural flow requires three round-trips: create shell → discover → add pages. A composite endpoint or "draft" flag could keep the DB cleaner by avoiding orphaned shells if a user bails mid-wizard, but for a single-household app the orphan cost is trivial (manual SQL cleanup or a future delete-site UI). Frontend-only ships fastest and matches the existing pattern of "the API is the surface area, frontend orchestrates."

### D2: Always-discover with manual-URL escape hatch

The roadmap suggested two upfront paths (paste known URL vs. discover candidates). We collapse to one: always run `/discover`, and put a "Add a URL manually" affordance below the candidate list. Reasons:
- Most users don't know upfront whether they need discover (they don't know if the site has a discoverable schedule page until they look).
- LLM cost is small in v1 (one call per site addition).
- Even users who think they know the URL get a free sanity check from Claude — they may discover a better page.
- Single path = simpler UI, fewer states, fewer tests.

When discover fails or returns zero candidates, the manual-entry input is the user's path forward (see D6).

### D3: Single-page progressive reveal

Multi-step wizards can use a stepper UI (Step 1 of N with Next/Back), a single-page progressive-reveal layout, or a two-page split (e.g., `/sites/new` then `/sites/$id/discover`). We use **single-page progressive reveal**:

- Top: name + base_url + "Discover pages" button.
- Click Discover → in-place loading state.
- Below: candidate list + manual-entry input + Save button — appear once discover completes.
- All on one route, no Next/Back chrome.

A stepper adds chrome for two real steps. The two-page split fragments a single conceptual task and complicates routing; the only benefit (refresh-resume) doesn't justify the overhead given typical discover times.

### D4: Pre-selected high-confidence candidates with collapsed low-confidence

After discover returns, candidates with score ≥ 0.7 are auto-checked and rendered with their `reason` text visible. Candidates < 0.7 are collapsed under a `Show N more candidates` disclosure. Sorted by score desc within each group.

A plain ranked list dumps cognitive load on the user; a kind-grouped layout over-structures a list that's almost always all `schedule` pages anyway. The 0.7 threshold is a v1 default; settings could expose it later.

### D5: Auto-fire `/crawl-now` after pages are added

The wizard's value proposition is "I added a site, now show me what it tracks." Without auto-crawl, the user waits up to 6h (default cadence) before any data appears, or has to remember to click Crawl-now on the detail page. Auto-firing `/crawl-now` after page POSTs succeed gives immediate feedback. Cost: one extra mutation call we already have wired (Phase 6-4's `useCrawlNow`).

If `/crawl-now` itself fails after page adds succeeded, soft-fail: navigate to `/sites/$id` anyway (the pages were added — the wizard's primary work succeeded). The detail page can surface its own crawl-status error if relevant.

### D6: Strict gating — Save requires ≥1 page

If discover fails or returns zero candidates, the Save button stays disabled until the user adds at least one URL via the manual-entry input. Allowing zero-page sites would create orphans that don't crawl anything — the user thinks they did something but didn't. Forcing a complete setup is the wizard's purpose.

### D7: Sequential page POSTs

For N selected pages, POST them sequentially. v1 page counts are 1–5; the latency cost is negligible and partial-failure handling becomes trivial: stop on the first failure, show "Added X of N — retry remaining." `Promise.all` would be marginally faster but harder to surface partial failure.

## Architecture

### Routes

| Route | Component | Purpose |
|---|---|---|
| `/sites` (modify) | `SitesIndexPage` | Add a header "Add site" button linking to `/sites/new`. |
| `/sites/new` (new) | `NewSitePage` | Thin route shell that mounts `<SiteWizard />`. |

### Components

```
SiteWizard
├── pre-discover form (name + base_url)
│     └── "Discover pages" button
├── DiscoveryLoadingState  (during /discover)
├── ErrorBanner            (on /discover error)
├── CandidateList          (when /discover returns ≥0 candidates)
│     ├── high-confidence section (score ≥ 0.7, expanded)
│     └── low-confidence disclosure (score < 0.7, collapsed)
├── ManualPageEntry        (always visible after /discover, even on error)
│     ├── URL input + kind <select> + "Add" button
│     └── chip list of added entries with × to remove
├── action row
│     ├── "Create site" button (disabled when 0 pages selected/added)
│     └── "Cancel" button
└── ConfirmDialog (dirty cancel pre-discover only)
```

### State

State lives in `<SiteWizard>` (single component owns the wizard's lifecycle). TanStack Form owns the name/base_url and the manual-URL input form. Lifecycle state is plain `useState`:

```ts
const [siteId, setSiteId] = useState<number | null>(null);
const [discoverState, setDiscoverState] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
const [candidates, setCandidates] = useState<Candidate[]>([]);
const [selectedUrls, setSelectedUrls] = useState<Set<string>>(new Set());
const [manualEntries, setManualEntries] = useState<{ url: string; kind: PageKind }[]>([]);
const [saveState, setSaveState] = useState<'idle' | 'saving' | 'error'>('idle');
const [errorMsg, setErrorMsg] = useState<string | null>(null);
```

Pages to create on Save = `[...candidates.filter(c => selectedUrls.has(c.url)), ...manualEntries]` (de-duplicated by URL).

### Mutations

Add to `frontend/src/lib/mutations.ts`:

- `useCreateSite()` — `POST /api/sites`. Vars: `{name, base_url}` (other site fields use defaults).
- `useDiscoverPages()` — `POST /api/sites/{siteId}/discover`. Vars: `{siteId}`. Returns the `DiscoveryResultOut` shape.
- `useAddPage()` — `POST /api/sites/{siteId}/pages`. Vars: `{siteId, url, kind}`. Returns `PageOut`.
- `useCrawlNow` already exists (Phase 6-4).

All four follow the canonical 5b-1b pattern. Non-optimistic (these are creates that flip lists; just invalidate `['sites']` and `['sites', siteId]` on success).

### Files

**Create:**
- `frontend/src/routes/sites.new.tsx` — thin route mounting `<SiteWizard />`.
- `frontend/src/components/sites/SiteWizard.tsx`
- `frontend/src/components/sites/SiteWizard.test.tsx`
- `frontend/src/components/sites/CandidateList.tsx`
- `frontend/src/components/sites/CandidateList.test.tsx`
- `frontend/src/components/sites/ManualPageEntry.tsx`
- `frontend/src/components/sites/ManualPageEntry.test.tsx`

**Modify:**
- `frontend/src/routes/sites.index.tsx` — add header "Add site" button.
- `frontend/src/lib/mutations.ts` — add 3 new hooks.
- `frontend/src/lib/mutations.test.tsx` — tests for the 3 new hooks (~6 tests, happy + error per hook).
- `frontend/src/test/handlers.ts` — MSW handlers for `POST /api/sites`, `POST /api/sites/:id/discover`, `POST /api/sites/:id/pages`. Site list/detail handlers may already exist; verify.
- `frontend/src/lib/types.ts` — add `Candidate` and `DiscoveryResult` types matching backend `CandidateOut` / `DiscoveryResultOut`.
- `frontend/src/routeTree.gen.ts` — regenerated by build.

**No new dependencies.** All needed pieces (TanStack Form, zod, radix-ui, MSW) are already pinned.

## Data Flow

### Happy path

```
User on /sites/new
  ↓ types name + URL, clicks "Discover pages"
useCreateSite.mutateAsync({name, base_url})
  → 201 Created { id, ... }
  setSiteId(id)
useDiscoverPages.mutateAsync({siteId: id})
  → 200 { candidates: [...] }
  setCandidates(candidates)
  setSelectedUrls(new Set(candidates.filter(c => c.score >= 0.7).map(c => c.url)))
  setDiscoverState('success')

CandidateList renders. ManualPageEntry visible.
User toggles checkboxes / adds manual URLs.

  ↓ clicks "Create site"
const pages = [...selected, ...manualEntries]   // de-duplicated by URL
for (const p of pages) {
  await useAddPage.mutateAsync({siteId, url: p.url, kind: p.kind})
  // on error: setSaveState('error'); setErrorMsg(...); break (state holds remaining)
}
useCrawlNow.mutate({siteId})  // soft-fail; don't block navigation
navigate({to: '/sites/$id', params: {id: String(siteId)}})
```

### Error paths

| Failure | Behavior |
|---|---|
| `useCreateSite` fails | ErrorBanner above form. Form stays editable. Click "Discover pages" again to retry. `siteId` stays `null` so the next attempt creates a fresh shell. |
| `useDiscoverPages` 502 | ErrorBanner: "Discovery failed — try again, or add URLs manually." `discoverState = 'error'`. ManualPageEntry visible. "Retry discover" button reuses the existing `siteId`. |
| `useDiscoverPages` 503 | ErrorBanner: "Discovery requires Claude API access. Add URLs manually below." Same shape as 502; copy differs. |
| `useDiscoverPages` returns 0 candidates | `discoverState = 'success'`, `candidates = []`. CandidateList renders an empty-state message. ManualPageEntry is the path. |
| `useAddPage` partial failure (3rd of 5 fails) | Stop sequentially. `setSaveState('error')` + ErrorBanner: "Added 2 of 5 pages — fix and retry." Successfully-added URLs are removed from `selectedUrls` and `manualEntries`. User clicks Save again to retry remaining. |
| `useCrawlNow` fails after pages succeeded | Soft-fail: log to console, navigate anyway. Wizard's primary work (adding pages) succeeded. |
| URL validation fail (zod) | Inline field error; mutation never fires. |
| Manual URL duplicates a candidate URL | Reject the manual add with inline "already in candidates" error. |

### Cancel behavior

- **Pre-discover (siteId === null)**: form may be dirty (name/base_url typed). Show ConfirmDialog if dirty (KidForm pattern). Clean cancel navigates to `/sites`.
- **Post-discover (siteId set)**: navigate immediately to `/sites`. The orphan shell stays in the DB; user can clean it up via SQL or future delete-site UI. No auto-DELETE — keeps the implementation simple per D1.

## Validation

zod schemas (co-located in component files; no shared schema file needed):

```ts
// In SiteWizard
const siteFormSchema = z.object({
  name: z.string().trim().min(1, 'Name is required').max(120),
  base_url: z.string().url('Must be a valid URL'),
});

// In ManualPageEntry
const manualEntrySchema = z.object({
  url: z.string().url('Must be a valid URL'),
  kind: z.enum(['schedule', 'registration', 'list', 'other']),
});
```

## Testing

**Frontend test count target:** ~21 new tests, raising 138 → ~159.

### `SiteWizard.test.tsx` (~8 tests)

1. Renders name + base_url inputs and a disabled "Discover pages" button.
2. Discover button enables when name + base_url are valid.
3. Discover click POSTs `/api/sites` then `/api/sites/{id}/discover` (MSW request capture).
4. Successful discover renders the candidate list with score ≥ 0.7 pre-checked.
5. Discover error renders ErrorBanner; manual entry remains usable.
6. Save button disabled when 0 pages selected/added.
7. Save click POSTs `/pages` per page sequentially, then `/crawl-now`, then navigates to `/sites/$id`.
8. Partial page-add failure leaves remaining + ErrorBanner.
9. (Bonus if cheap:) Dirty cancel pre-discover → ConfirmDialog; clean cancel doesn't.

### `CandidateList.test.tsx` (~4 tests)

1. Sorts candidates by score desc.
2. Auto-checks candidates with score ≥ 0.7; expands their reason text.
3. Collapses score < 0.7 candidates under a `Show N more` disclosure.
4. Toggling a checkbox calls `onChange` with the updated `Set<string>`.

### `ManualPageEntry.test.tsx` (~3 tests)

1. Add URL + kind appends to the list.
2. Click × removes an entry.
3. Duplicate URL (against existing candidates or manual entries) shows inline error.

### `mutations.test.tsx` extensions (~6 tests)

Two tests per new hook (happy path + error path) for `useCreateSite`, `useDiscoverPages`, `useAddPage`. Use the existing pattern in `mutations.test.tsx`.

### Manual smoke (master §10 criterion #1 verification)

After all tests pass and the branch is ready:

1. Open `/sites`.
2. Click "Add site" button.
3. Enter a name + base URL of a test site (use the dev fixture's Lil Sluggers URL or any local test target).
4. Click Discover. Wait for candidates.
5. Verify candidates with score ≥ 0.7 are pre-checked.
6. (Optional) Add one URL manually.
7. Click Create site.
8. Verify navigation to `/sites/$id` and that pages are listed.
9. Verify a crawl was queued (CrawlRun should appear in the detail page or via API).
10. **Time the flow** end-to-end. Must be < 2 minutes per criterion #1.

## Acceptance criteria

- ✅ User can navigate from `/sites` to `/sites/new` via a visible "Add site" button.
- ✅ User can paste a base URL + name and click Discover.
- ✅ Discover step shows a loading state and renders Claude-ranked candidates on success.
- ✅ Candidates with score ≥ 0.7 are pre-checked; lower-score collapsed.
- ✅ User can add URLs manually with kind selector; duplicates rejected inline.
- ✅ Discover error states (502/503/0-results) leave manual entry usable.
- ✅ Save button is disabled when 0 pages selected/added.
- ✅ Save creates pages sequentially, fires crawl-now (soft-fail), navigates to `/sites/$id`.
- ✅ Partial page-add failure preserves remaining and shows ErrorBanner.
- ✅ Pre-discover dirty cancel triggers ConfirmDialog; post-discover cancel navigates immediately.
- ✅ Frontend gates clean: `npm run typecheck`, `npm run lint`, `npm run test` (~159 tests).
- ✅ Manual smoke: end-to-end "add a real site" flow completes in < 2 minutes (closes master §10 criterion #1).

## Risks

- **LLM latency variance.** Discover can take 5–30s. The single-page progressive reveal handles this gracefully (loading state stays anchored to the form), but on slow connections users may suspect the page is broken. Mitigation: a clear spinner with copy "Asking Claude to find schedule pages — this can take up to 30 seconds." If this proves bad in practice, Phase 7 can add a polling/SSE-based progress indicator.
- **Orphan shells.** Per D1, no auto-cleanup. If users bail mid-wizard frequently, the `/sites` list could accumulate empty sites. Mitigation: low real-world risk in a single-user app; if it bites, a small follow-up PR adds DELETE-site UI.
- **Real test sites for smoke.** The smoke step needs a URL whose discovery actually returns candidates. The dev fixture's Lil Sluggers URL is a safe bet, or any local static-HTML site. If the chosen test site has no discoverable schedule pages, the smoke verifies the error path (still valuable but doesn't close criterion #1) — pick a known-good URL.

## Out of scope (explicit non-goals)

- Backend API changes
- DELETE-site UI
- Browser-nav guards (`useBlocker`)
- Re-discover preserving previously-selected candidates from a prior discover
- Custom kind-selector styling
- "Add another site" success state
- Site templates / presets

## After this lands

Master §10 terminal criteria status:
- 7 of 8 met (after Phase 6-1/3/4)
- **8 of 8 met** (after this)
- Criterion #4 (30-day observation) becomes runnable — kicks off Phase 9.
