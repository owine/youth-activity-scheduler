# Phase 5a — Read-Only Web Dashboard

**Status:** design approved, ready for implementation plan
**Date:** 2026-04-24
**Depends on:** Phase 4 merged (2026-04-24, commit `15f0f95` on `main`)
**Succeeds into:** Phase 5b (Add Site wizard + mutation UIs + alert ack/dismiss)

## 1. Purpose and scope

Phase 5a ships the first web UI for Youth Activity Scheduler: a read-only single-page application that surfaces what Phases 1–4 have been quietly accumulating in the database. It turns the project from "API + cron worker + digest emails" into "something you can look at in a browser during your weekly glance."

The app targets a single admin using a shared desktop browser on a trusted network. There is no authentication, no multi-tenant model, no mobile-first responsive layout. One household, 1–3 kids, ~5–20 tracked sites.

### 1.1 In scope

- Global **Inbox** landing page: digest-style sections for alerts, new matches by kid, and site activity. Mirrors the structure of the Phase 4 daily digest email.
- **Kid detail** views (one section per kid) with two read-only tabs: **Matches** (cards grouped by registration/start-date urgency) and **Watchlist**.
- **Sites** list and per-site detail (including recent crawl history).
- **Settings** view: household config, alert routing table, and a placeholder for notifier channel configs (secrets not exposed in 5a).
- System-matching **light/dark theme** with a user override toggle, persisted to `localStorage`.
- Single-container production deploy: FastAPI serves the built SPA from `/app/static/` at `/`, with `/api/*` unchanged.
- Two new read-only backend endpoints (§4) that aggregate data the existing per-resource routes can't deliver in one round-trip.

### 1.2 Out of scope — deferred to later slices

These would bloat the spec and the delivery. Each has a clean boundary.

- **Any mutation UI.** No forms that POST, PATCH, or DELETE. Phase 5b.
- **Add Site wizard.** Wraps `POST /api/sites/{id}/discover` into a guided multi-step flow. Phase 5b.
- **Alert acknowledgement / dismissal.** Requires new backend endpoints plus mutation UI. Phase 5b.
- **Calendar view.** Non-trivial layout problem (overlapping events, multi-kid overlays). Phase 5c+.
- **SSE / async job progress.** Only needed when the wizard lands. Phase 5b.
- **Authentication.** App continues to assume trusted network, same as the existing API.
- **Mobile-first layout.** Desktop-first with basic responsiveness (sidebar collapses at narrow widths); no dedicated mobile views.
- **Notifier config editing or masked-secret display.** Deferred to 5b to avoid the "mask on GET vs redact vs never return" decision during 5a.

## 2. Architecture

### 2.1 Tech stack (decided)

- **Vite + React 19 + TypeScript** — single-page application, served as a static bundle in production.
- **Tailwind CSS + shadcn/ui** — shadcn is copy-pasted components (owned in-tree, not a dependency), built on Radix primitives for accessibility. Matches the admin-console aesthetic.
- **TanStack Query** for server state (caching, polling, focus-based refetch).
- **TanStack Router** with file-based routing, typed search params.
- **Theme:** CSS variables driven by `prefers-color-scheme`, with a user-override toggle stored in `localStorage`.
- **Single-container prod:** multi-stage Dockerfile; Node image builds `frontend/dist/`, Python image copies it in, FastAPI serves via `StaticFiles(html=True)`. No separate web server.

### 2.2 Repository layout

A new top-level `frontend/` directory, parallel to `src/`.

```
frontend/
  package.json
  tsconfig.json
  vite.config.ts          # proxies /api and /healthz to :8080 in dev
  tailwind.config.ts
  postcss.config.js
  index.html
  src/
    main.tsx              # entry; wires TanStack Router + Query providers + ThemeProvider
    routes/               # file-based routing (TanStack Router convention)
      __root.tsx          # shell: top bar + kid switcher + outlet
      index.tsx           # Inbox
      kids.$id.matches.tsx
      kids.$id.watchlist.tsx
      sites.index.tsx
      sites.$id.tsx
      settings.tsx
    components/
      ui/                 # shadcn primitives: button, card, sheet, tabs, skeleton, badge, …
      layout/             # AppShell, TopBar, KidSwitcher, ThemeToggle
      inbox/              # AlertsSection, NewMatchesByKidSection, SiteActivitySection
      matches/            # UrgencyGroup, MatchCard, MatchDetailDrawer, MatchFilters
      sites/              # SiteList, SiteRow, SiteDetail, CrawlHistoryList
      alerts/             # AlertRow, AlertDetailDrawer, AlertTypeBadge
    lib/
      api.ts              # typed fetch wrappers; throws on non-2xx
      queries.ts          # TanStack Query hooks (useInboxSummary, useKid, useMatches, …)
      theme.ts            # prefers-color-scheme + localStorage override
      format.ts           # price, rel_date, fmt — mirrors Phase 4 Jinja filters
      types.ts            # API response types (Alert, Match, Kid, Site, InboxSummary)
    styles/
      globals.css         # Tailwind base + shadcn CSS variable theme tokens
    test/
      setup.ts            # Vitest + MSW bootstrap
  e2e/                    # Playwright specs
    inbox.spec.ts
    kid-matches.spec.ts
    deep-link.spec.ts
  public/
    favicon.svg
```

### 2.3 Production deploy

Multi-stage `Dockerfile` changes:

```dockerfile
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build  # emits /build/dist

FROM python:3.12-slim AS app
# ... existing python install ...
COPY --from=frontend-build /build/dist /app/static
# existing CMD unchanged; FastAPI app factory mounts /app/static
```

FastAPI changes (`src/yas/web/app.py`):

- Mount `StaticFiles(directory="/app/static", html=True)` at `/` after all API routers are registered. With `html=True`, requests for `/` return `index.html`.
- Add a catch-all route at the end that returns `/app/static/index.html` for any GET not matching `/api/*`, `/healthz`, `/readyz`, or a static asset. Required so TanStack Router deep links (e.g., `/kids/1/matches`) work on page refresh. Implementation: register last, matches `{full_path:path}`, returns `FileResponse("/app/static/index.html")` when the path doesn't map to a static asset.
- Order invariant (asserted by a test): API routes resolve before the SPA fallback.

### 2.4 Dev loop

- **Backend:** existing `python -m yas api` (port 8080) or `docker compose up`.
- **Frontend:** `cd frontend && npm run dev` → Vite dev server on port 5173 with proxy config:
  ```ts
  // vite.config.ts
  server: {
    proxy: {
      '/api':     { target: 'http://localhost:8080', changeOrigin: true },
      '/healthz': { target: 'http://localhost:8080', changeOrigin: true },
      '/readyz':  { target: 'http://localhost:8080', changeOrigin: true },
    },
  }
  ```
- Hot reload on both sides; no Docker rebuild required during dev.

### 2.5 State model

TanStack Query is the only client-side "state manager".

- **Server state** lives in the Query cache. Every API call goes through a query hook in `src/lib/queries.ts`.
- **URL state** (filters, active tab, detail-drawer target) lives in TanStack Router search params. Typed via zod schemas on each route.
- **Ephemeral UI state** (drawer open/close, hover, optimistic flags) uses plain React `useState`.

No Redux. No Zustand. No Context outside of Query/Router/Theme providers.

**Query defaults:**

```ts
new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: true,
      retry: 2,
    },
  },
});
```

**Per-view overrides:**

- Inbox: `refetchInterval: 60_000` (keeps the "what's new" view near-live without being chatty).
- Kid, Sites, Settings: focus-refetch only.

## 3. Pages

### 3.1 Inbox — `/`

**Layout (per mockup A, "digest-style sections"):**

- Header: "What's new this week · Since Apr 17 · 2 kids · 8 sites tracked"
- **Alerts (N)** — list of rows, most-recent first, typed with coloured badges (`watchlist_hit`, `reg_opens_1h`, `crawl_failed`, etc.). Click a row → opens `AlertDetailDrawer` (shadcn `Sheet`, slides from right). Drawer does not navigate away; preserves the Inbox underneath for fast scan-through.
- **New Matches (N)** — one card per kid showing "{N} new · {M} opening soon". Click a card → navigates to `/kids/:id/matches`.
- **Site activity** — three-line summary: "6 sites refreshed · 2 posted new schedules · 1 stagnant". Click "stagnant" → `/sites` pre-filtered.

**Data:** single `GET /api/inbox/summary?since=<ts>&until=<ts>`. Window defaults to 7 days; adjustable via URL search param (`?days=7`, `?days=30`). See §4.1 for response shape.

**Empty states:**

- No alerts in window → "No alerts this week. Quiet is good."
- No new matches → "No new matches. Stagnant detection runs nightly."
- No site activity → omit the section entirely.

### 3.2 Kid — `/kids/:id/*`

**Shared shell:** kid header (name, age-at-today, total matches, N opening soon) above the tab bar. Tabs: **Matches**, **Watchlist**. Selected tab reflected in URL; tab switch is `<Link>` navigation, not JS state.

**Kid switcher** in top bar shows all kids as pills; current one is active. Clicking another kid navigates to the same tab under that kid (`/kids/2/matches` if on matches).

#### 3.2.1 Matches — `/kids/:id/matches` (default)

**Layout (per mockup B, "cards grouped by urgency"):**

- Three collapsible groups, ordered:
  1. **Registration opens this week** — matches whose linked offering has `registration_opens_at` in `[today, today+7d]`.
  2. **Starting in ≤ 14 days** — matches whose offering has `start_date` in `[today, today+14d]`, excluding those already in group 1.
  3. **Later this season** — everything else.
- Each group header shows count + a collapse chevron. Expanded-by-default for 1 and 2; collapsed for 3.
- Each card: title, site, start date, price, score. Score shown small, right-aligned. Reg-opens-soon cards get a subtle coloured border (`border-destructive/30` in shadcn token terms).
- Click a card → `MatchDetailDrawer` with the full `reasons` breakdown (gates, watchlist_hit, distance miles, score components).
- Filter bar above the first group: min score slider, site filter dropdown, date-range picker. Filters are URL search params; hitting refresh preserves them. Clear-all link when any filter is active.

**Data:** `GET /api/matches?kid_id=N` + `GET /api/kids/:id` for header. Client-side grouping based on `offering.registration_opens_at` and `offering.start_date` fields already returned by the matches endpoint.

#### 3.2.2 Watchlist — `/kids/:id/watchlist`

**Layout:** simple list. Each entry shows: site (or "(any)" if site_id is null), pattern, priority, notes, active toggle (read-only display), "ignores hard gates" flag, and a count of current matches that hit this entry.

**Data:** `GET /api/kids/:id` returns embedded `watchlist` (per existing kids_schemas). The match-count per entry may require a small client-side group-by on `GET /api/matches?kid_id=N`; if the grouping is awkward in the client, extend the watchlist shape server-side with a `current_match_count` field as a refinement (decision during implementation planning, not here).

### 3.3 Sites — `/sites`, `/sites/:id`

**List (`/sites`):**

- Table: name, adapter (llm/deterministic), # pages, last crawled (relative: "2h ago"), next check (relative: "in 4h"), muted status.
- Default sort: last-crawled desc.
- Click a row → site detail.
- Top bar: filter chip "Stagnant only" (pre-filters to sites whose newest page hasn't changed in the configured stagnant window).

**Detail (`/sites/:id`):**

- Header: name, base URL, adapter.
- Pages list: each page's URL, kind, last fetched, next check.
- Recent crawl history: last 10 crawls with timestamp, status, result summary.
- No edit controls in 5a.

**Data:**

- `GET /api/sites` — existing.
- `GET /api/sites/:id` — existing (may need `include_pages=true`; confirm during planning).
- `GET /api/sites/:id/crawls?limit=10` — **new** (§4.2).

### 3.4 Settings — `/settings`

**Content (all read-only):**

- Household section: home address, home location name, default max distance (mi), digest time, quiet hours start/end, daily LLM cost cap.
- Alert routing table: one row per `AlertType`, showing channels list and enabled flag.
- Notifier configuration: **placeholder card** stating "Channel configuration available in Phase 5b." No secrets exposed in 5a.

**Data:** `GET /api/household`, `GET /api/alert_routing`. No new endpoints.

## 4. Backend changes

All additions are read-only. Existing behavior unchanged.

### 4.1 `GET /api/inbox/summary?since=<ts>&until=<ts>`

**New endpoint.** Aggregates everything the Inbox page needs in one round-trip.

**Query params:**

- `since` (ISO 8601, required) — inclusive lower bound on `alerts.scheduled_for` and `matches.computed_at`.
- `until` (ISO 8601, required) — exclusive upper bound on same.

If either is malformed → 422 via FastAPI default.

**Response (Pydantic `InboxSummaryOut`):**

```json
{
  "window_start": "2026-04-17T00:00:00+00:00",
  "window_end": "2026-04-24T00:00:00+00:00",
  "alerts": [
    {
      "id": 42,
      "type": "reg_opens_1h",
      "kid_id": 1,
      "kid_name": "Sam",
      "offering_id": 17,
      "site_id": 3,
      "channels": ["email", "pushover"],
      "scheduled_for": "...",
      "sent_at": "...",
      "skipped": false,
      "dedup_key": "...",
      "payload_json": { "offering_name": "Spring T-Ball", "registration_url": "..." },
      "summary_text": "Registration opens in 1 hour — Spring T-Ball for Sam · Lil Sluggers"
    }
  ],
  "new_matches_by_kid": [
    { "kid_id": 1, "kid_name": "Sam", "total_new": 7, "opening_soon_count": 2 },
    { "kid_id": 2, "kid_name": "Maya", "total_new": 5, "opening_soon_count": 0 }
  ],
  "site_activity": {
    "refreshed_count": 6,
    "posted_new_count": 2,
    "stagnant_count": 1
  }
}
```

**Semantics:**

- `alerts` — `alerts` rows where `scheduled_for IN [since, until)`, ordered by `scheduled_for DESC`, limit 50. Includes skipped alerts (the UI distinguishes them with a badge).
- `summary_text` — one-line human summary composed server-side so the client doesn't need to understand every alert type's payload shape. Built from `type` + `payload_json` via a small dispatch table; mirrors the template logic already used by the digest builder.
- `new_matches_by_kid` — one row per active kid. `total_new` = count of `matches` rows with `computed_at IN [since, until)` for that kid. `opening_soon_count` = subset whose linked offering has `registration_opens_at` within the window.
- `site_activity.refreshed_count` — distinct sites with at least one successful crawl in the window.
- `site_activity.posted_new_count` — sites with at least one `schedule_posted` alert in the window.
- `site_activity.stagnant_count` — sites currently flagged stagnant by the existing detector (reuse `yas.alerts.detectors.site_stagnant`).

**Tests:** happy path with seeded data, empty window, one-kid household, malformed timestamp (422), window that crosses zero data.

### 4.2 `GET /api/sites/{id}/crawls?limit=10`

**New endpoint.** Returns the most recent `N` crawl attempts for one site. 404 if the site doesn't exist.

**Response:** `list[CrawlOut]` with `{id, page_id, started_at, finished_at, status, fetched_bytes, error_message}`.

**Semantics:** reads the existing `crawls` table added in Phase 2, no schema changes. `limit` defaults to 10, max 100.

**Tests:** happy path, unknown site (404), limit validation, empty history.

### 4.3 SPA fallback wiring

Not an endpoint, but a route-order invariant in `src/yas/web/app.py`:

1. All `/api/*` routers registered first (unchanged).
2. `/healthz`, `/readyz` (unchanged).
3. `StaticFiles(directory=..., html=True)` mounted at `/`.
4. Catch-all: any GET path that didn't match above returns `FileResponse("/app/static/index.html")`. Implementation pseudocode:
   ```python
   @app.get("/{full_path:path}", include_in_schema=False)
   async def spa_fallback(full_path: str) -> FileResponse:
       return FileResponse(STATIC_DIR / "index.html")
   ```
5. **Invariant test:** hit `/api/kids` → JSON (not HTML); hit `/kids/1/matches` → HTML; hit `/api/nonexistent` → 404 JSON (not the SPA shell).

### 4.4 Explicit non-changes

- `HouseholdOut` is NOT extended with notifier config fields in 5a. Settings page shows the placeholder. Adding masked configs is a 5b decision.
- No new mutation endpoints. No changes to existing endpoints' response shapes.

## 5. Engineering details

### 5.1 Testing

**Backend (new endpoints in this phase):**

- `tests/integration/test_api_inbox.py` — happy path, empty window, one-kid, malformed timestamp, zero site activity.
- `tests/integration/test_api_site_crawls.py` — happy path, unknown site, limit bounds, empty history.
- `tests/integration/test_spa_fallback.py` — API route precedence, deep-link returns HTML, unknown API path returns 404 JSON.

**Frontend unit (Vitest + React Testing Library + MSW):**

- One spec per non-trivial component: `AlertsSection`, `NewMatchesByKidSection`, `SiteActivitySection`, `UrgencyGroup`, `MatchCard`, `MatchFilters`, `MatchDetailDrawer`, `SiteRow`, `CrawlHistoryList`.
- Query hooks in `lib/queries.ts` tested against MSW handlers; verify that each hook requests the right URL and handles 4xx/5xx with an error state.
- Theme: `ThemeToggle` flips the `html` class and persists to `localStorage`; system-preference mode reads `matchMedia`.

**Frontend e2e (Playwright):**

- `e2e/inbox.spec.ts` — open `/`, see seeded inbox content, click an alert row → drawer opens with alert details, close drawer → inbox preserved.
- `e2e/kid-matches.spec.ts` — from inbox, click the "Sam · 7 new" card → lands on `/kids/1/matches`, urgency groups render with seeded matches, click a card → detail drawer shows reasons.
- `e2e/deep-link.spec.ts` — cold-load `/kids/1/matches` via the Playwright `page.goto`; SPA fallback serves index, React app boots, matches render. (Validates the catch-all route.)

E2E harness: a new `scripts/e2e_phase5a.sh` that (1) builds both images, (2) brings up the compose stack with a seeded-DB sidecar, (3) runs `playwright test` against it, (4) tears down. Pattern mirrors `scripts/smoke_phase4.sh`.

### 5.2 Error and loading states

- Every query hook exposes `isLoading`, `isError`, `error`, `refetch`.
- **Loading:** shadcn `Skeleton` shaped like the final content for each section/card/row. Not a generic spinner.
- **Error:** `<ErrorBanner>` component (new, in `components/ui/`) with message + Retry button that calls `refetch()`. Matches shadcn `Alert` styling.
- **Global ErrorBoundary** at `__root.tsx` for thrown React errors (not network errors). Shows "Something went wrong" + reload prompt.
- **No silent failures.** Every `isError` branch renders something visible. This matches the Phase 4 codebase rule.

### 5.3 Accessibility

- Rely on shadcn/ui (Radix) for ARIA correctness on primitives; don't re-implement.
- Drawer: focus trap, Escape closes, initial focus on close button.
- Nav: `<Tab>` order follows reading order; all interactive elements are keyboard-reachable.
- Colour contrast: use shadcn's default theme tokens; both light and dark pass WCAG AA by default. Custom colours require verifying with a contrast checker.
- Every icon-only button has an `aria-label`.

### 5.4 Theming

- `ThemeProvider` in `main.tsx` manages three states: `system`, `light`, `dark`. Applies `class="dark"` to `<html>` when resolved theme is dark.
- Resolved theme is `system` by default; user toggle switches between the three. Persisted to `localStorage["yas-theme"]`.
- CSS tokens defined once in `styles/globals.css` using shadcn's convention (`--background`, `--foreground`, `--primary`, etc., with `:root` and `.dark` overrides).
- No FOUC: theme resolution runs in a `<script>` tag in `index.html` before React hydrates.

### 5.5 Data formatting

Mirror the Phase 4 Jinja filter semantics so the UI matches digest emails:

- `price(value)` — `None` / negative → empty; `0` → "Free"; else "$X.XX".
- `relDate(date)` — "Today" / "Tomorrow" / "in N days" (≤ 6) / "Sat May 2" (within current week+3mo) / absolute date.
- `fmt(datetime)` — "Wed 9:00 AM · May 6".

Implement in `src/lib/format.ts`. Testable without components.

### 5.6 Tooling

- **ESLint** with `@typescript-eslint`, React Hooks plugin.
- **Prettier** with shadcn's config.
- **Scripts in `frontend/package.json`:** `dev`, `build`, `preview`, `test`, `test:watch`, `lint`, `typecheck`, `format`.

### 5.7 Phase 5a exit gates

Existing Python gates (no change):

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src`
- `uv run pytest` (including new `tests/integration/test_api_inbox.py`, `test_api_site_crawls.py`, `test_spa_fallback.py`)

New frontend gates:

- `npm --prefix frontend run lint`
- `npm --prefix frontend run typecheck`
- `npm --prefix frontend run test`
- `npm --prefix frontend run build` — must succeed, emitting `frontend/dist/`.

New integration gate:

- `scripts/e2e_phase5a.sh` — runs the Playwright suite against a full Dockerized stack.

All gates green before merging to `main` via `--no-ff`.

## 6. Risks and open questions

### 6.1 Risks

- **The `/api/inbox/summary` query is a multi-table aggregate.** On a lightly-populated dev DB it's fine; with real data over months it could become the slowest endpoint. Mitigation: integration test includes a timing assertion (< 200ms on 10k alerts / 10k matches seeded); if violated, add targeted indexes.
- **Detail drawer on top of a polling page.** The Inbox refetches every 60s. If a user has the alert drawer open and the underlying list refetches, the selected alert could shift position or disappear. Mitigation: drawer reads from a cached-by-id query hook, independent of the list query; drawer stays populated even if the alert drops off the window.
- **Bundle size.** shadcn + Radix + TanStack Query + Router is modest but not tiny. Target: ≤ 300KB gzipped for the initial JS payload. Vite's analyze plugin runs in CI; if exceeded, the plan adds code-splitting per route.
- **Browser caching of `index.html`.** If `index.html` is cached, users won't see new SPA versions after a deploy. Mitigation: FastAPI returns `Cache-Control: no-cache` on `index.html` and `public, max-age=31536000, immutable` on hashed static assets (Vite emits hashed filenames by default).

### 6.2 Open questions (resolved during implementation planning, not now)

- Whether `GET /api/sites/:id` needs an `include_pages=true` flag or whether the existing response already includes pages.
- Whether `WatchlistOut` should grow a `current_match_count` field server-side, or the client should derive it from `/api/matches?kid_id=N`.
- Whether to use Vitest's `happy-dom` or `jsdom` environment (happy-dom is faster; jsdom has broader API coverage).

## 7. Success criteria

Phase 5a is done when:

- All exit gates in §5.7 pass.
- A cold `git clone` + `docker compose up` surfaces the app at `http://localhost:8080/`, renders the Inbox, navigates to a kid, displays matches, and deep-links work on refresh.
- The Playwright smoke passes on CI.
- The written readme section ("Web UI") explains how to start the dev loop (both FastAPI + Vite) and how to run the e2e suite.

When these land, merge to `main` with `--no-ff` and proceed to Phase 5b (Add Site wizard + mutation UIs).
