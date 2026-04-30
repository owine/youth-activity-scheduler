# Phase 5d-1 — Site/Offering Alert Mute (Design)

**Status:** Approved (brainstorming complete 2026-04-29).
**Predecessors (already merged):**
- Phase 5b-1b — canonical TanStack Query mutation pattern.
- Phase 5c-2 — calendar match overlay (this slice extends its filter logic).
**Master design:** `docs/superpowers/specs/2026-04-21-youth-activity-scheduler-design.md` §10. Closes the v1 terminal-state criterion: *"User can disable alerts from a specific site or offering with one click."*
**Succeeds into:** No immediate successor planned. After this slice, v1 is functionally complete.

## 1. Purpose and scope

Wire `Site.muted_until` and `Offering.muted_until` (model columns that already exist) into the alert-firing pipeline and the calendar match overlay, then build a single small UI primitive (`<MuteButton>`) that ships in three places: site detail page, matches list, calendar match popover.

`Site.muted_until` is partially honored today (crawl scheduler skips muted sites; site-stagnant detector skips muted sites). `Offering.muted_until` is an orphan column with no enforcement. Neither has UI affordances.

### 1.1 In scope

- **Backend alert pipeline** — extend `enqueue_new_match` and `enqueue_watchlist_hit` in `src/yas/alerts/enqueuer.py` to skip alerts when either the offering or its parent site is currently muted.
- **Backend offering route** — new `PATCH /api/offerings/{offering_id}` accepting `{ muted_until: datetime | null }`. Initial scope is mute only; future fields land in the same patch.
- **Backend calendar overlay filter** — extend `GET /api/kids/{id}/calendar?include_matches=true` to exclude muted offerings (and offerings whose site is muted).
- **Frontend `<MuteButton>` component** — popover with 4 duration options (7d / 30d / 90d / forever) when unmuted; "Muted until {date}" + Unmute action when muted. Pure UI; the parent owns the mutation.
- **Two mutation hooks** — `useUpdateSiteMute`, `useUpdateOfferingMute`. Follow the canonical 5b-1b/5c-1 pattern (cancelQueries → snapshot → optimistic where helpful → onError restore → awaited onSettled invalidate).
- **Three UI placements** — site detail page (`sites.$id.tsx`), matches list (`kids.$id.matches.tsx`), calendar event popover (match branch only).

### 1.2 Out of scope

- **Mute reasons or notes.** No `mute_reason` column. The user can remember.
- **Per-channel mute.** No "no push but yes email" granularity. v1 stays on the existing routing model.
- **Bulk mute / multi-select.** Single-row clicks only.
- **Auto-unmute notifications.** No "muted offerings about to unmute" reminder.
- **Mute history audit log.** The `muted_until` column is the source of truth.
- **"Show muted" toggle on the matches page.** Matches list shows everything regardless of mute (it's the find/manage surface). Mute affects alerts and calendar visibility, not matches list visibility.
- **Mute on enrolled offerings as a UI affordance.** The data layer handles it correctly (enrolled offerings produce no future new_match alerts anyway because the matcher excludes them); we don't surface a mute button on enrollment events. The matches list and site detail page can still mute an offering you happen to be enrolled in — that's harmless.

## 2. Mute semantics (Q1: A — suppress all alerts)

A row whose `muted_until` is set to a future timestamp is "muted." When evaluating whether to fire an alert about an offering:

```
muted := (offering.muted_until > now) OR (offering.site.muted_until > now)
if muted: skip
```

This applies to **`new_match`** and **`watchlist_hit`** alert types. Watchlist hits previously bypassed `kid.alert_on` because the user explicitly added the watchlist entry — mute is a stronger signal ("user changed their mind") and overrides. The function's docstring will be updated to reflect this.

`schedule_posted` (site-level, not offering-level) is gated by `Site.muted_until` only — already covered by the existing site-level mute path conceptually, but **not yet implemented** in the enqueuer. Add the same gate there.

`site_stagnant` already honors `Site.muted_until` via `src/yas/alerts/detectors/site_stagnant.py:26`. No change needed.

`reg_opens_24h` / `reg_opens_1h` / `reg_opens_now` — these alerts fire for matches whose offering has `registration_opens_at` set. Apply the same `_is_muted` gate. (The enqueuer file has these paths; identify them during implementation and gate uniformly.)

`crawl_failed` — site-level operational alert. Should also respect site mute (a site muted because it's broken shouldn't keep alerting that it's broken).

`digest`, `no_matches_for_kid`, `push_cap` — kid- or system-level, not site/offering-targeted. No change.

## 3. Mute duration (Q2: B — duration picker, 4 options)

The UI picker offers four buttons:

| Label | `muted_until` value |
|---|---|
| 7 days | `now() + 7 days` |
| 30 days | `now() + 30 days` |
| 90 days | `now() + 90 days` |
| Forever | `3000-01-01T00:00:00Z` (sentinel constant) |

Forever is a sentinel rather than `NULL`-or-true-forever to keep the data model uniform. The frontend `isMuted(mutedUntil)` helper just compares to `now`; the year-3000 sentinel is functionally indistinguishable from "true forever" within any plausible app lifetime. Unmuting writes `null`.

Date math lives in `frontend/src/lib/mute.ts`:

```ts
export const FOREVER_SENTINEL = '3000-01-01T00:00:00Z';

export function muteUntilFromDuration(duration: '7d' | '30d' | '90d' | 'forever', now: Date = new Date()): string {
  if (duration === 'forever') return FOREVER_SENTINEL;
  const days = { '7d': 7, '30d': 30, '90d': 90 }[duration];
  const out = new Date(now);
  out.setDate(out.getDate() + days);
  return out.toISOString();
}

export function isMuted(mutedUntil: string | null, now: Date = new Date()): boolean {
  if (mutedUntil == null) return false;
  return new Date(mutedUntil) > now;
}
```

## 4. UI placement (Q3: B)

### 4.1 `<MuteButton>` component

`frontend/src/components/common/MuteButton.tsx` — the only new presentational primitive in this slice.

```tsx
interface MuteButtonProps {
  mutedUntil: string | null;       // ISO timestamp or null
  onChange: (mutedUntil: string | null) => void;  // null = unmute
  isPending?: boolean;
  size?: 'default' | 'sm';
}
```

Renders a Popover trigger button:
- **Unmuted**: button label "Mute". Click opens picker with 4 duration buttons. Selecting one calls `onChange(muteUntilFromDuration(...))`.
- **Muted**: button label "Muted until {Mar 28}" (formatted with `date-fns`). Click opens menu with single "Unmute" action calling `onChange(null)`.

Uses the unified `radix-ui` package's Popover primitive (`import { Popover } from 'radix-ui'`) directly — no shadcn wrapper because the project doesn't have one in `components/ui/` yet, and the radix primitive is sufficient for this small popover. Style via Tailwind classes consistent with existing `Button` + Sheet primitives.

The component is purely presentational. Mutation, error handling, optimistic state belong to the parent.

### 4.2 Site detail page

`frontend/src/routes/sites.$id.tsx` — gains `<MuteButton>` in the page header alongside the site name. Wires to `useUpdateSiteMute` (Section 5).

### 4.3 Matches list

`frontend/src/routes/kids.$id.matches.tsx` — each match row gains a small (`size="sm"`) `<MuteButton>` on the right side. Wires to `useUpdateOfferingMute`. Muting a match in the list updates the row's button label but does NOT remove the row from the list (matches page is the find/manage surface).

### 4.4 Calendar event popover (match branch only)

`frontend/src/components/calendar/CalendarEventPopover.tsx` — the `kind === 'match'` branch gains a `<MuteButton>` alongside the existing Enroll button + View details link. Wires to `useUpdateOfferingMute`.

After clicking a duration, the popover's `onSuccess` callback clears the local selection and closes the popover (same pattern as the existing Enroll branch). The mutation also invalidates the calendar query so when the popover re-opens later, the muted offering's match events are gone (per Q4: muted offerings hidden from match overlay).

The popover does NOT show an Unmute button on muted matches because muted matches don't appear on the calendar in the first place. To unmute an offering, the user goes to the matches list or site detail page.

## 5. Mutation hooks

`frontend/src/lib/mutations.ts` adds two hooks. Same canonical shape as the existing `useCancelEnrollment`, etc.

### 5.1 `useUpdateSiteMute`

```ts
interface UpdateSiteMuteInput {
  siteId: number;
  mutedUntil: string | null;   // ISO timestamp or null
}

export function useUpdateSiteMute() {
  const qc = useQueryClient();
  type Ctx = { /* no optimistic cache surgery for site mute — just invalidate */ };
  return useMutation<unknown, Error, UpdateSiteMuteInput, Ctx>({
    mutationFn: ({ siteId, mutedUntil }) =>
      api.patch(`/api/sites/${siteId}`, { muted_until: mutedUntil }),

    onSettled: async (_d, _e, { siteId }) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['sites'] }),
        qc.invalidateQueries({ queryKey: ['sites', siteId] }),
        qc.invalidateQueries({ queryKey: ['kids'] }),  // calendar match overlay depends on this
      ]);
    },
  });
}
```

No optimistic surgery: the `MuteButton`'s local `isPending` covers visual feedback; site/offering rows don't need pre-confirmation removal.

### 5.2 `useUpdateOfferingMute`

```ts
interface UpdateOfferingMuteInput {
  offeringId: number;
  mutedUntil: string | null;
}

export function useUpdateOfferingMute() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, UpdateOfferingMuteInput, { snapshots: ... }>({
    mutationFn: ({ offeringId, mutedUntil }) =>
      api.patch(`/api/offerings/${offeringId}`, { muted_until: mutedUntil }),

    onMutate: async ({ offeringId, mutedUntil }) => {
      // Optimistic: when muting (mutedUntil != null), remove match events for
      // this offering from cached calendar variants — same pattern as
      // useEnrollOffering. When unmuting (mutedUntil == null), no surgery.
      if (mutedUntil == null) return { snapshots: [] };
      await qc.cancelQueries({ queryKey: ['kids'] });
      const snapshots = qc.getQueriesData<KidCalendarResponse>({ queryKey: ['kids'] });
      for (const [key, data] of snapshots) {
        if (!data) continue;
        if (key[2] !== 'calendar') continue;
        const filtered = data.events.filter(
          (e) => !(e.kind === 'match' && e.offering_id === offeringId),
        );
        qc.setQueryData<KidCalendarResponse>(key, { ...data, events: filtered });
      }
      return { snapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots?.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['matches'] }),
        qc.invalidateQueries({ queryKey: ['kids'] }),
      ]);
    },
  });
}
```

The optimistic match-removal mirrors `useEnrollOffering` from 5c-2 — same problem (remove a match from the calendar grid before server confirms).

## 6. Backend changes

### 6.1 Enqueuer gate

`src/yas/alerts/enqueuer.py` adds:

```python
async def _is_muted(session: AsyncSession, *, offering_id: int) -> bool:
    """True if the offering or its parent site is currently muted."""
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(Offering.muted_until, Site.muted_until)
            .join(Site, Site.id == Offering.site_id)
            .where(Offering.id == offering_id)
        )
    ).one_or_none()
    if row is None:
        return False
    o_muted, s_muted = row
    return (o_muted is not None and o_muted > now) or (s_muted is not None and s_muted > now)


async def _is_site_muted(session: AsyncSession, *, site_id: int) -> bool:
    """True if the site is currently muted."""
    now = datetime.now(UTC)
    s_muted = (
        await session.execute(select(Site.muted_until).where(Site.id == site_id))
    ).scalar_one_or_none()
    return s_muted is not None and s_muted > now
```

Insertion points (all in `src/yas/alerts/enqueuer.py`):
- `enqueue_new_match` (offering-targeted) — call `_is_muted(session, offering_id=offering_id)` after the `_kid_alert_on` check; return None if muted.
- `enqueue_watchlist_hit` (offering-targeted) — same insertion.
- `enqueue_registration_countdowns` (offering-targeted) — gate via `_is_muted` once per offering, before the inner loop emits the three countdown variants.
- `enqueue_schedule_posted` (site-targeted) — call `_is_site_muted(session, site_id=site_id)`; return None if muted.
- `enqueue_crawl_failed` (site-targeted) — same `_is_site_muted` gate.
- `enqueue_site_stagnant` (site-targeted) — already gated upstream by the detector (`alerts/detectors/site_stagnant.py:26`), but adding the same `_is_site_muted` gate here is harmless defense-in-depth and keeps the enqueuer module uniform. Decision: add it.

### 6.2 Offering route

New file `src/yas/web/routes/offerings.py`:

```python
"""CRUD for /api/offerings — initial scope: mute toggle."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.db.models import Offering
from yas.db.session import session_scope

router = APIRouter(prefix="/api/offerings", tags=["offerings"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


class OfferingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    muted_until: datetime | None = None


class OfferingMuteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    site_id: int
    muted_until: datetime | None


@router.patch("/{offering_id}", response_model=OfferingMuteOut)
async def update_offering(
    request: Request,
    offering_id: int,
    payload: OfferingPatch,
) -> OfferingMuteOut:
    async with session_scope(_engine(request)) as s:
        offering = (
            await s.execute(select(Offering).where(Offering.id == offering_id))
        ).scalar_one_or_none()
        if offering is None:
            raise HTTPException(status_code=404, detail=f"offering {offering_id} not found")
        if "muted_until" in payload.model_fields_set:
            offering.muted_until = payload.muted_until
        await s.flush()
        await s.refresh(offering)
        return OfferingMuteOut.model_validate(offering)
```

Register the router in `src/yas/web/app.py` alongside the others.

The `model_fields_set` guard is so a future `PATCH` body that doesn't include `muted_until` won't accidentally null it out. (Pydantic v2 idiom.)

The `await s.refresh(offering)` after flush mirrors the SQLite-tz-roundtrip lesson from 5b-1a: returning the just-refreshed row keeps response timestamps consistent with what comes back on the next read.

### 6.3 Calendar match-overlay filter

`src/yas/web/routes/kid_calendar.py` — extend the `select(Match, Offering)` query in the `if include_matches:` block:

The route handler already captures `now = datetime.now(UTC)` once at the top — reuse it (don't call `datetime.now(UTC)` per row):

```python
from sqlalchemy import or_, select  # add or_ to imports

# inside the include_matches block:
match_rows = (
    await s.execute(
        select(Match, Offering)
        .join(Offering, Offering.id == Match.offering_id)
        .join(Site, Site.id == Offering.site_id)
        .where(Match.kid_id == kid_id)
        .where(Match.score >= _MATCH_THRESHOLD)
        .where(~Match.offering_id.in_(committed_offering_ids))
        .where(or_(Offering.muted_until.is_(None), Offering.muted_until <= now))
        .where(or_(Site.muted_until.is_(None), Site.muted_until <= now))
    )
).all()
```

### 6.4 No new dependencies

All work in this slice uses existing libraries.

## 7. Edge cases

- **Mute date in the past**: `_is_muted` returns false; effectively unmuted. Treat past-dated mutes as expired. The frontend's "Forever" sentinel (year 3000) avoids this ambiguity; if a mute happens to expire while the popover is open, the next render correctly shows it as unmuted.
- **Site muted, individual offering also muted**: either condition suffices; no precedence needed.
- **Mute an enrolled offering**: data-layer no-op (the matcher already excludes enrolled offerings from match production, and enrollment events on the calendar don't depend on mute). UI doesn't surface a mute button on enrollment events.
- **Concurrent mute clicks**: `isPending` disables the button; second click ignored.
- **Calendar match popover open on a match that just got muted in another tab**: stale render; no auto-refetch on calendar route. Acceptable for single-household.
- **`Offering.muted_until` set in the past via direct API**: `_is_muted` correctly treats as unmuted. UI's `isMuted` helper agrees.
- **Race: site mute → offering on that site has a pending alert already inserted**: pending alerts in the queue fire normally. **Decision: mute filters at enqueue time only; the delivery worker does NOT re-check mute.** Rationale:
  1. If a user mutes a site, they want NO new alerts. A pending alert was enqueued before the mute and may represent something the user explicitly asked about (e.g., a watchlist hit). Suppressing it at delivery time would feel surprising.
  2. Symmetry with 5b-1a/b is intentionally only partial: `closed_at IS NULL` is a per-alert lifecycle state and the worker correctly gates on it. Mute is a per-row-on-Site/Offering policy, not a per-alert state.
  3. A worker-side mute check would duplicate logic for limited benefit and complicate the queue invariants.

## 8. Testing

Backend:
1. `tests/integration/test_alerts_enqueuer.py` (extend) —
   - `enqueue_new_match` returns None when offering muted, when site muted, when both muted; enqueues normally when both unmuted; enqueues normally when `muted_until` in the past.
   - Same coverage for `enqueue_watchlist_hit`.
   - `enqueue_schedule_posted` returns None when site muted.
   - (Reg-opens variants similar.)
2. `tests/integration/test_api_offerings.py` (new) — `PATCH /api/offerings/{id}`:
   - 404 for unknown id.
   - 422 when body has unknown fields (Pydantic `extra="forbid"`).
   - Setting `muted_until` to a future timestamp persists.
   - Setting `muted_until` to null clears the field.
   - Empty body: no change to `muted_until` (model_fields_set guard).
3. `tests/integration/test_api_kids_calendar.py` (extend) —
   - Match overlay excludes a muted offering.
   - Match overlay excludes an offering whose site is muted.
   - Match overlay includes an offering whose `muted_until` is in the past.

Frontend:
4. `frontend/src/lib/mute.test.ts` (new) — pure-function tests for `muteUntilFromDuration` (4 durations) and `isMuted` (null, past, future, sentinel).
5. `frontend/src/components/common/MuteButton.test.tsx` (new) —
   - Renders "Mute" when `mutedUntil` is null or in the past.
   - Renders "Muted until {date}" when `mutedUntil` is in the future.
   - Clicking a duration option fires `onChange` with the right ISO string.
   - Clicking Unmute fires `onChange(null)`.
6. `frontend/src/lib/mutations.test.tsx` (extend) — `useUpdateSiteMute` and `useUpdateOfferingMute`: PATCH fires with right payload; `useUpdateOfferingMute` optimistic match-removal works; rollback on error.
7. MSW handlers: `PATCH /api/sites/:id` (NOT yet in `frontend/src/test/handlers.ts` — add) and `PATCH /api/offerings/:id` (new).

Manual smoke (before merge):
- Mute a site from sites detail → site row reflects state.
- Wait/seed a new_match condition → no alert fires (verify via /api/alerts list).
- Mute an offering from matches list → button label flips.
- Toggle "Show matches" on calendar → muted offering's match doesn't appear.
- Unmute → match returns.

## 9. Open questions

None blocking. All four brainstorming decisions captured:

- **Q1** (mute scope): suppresses ALL alerts touching site/offering. §2.
- **Q2** (duration): 4-option picker (7d/30d/90d/forever). §3.
- **Q3** (UI placement): site detail + matches list + calendar popover. §4.
- **Q4** (calendar match overlay): muted offerings hidden. §6.3.

## 10. Exit criteria

Phase 5d-1 is complete when:

- `Offering.muted_until` is enforced in `enqueue_new_match`, `enqueue_watchlist_hit`, and reg-opens variants; `Site.muted_until` is enforced in those + `enqueue_schedule_posted` + `enqueue_crawl_failed` (where applicable).
- `PATCH /api/offerings/{offering_id}` works and is tested.
- Calendar match overlay excludes muted offerings (and offerings whose site is muted).
- `<MuteButton>` is implemented, tested, and used in three placements (site detail, matches list, calendar popover).
- `useUpdateSiteMute` and `useUpdateOfferingMute` follow the canonical pattern.
- All backend gates green.
- All frontend gates green.
- Manual smoke verified.
- Closes the v1 terminal-state criterion: *"User can disable alerts from a specific site or offering with one click."*
