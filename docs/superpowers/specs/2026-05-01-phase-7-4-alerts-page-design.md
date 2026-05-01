# Phase 7-4 — Alerts Page Design (Outbox + Digest Preview)

**Date:** 2026-05-01
**Status:** Spec
**Author:** Claude + owine
**Closes:** Master §7 page #8 (Alerts: outbox, resend, digest preview)
**Roadmap:** `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md` (Phase 7-4)

## Goal

Add a new top-level `/alerts` page with two tabs:
- **Outbox** — paginated list of all alerts (beyond the inbox's last-24h window) with filters, status, channels, and a resend button.
- **Digest preview** — per-kid iframe-rendered preview of the next scheduled digest email.

After this lands, master §7 page #8 closes — completing all 9 master §7 pages and finishing Phase 7.

## Scope

**In scope:**
- Backend: extend `AlertOut` with `summary_text: str` (composed server-side, mirrors `InboxAlert.summary_text`); add `GET /api/digest/preview?kid_id=N` endpoint.
- Frontend: new `/alerts` route with internal tab routing (Outbox + Digest preview); 4 new components; 2 new query hooks; 1 new mutation hook; nav link.
- ~22 frontend tests + ~4 backend tests.

**Out of scope:**
- Cross-kid combined digest preview. The backend builder is per-kid; v1 honors that.
- Historical digest viewer. The outbox lists past digest alerts with metadata; rendering a historical one's HTML body is a future polish item.
- Cursor-based pagination. v1 uses limit/offset which is fine for ≤500 alerts.
- Resend confirmation dialog. The button just posts; existing inbox close pattern doesn't gate either.
- Bulk operations (multi-select close/resend).
- Multi-kid filter on outbox. Backend's `kid_id` query param is single-value; v1 honors that. Future-extensible to `kid_ids: list[int]` if useful.
- Custom date-range presets ("last 7 days", "last month"). Plain `since`/`until` date inputs only.
- Export-to-CSV.

## Background

The backend `/api/alerts` endpoint suite is already implemented:

- `GET /api/alerts` with filters `kid_id`, `type`, `status` (`pending|sent|skipped`), `since`, `until`, `limit` (1–500, default 25), `offset` (≥0). Sorted by `id` desc. Returns `AlertListResponse {items, total, limit, offset}`.
- `GET /api/alerts/{id}` — single alert.
- `POST /api/alerts/{id}/resend` — clones the alert with a new `dedup_key` and `scheduled_for=now()`. The worker picks it up.
- `POST /api/alerts/{id}/close` + `/reopen` — close lifecycle (Phase 5b-1a).

`AlertOut` returns full `payload_json` plus IDs (no embedded names). The existing `InboxAlert.summary_text` shows the pattern we'll mirror: server composes a human-readable summary at query time.

The backend digest pipeline (verified function names + signatures):
- `yas.alerts.digest.builder.gather_digest_payload(session, kid, *, window_start, window_end, alert_no_matches_kid_days, now=None) -> DigestPayload` — takes an active `AsyncSession`, a fully-loaded `Kid` ORM instance (not just an ID), an explicit time window, and a `alert_no_matches_kid_days` threshold sourced from settings.
- `yas.alerts.digest.llm_summary.generate_top_line(payload, llm, *, cost_cap_remaining_usd) -> str` — takes the payload, an `LLMClient | None`, and a remaining-budget float. Falls back to a deterministic template when `llm` is `None`.
- `yas.alerts.digest.builder.render_digest(payload, top_line) -> tuple[str, str]` — **returns `(plain_str, html_str)`** in that order (plain first, HTML second). The endpoint must respect this tuple order.

There is no HTTP endpoint for the digest pipeline today. Phase 7-4 adds one.

The summary-text helper for alerts is already exported: `yas.web.routes.inbox_alert_summary.summarize_alert` is a pure importable function that handles all 11 `AlertType` branches (including system alerts without kid_id/offering_id). Phase 7-4 reuses it directly — no duplication.

The frontend already has the inbox at `/` (`useInboxSummary`, default 7-day window per `frontend/src/lib/queries.ts`). No outbox or alerts route exists.

## Decisions

### D1: Single `/alerts` route with internal tabs (not two routes)

Master §7 page #8 — "Alerts: outbox, resend, digest preview" — is one logical page. We use one route `/alerts` with two tabs (`?tab=outbox` default, `?tab=digest`). Tab state lives in URL search param so reloads + back-button preserve view.

Two-route alternative (`/alerts/outbox` + `/alerts/digest`) doubles route count for two halves of the same page. Extending the existing inbox `/` mixes "what needs my attention NOW" with archival/preview tasks — wrong scope.

### D2: Server-composed `summary_text` on `AlertOut`, reusing `summarize_alert`

Three patterns considered:
- **A. Server-composed `summary_text`** — backend reads kid + offering + site joins at query time, composes "T-Ball Spring 2026 — Sam". Frontend renders the string.
- **B. Embedded structures** — extend `AlertOut` with optional `kid_name`, `offering_summary`, `site_name`. More backend; more frontend formatting.
- **C. Frontend-only resolution** — `useKids()` + per-row `useOffering` (N+1).

Pattern A wins because:
- The existing `InboxAlert.summary_text` already proves the pattern works for our use case.
- Zero N+1, simple frontend, narrow backend extension.
- We don't need flexible formatting; the user just wants to identify the alert.

**The composition helper already exists.** `yas.web.routes.inbox_alert_summary.summarize_alert` is a pure, importable function used by `inbox.py` to build `InboxAlert.summary_text`. It handles all 11 `AlertType` branches including system alerts (`crawl_failed`, `push_cap`, etc.). Phase 7-4 imports and calls it directly — no duplication, no risk of drift between the two summaries.

The function takes the alert + relevant entity dicts (kid name, offering name, site name) and returns the composed string. The `list_alerts` / `get_alert` handlers will join Kid + Offering + Site at query time and pass the resolved names to `summarize_alert` per row.

### D3: Filter state + tab + page in URL search params (untyped strings)

URL state for: `?tab=outbox|digest`, `?kid=N` (single integer for v1, see D4), `?type=alert_type` (single for v1; backend supports single value), `?status=pending|sent|skipped`, `?since=YYYY-MM-DD`, `?until=YYYY-MM-DD`, `?page=0` (offset = page × pageSize), `?kid_digest=N` (digest preview kid).

**Implementation: untyped string params, NOT `validateSearch`.** This codebase has zero precedent for TanStack Router's typed search schema (no `useSearch`/`validateSearch` usages anywhere). Phase 7-4 keeps it simple:

- The route reads search params via `Route.useSearch()` returning `Record<string, string | undefined>`.
- A small per-component helper parses the string params into the typed `OutboxFilterState` (Number-coerce `kid`, validate against allowed `status` literals, etc.); invalid values become null/default.
- Updates use `navigate({ search: { ...current, kid: '5' } })` with explicit string values.

This matches the codebase's "small, focused" idiom over heavy framework features. If multiple future routes need typed params, an extraction can introduce `validateSearch`. v1 doesn't.

Reload + back-button + share-by-link all work. Different from Phase 7-2 (which used localStorage) because alerts is a more "I want to send this query to a teammate" surface, even though we have one user. The URL approach is also slightly less code than localStorage hydration (no first-mount race).

### D4: Single-kid filter for v1

Backend's `list_alerts` `kid_id` query param is a single integer (`Annotated[int | None, Query()]`). v1 frontend matches: kid filter is a single-select dropdown / radio chip group, not multi-select. If multi-kid filtering bites, future polish adds `kid_ids: list[int]` on the backend + multi-select on the frontend. This is the same constraint as the existing backend; no new contract.

(The digest-preview tab uses a separate kid picker for which kid to render the preview for — not a filter.)

### D5: Pagination = limit/offset with Prev/Next buttons

Backend supports `limit≤500, offset`. v1 uses `limit=25` per page; URL `?page=N` translates to `offset=N*25`. Prev/Next buttons; Prev disabled at page 0; Next disabled when `offset + items.length >= total`.

Cursor-based pagination is over-engineered for ≤500 alerts.

### D6: Digest preview = next-scheduled, rendered as iframe

`GET /api/digest/preview?kid_id=N` returns `{html: string, plain: string, top_line: string}`.

**Endpoint flow** (concrete, since the actual function names are different from earlier draft):

```python
# src/yas/web/routes/digest_preview.py (sketch)
@router.get("", response_model=DigestPreviewOut)
async def get_digest_preview(kid_id: int, request: Request) -> DigestPreviewOut:
    settings = request.app.state.yas.settings
    async with session_scope(_engine(request)) as s:
        kid = (await s.execute(select(Kid).where(Kid.id == kid_id))).scalar_one_or_none()
        if kid is None:
            raise HTTPException(404, f"kid {kid_id} not found")
        now = datetime.now(UTC)
        window_start = now - timedelta(days=1)  # 24h window for preview
        window_end = now
        payload = await gather_digest_payload(
            s, kid,
            window_start=window_start,
            window_end=window_end,
            alert_no_matches_kid_days=settings.alert_no_matches_kid_days,
            now=now,
        )
    # Force template fallback for the preview top-line so the preview never
    # bills against the household's daily LLM cap. If we want LLM previews
    # later, source request.app.state.yas.llm + a dedicated preview budget.
    top_line = await generate_top_line(payload, llm=None, cost_cap_remaining_usd=0.0)
    plain, html = render_digest(payload, top_line)  # NOTE: order is (plain, html)
    return DigestPreviewOut(html=html, plain=plain, top_line=top_line)
```

Key correctness points (each was a draft-spec mistake the reviewer caught):

- `gather_digest_payload` takes the **`Kid` ORM instance** (not the int id) and an active `AsyncSession`; the route must look up the kid first (404 on miss) and pass the loaded ORM.
- `generate_top_line` requires an `llm: LLMClient | None` argument. v1 passes **`llm=None`** to force the deterministic template fallback — preview should never bill against the household's daily LLM cost cap. (Future polish: thread `request.app.state.yas.llm` through with a dedicated preview budget.)
- `render_digest` returns the tuple as **`(plain, html)`** — plain first, HTML second. The endpoint must unpack in that order.
- 24-hour preview window is hardcoded for v1; the existing inbox is configurable (default 7d) but preview is always "what would land if we sent it right now."

Frontend renders:
- Top line as plain text above the iframe.
- HTML body in `<iframe srcDoc={html} sandbox="allow-same-origin" className="w-full h-[600px] rounded border border-border" title="Digest preview" />`.

`sandbox="allow-same-origin"` lets `<style>` blocks work without enabling scripts. Fixed 600px height for v1; future polish can add postMessage-based auto-resize.

Why "next scheduled" over "historical"? The user's actual question for "preview" is "what's about to land in my inbox?" The outbox already lists past digest alerts with metadata. A historical-render endpoint is a future polish item.

### D7: Resend button = direct POST, no confirmation dialog

The existing inbox-close UI (Phase 5b-1b) doesn't gate destructive-ish actions with confirms. Resend is also non-destructive (clones an existing row; doesn't delete). Direct POST → invalidate `['alerts']` cache → new cloned alert appears at top of the list on next render.

If users frequently click resend by accident, future polish can add a 3s undo banner.

### D8: Filter for "open" state inherited from close lifecycle (Phase 5b-1a)

The Phase 5b-1a closure mechanic (close_reason: acknowledged|dismissed|null) lives on the alert. Users may want to filter by open vs closed in the outbox. v1 does NOT add this filter to keep filter chrome minimal; the inbox `/` is for open alerts, the outbox `/alerts` shows everything. If the user wants to filter to only-open alerts, they can re-use the inbox view.

If this turns out to be missed, a future polish adds `?closed=open|closed|any`.

### D9: Empty / loading / error states

- **Outbox empty (no matches to filters):** "No alerts match your filters." plus "Clear filters" button (resets URL params to defaults).
- **Outbox loading:** `<Skeleton className="h-32 w-full" />`.
- **Outbox error:** `<ErrorBanner message="Failed to load alerts" onRetry={refetch} />`.
- **Digest preview empty (no kids):** "Add a kid first" with link to `/kids/new`.
- **Digest preview loading:** `<Skeleton />`.
- **Digest preview error:** `<ErrorBanner ... />`.
- **Digest preview when LLM unavailable:** backend's template fallback in `llm_summary.py` ensures the endpoint never errors on LLM unavailability. Frontend has no special branch.
- **Digest preview when no recent activity:** backend's `gather_digest_payload` produces an empty payload; renderer outputs HTML with empty-state copy. No special frontend branch.

### D10: Resend success feedback = inline pill, not a global toast

The codebase doesn't have a toast system. Resend success → render a small green "Resend queued" pill on the row for ~3 seconds (component-local state with `setTimeout`). On error → red pill with detail. Mirrors the `<TestSendButton>` pattern from Phase 7-1.

## Architecture

### Routes

| Route | Component | Purpose |
|---|---|---|
| `/alerts` (new) | `AlertsPage` (route shell) | Reads `?tab=outbox|digest`; renders `<OutboxPanel>` or `<DigestPreviewPanel>`. |

Top-banner nav: add "Alerts" link between Inbox and Sites with an icon (e.g. `lucide-react`'s `Mail` or `Send`).

### Components

```
AlertsPage (route)
├── tab nav (Outbox | Digest preview)
└── (one of:)
    ├── OutboxPanel
    │   ├── OutboxFilterBar
    │   ├── OutboxRow × N
    │   └── pagination buttons
    └── DigestPreviewPanel
        ├── kid picker
        ├── top-line text
        └── <iframe srcDoc>
```

### Hooks

```ts
// queries.ts
export function useAlerts(filters: OutboxFilterState, pageSize = 25) {
  return useQuery({
    queryKey: ['alerts', filters],
    queryFn: () => api.get<AlertListResponse>(`/api/alerts?${serialize(filters)}&limit=${pageSize}&offset=${filters.page * pageSize}`),
  });
}

export function useDigestPreview(kidId: number | null) {
  return useQuery({
    queryKey: ['digest', 'preview', kidId],
    queryFn: () => api.get<DigestPreviewResponse>(`/api/digest/preview?kid_id=${kidId}`),
    enabled: kidId != null && Number.isFinite(kidId) && kidId > 0,
  });
}

// mutations.ts
export function useResendAlert() {
  const qc = useQueryClient();
  return useMutation<Alert, Error, { alertId: number }>({
    mutationFn: ({ alertId }) => api.post<Alert>(`/api/alerts/${alertId}/resend`, {}),
    onSettled: async () => {
      await qc.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
}
```

### Files

**Modify — backend:**
- `src/yas/web/routes/alerts_schemas.py` — add `summary_text: str` to `AlertOut`.
- `src/yas/web/routes/alerts.py` — `list_alerts` and `get_alert` import `summarize_alert` from `yas.web.routes.inbox_alert_summary` and call it per row after joining Kid + Offering + Site. Use the same join pattern as `inbox.py`.
- `src/yas/web/app.py` — register the new digest preview router.
- `tests/integration/test_api_alerts.py` — extend with one assertion for `summary_text`.

**Create — backend:**
- `src/yas/web/routes/digest_preview.py` — `GET /api/digest/preview?kid_id=N` calls `gather_digest_payload()` + `generate_top_line()` (with `llm=None` for the v1 template fallback) + `render_digest()` (returns `(plain, html)`).
- `src/yas/web/routes/digest_preview_schemas.py` — `DigestPreviewOut {html: str, plain: str, top_line: str}`.
- `tests/integration/test_api_digest_preview.py` — ~3 tests.

**Modify — frontend:**
- `frontend/src/lib/types.ts` — add `Alert` (full) interface; `OutboxFilterState`, `AlertStatus` union (`'pending'|'sent'|'skipped'`), `DigestPreviewResponse`.
- `frontend/src/lib/queries.ts` — add `useAlerts(filters, pageSize)` + `useDigestPreview(kidId)`.
- `frontend/src/lib/mutations.ts` — add `useResendAlert`.
- `frontend/src/lib/mutations.test.tsx` — extend with `useResendAlert` tests (~2).
- `frontend/src/components/layout/TopBar.tsx` — add "Alerts" link between Inbox and Sites.
- `frontend/src/test/handlers.ts` — defaults for `GET /api/alerts`, `POST /api/alerts/:id/resend`, `GET /api/digest/preview`.
- `frontend/src/routeTree.gen.ts` — regenerated.

**Create — frontend:**
- `frontend/src/routes/alerts.tsx` — thin route shell; reads `?tab=`.
- `frontend/src/components/alerts/OutboxPanel.tsx` + `.test.tsx`
- `frontend/src/components/alerts/OutboxFilterBar.tsx` + `.test.tsx`
- `frontend/src/components/alerts/OutboxRow.tsx` + `.test.tsx`
- `frontend/src/components/alerts/DigestPreviewPanel.tsx` + `.test.tsx`

**No new dependencies.** Reuses `<Card>`, `<Badge>`, `<Button>`, `<Skeleton>`, `<EmptyState>`, `<ErrorBanner>`. The TopBar icon comes from `lucide-react` which is already pinned.

## Outbox layout

```
┌─────────────────────────────────────────────────────────┐
│ Filters: [Kid: any ▾] [Type: any ▾] [Status: any ▾]    │
│         From: [____] To: [____]   [Clear]               │
├─────────────────────────────────────────────────────────┤
│ [type-badge] T-Ball Spring 2026 — Sam        [Resend]   │
│ Apr 30 · sent 8:01 AM · email, ntfy                     │
├─────────────────────────────────────────────────────────┤
│ [type-badge] Soccer Fall 2026 — Alex          [Resend]  │
│ Apr 29 · pending · email                                │
├─────────────────────────────────────────────────────────┤
│         Showing 1–25 of 142    [Prev]  [Next]           │
└─────────────────────────────────────────────────────────┘
```

**Row layout (`<OutboxRow>`):**
- Top line: `<Badge>` for `alert.type` (color-coded; reuse `inbox`'s badge styling if any) | `summary_text` (`flex-1`) | `[Resend]` button.
- Second line (text-xs muted-foreground): `<scheduledFormat>` + status indicator + channels comma-list.
  - Status indicator: `pending` | `sent <relDate(sent_at)>` | `skipped` | (if closed: `closed (<close_reason>)`).
- Resend button calls `useResendAlert.mutate({alertId: alert.id})`. Pill rendered on success/failure (D10).

**Filter bar:**
- All controls write to URL search params via `navigate({ search: ... })` from TanStack Router.
- "Clear" button → navigates with empty search params (just `?tab=outbox`).

**Pagination:**
- Top-right `Showing M–N of TOTAL` indicator.
- `[Prev]` button → `?page=current-1` (disabled at 0).
- `[Next]` button → `?page=current+1` (disabled when next page would be empty).

## Digest preview layout

```
┌─────────────────────────────────────────────────────────┐
│ Kid: [Sam ▾]                                            │
│                                                         │
│ Top-line: "Sam has 3 new soccer matches this week."     │
│                                                         │
│ ┌─ Email preview ─────────────────────────────────────┐ │
│ │ ▼ HTML rendered in iframe (fixed 600px height) ▼   │ │
│ │ ──────────────────────────────────────────────────  │ │
│ │ ...rendered digest body...                          │ │
│ │                                                     │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ ⓘ This is a preview of the next scheduled digest        │
│   based on the last 24 hours of activity.               │
└─────────────────────────────────────────────────────────┘
```

- Kid picker: `<select>` populated from `useKids()`. Default = first kid. Selection writes to URL `?kid_digest=N`.
- Top-line text: `{response.top_line}` rendered above the iframe.
- Iframe: `<iframe srcDoc={response.html} sandbox="allow-same-origin" className="w-full h-[600px] rounded border border-border" title="Digest preview" />`.
- Disclaimer below iframe: "This is a preview of the next scheduled digest based on the last 24 hours of activity." (matches the hardcoded preview window in D6.)

## Data flow

### Outbox

```
URL search params → OutboxFilterState
  ↓
useAlerts(filters)
  → GET /api/alerts?kid_id=...&type=...&status=...&since=...&until=...&limit=25&offset=N
  → AlertListResponse {items, total, limit, offset}
  ↓
Render OutboxRow per item
  ↓
User clicks Resend
  → useResendAlert.mutate({alertId})
  → POST /api/alerts/{id}/resend
  → invalidate ['alerts']
  → list refetches; new alert appears at top
  ↓
User changes filter via OutboxFilterBar
  → navigate({ search: { ...filters, page: 0 } })
  → URL updates → React reads new URL → useAlerts re-runs with new filters
```

### Digest preview

```
URL ?kid_digest=N (or default = first kid from useKids)
  ↓
useDigestPreview(kidId)
  → GET /api/digest/preview?kid_id=N
  → DigestPreviewResponse {html, plain, top_line}
  ↓
Render top_line + <iframe srcDoc={html}>
  ↓
User changes kid via picker
  → navigate({ search: { ..., kid_digest: newKidId } })
  → URL updates → useDigestPreview re-runs with new kidId
```

## Validation

zod schemas not strictly needed since this is mostly read-only display. Form-style validation:

- Date inputs (since/until) accept any valid `<input type="date">` value; backend ISO-parses.
- Filter state types in `frontend/src/lib/types.ts`:

```ts
export type AlertStatus = 'pending' | 'sent' | 'skipped';

export interface OutboxFilterState {
  kidId: number | null;
  type: string | null;        // AlertType union; from existing types.ts
  status: AlertStatus | null;
  since: string | null;       // YYYY-MM-DD
  until: string | null;
  page: number;               // 0-indexed
}

export interface DigestPreviewResponse {
  html: string;
  plain: string;
  top_line: string;
}

export interface Alert {
  id: number;
  type: AlertType | string;
  kid_id: number | null;
  offering_id: number | null;
  site_id: number | null;
  channels: string[];
  scheduled_for: string;
  sent_at: string | null;
  skipped: boolean;
  dedup_key: string;
  payload_json: Record<string, unknown>;
  closed_at: string | null;
  close_reason: CloseReason | null;
  summary_text: string;
}

export interface AlertListResponse {
  items: Alert[];
  total: number;
  limit: number;
  offset: number;
}
```

## Testing

**Frontend test count target:** ~22 new tests, raising 251 → ~273.
**Backend:** ~4 new tests, raising 593 → ~597.

### Backend

`tests/integration/test_api_alerts.py` extension (~1 test):
1. `test_alert_list_includes_summary_text` — create alert with kid + offering; GET `/api/alerts`; assert `items[0].summary_text` is non-empty and contains the offering's name. Assert that for an alert without kid/offering (e.g. system alert), `summary_text` is still a non-empty string.

`tests/integration/test_api_digest_preview.py` (new, ~3 tests):
1. Happy path: seed kid + matches; GET `/api/digest/preview?kid_id=1`; assert response shape `{html, plain, top_line}` non-empty. HTML contains kid name.
2. No matches: kid with no recent matches; assert response still returns valid shape (HTML may say "No matches" or similar empty-state).
3. Unknown kid_id: GET `/api/digest/preview?kid_id=999` → 404.

### Frontend

`mutations.test.tsx` extension (~2 tests):
1. `useResendAlert` happy path: POST `/api/alerts/:id/resend` (capture body — empty), invalidates `['alerts']` cache.
2. `useResendAlert` 500 → rejects.

`OutboxRow.test.tsx` (~4 tests):
1. Renders type badge + summary_text + scheduled-for date.
2. Status indicator: pending / sent <relDate> / skipped / closed branches.
3. Resend button click → fires `useResendAlert` (capture POST URL).
4. Channel list rendered correctly (chips for each channel).

`OutboxFilterBar.test.tsx` (~4 tests):
1. Renders kid select + type select + status radio + since/until date inputs.
2. Toggling status → onChange with new status.
3. Setting a date → onChange with formatted date string.
4. Clear button → onChange with empty filters.

`OutboxPanel.test.tsx` (~4 tests):
1. Renders FilterBar + list of OutboxRow components seeded from `useAlerts`.
2. Empty filtered: "No alerts match" + Clear button.
3. Pagination: Next disabled when `offset + items.length >= total`; Prev disabled at offset 0.
4. Filter state persists in URL search params; mount with `?status=sent` reads through.

`DigestPreviewPanel.test.tsx` (~5 tests):
1. Kid picker renders all kids; default first kid.
2. Pre-populated render: when `useDigestPreview` resolves, iframe `srcDoc` is set to response html.
3. Top-line rendered above iframe.
4. Switching kid via picker fires the preview query for the new kid_id.
5. Empty state when no kids: "Add a kid first" + link to `/kids/new`.

`alerts.test.tsx` (route shell, ~2 tests):
1. Default tab is outbox when no `?tab=` param.
2. URL `?tab=digest` activates DigestPreviewPanel.

### Manual smoke (master §7 page #8 verification)

1. Navigate `/alerts` → Outbox tab default.
2. TopBar has new "Alerts" link.
3. Verify outbox lists past alerts (fixture data or recent activity).
4. Filter by kid → list narrows.
5. Filter by status=pending → only pending visible.
6. Click Resend on any alert → row shows green "Resend queued" pill; new alert appears at top after invalidation.
7. Switch to Digest preview tab → URL becomes `/alerts?tab=digest`.
8. Iframe renders the digest HTML at fixed 600px.
9. Switch kid via picker → iframe content changes.
10. Reload page → filters + tab + kid selection all persist.

## Acceptance criteria

- ✅ New `/alerts` route accessible via TopBar; default tab is Outbox.
- ✅ Outbox lists alerts with all 4 filter controls + pagination.
- ✅ Filter state, current page, and tab all persist in URL search params.
- ✅ Resend button POSTs to `/resend` and the new cloned alert appears after invalidation.
- ✅ Digest preview tab renders the next-scheduled digest in an iframe sandboxed against the app.
- ✅ Kid picker switches preview content.
- ✅ Empty/error/no-kid states render the right copy.
- ✅ Backend `AlertOut.summary_text` populated; frontend types match.
- ✅ Backend `GET /api/digest/preview?kid_id=N` returns `{html, plain, top_line}`.
- ✅ Backend gates clean; ~597 tests passing.
- ✅ Frontend gates clean; ~273 tests passing.

## Risks

- **Iframe height.** Fixed 600px works for typical digests but truncates long ones. Acceptable v1; future polish can add `postMessage`-based auto-resize.
- **Sandbox attribute.** `sandbox="allow-same-origin"` lets `<style>` work without scripts; the digest renderer uses Jinja `select_autoescape(["html"])` and self-contained inline styles (verified). No remote-asset issues expected.
- **`summary_text` for system alerts.** Composition logic for alerts without kid_id/offering_id (e.g. `crawl_failed`, `push_cap`) needs a sensible fallback. Mirror `InboxAlert.summary_text`'s composition.
- **`useResendAlert` invalidation.** Invalidating `['alerts']` is broad enough to cover all outbox views — fine since there's only one outbox at a time.
- **Filter URL serialization.** Multi-value filters not supported in v1 (single kid, single type). Future-extensible.
- **TanStack Router search-param typing.** The router supports typed search schemas. We use untyped string params for v1; if it bites, the router's `validateSearch` helper can add types.

## After this lands

Master §7 page status:
- 8 of 9 met (after Phase 7-3)
- **9 of 9 met** (after this) — page #8 Alerts closed.
- Phase 7 complete. Phases 8 (polish) and 9 (observation) remain to v1.
