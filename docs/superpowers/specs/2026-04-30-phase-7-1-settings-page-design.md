# Phase 7-1 — Settings Page Design

**Date:** 2026-04-30
**Status:** Spec
**Author:** Claude + owine
**Closes:** Master §7 page #9 (Settings)
**Roadmap:** `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md` (Phase 7-1)

## Goal

Replace the existing read-only `/settings` page with a fully editable Settings page covering Household basics (home address with geocode preview, defaults, digest/quiet hours, LLM cost cap), per-channel configuration forms (email, ntfy, Pushover), and the alert routing matrix. After this ships, master §7 page #9 closes and the only Phase 7 page left is 7-2 Offerings browser, 7-3 Enrollments, 7-4 Alerts outbox.

## Scope

**In scope:**
- New per-section components under `frontend/src/components/settings/`.
- New mutation hooks (`useUpdateHousehold`, `useUpdateAlertRouting`, `useTestNotifier`).
- One new backend endpoint: `POST /api/notifiers/{channel}/test`.
- Frontend tests (~32) + backend tests (~5).

**Out of scope:**
- **Home Assistant channel.** `HouseholdSettings.ha_config_json` exists in the schema but no notifier code reads it. Dropping the HA section from the form for v1; the schema field stays untouched.
- **Schema changes** to `HouseholdSettings`. The page works against the existing fields.
- **Per-channel test endpoints with custom payloads.** `/test` sends a fixed message; no params.
- **Browser-nav guards (`useBlocker`).** Per-section Save matches KidForm precedent; not worth the complexity for a settings page.
- **Re-styled checkbox grid.** Native `<input type="checkbox">` with Tailwind, no custom widget.
- **Cross-section transactional save.** Each section saves independently; no "save all" button.
- **Backfilling missing alert-routing rows.** The existing `/api/alert_routing` returns whatever rows the backend has populated; the UI renders those plus any new types we want to introduce later (out of scope here).

## Background

The backend has all the persistence machinery already:

- `GET /api/household` / `PATCH /api/household` — single-row settings (`home_location_id`, `default_max_distance_mi`, `digest_time`, `quiet_hours_start/end`, `daily_llm_cost_cap_usd`, plus four `*_config_json` fields). PATCH does immediate-geocode on `home_address` write via Nominatim and creates/updates the joined `Location` row; the response surfaces the resolved `home_address` + `home_location_name`.
- `GET /api/alert_routing` / `PATCH /api/alert_routing/{type}` — list of `[{type, channels: string[], enabled: bool}]`. The PATCH backend rejects channel names not in `_get_configured_channels(household)` (i.e. unconfigured channels can't be routed to).
- Worker reads channel configs from `household.smtp_config_json` (→ `EmailChannel`), `ntfy_config_json` (→ `NtfyChannel`), `pushover_config_json` (→ `PushoverChannel`). HA is not wired.

The current `/settings` route is read-only (cards display values; "Channel configuration available in Phase 5b" placeholder). This phase replaces that page with editable forms.

**Key fact about secrets:** the channel configs store *env-var names* (`password_env`, `auth_token_env`, `user_key_env`, `app_token_env`), not the actual secret values. The user sets the env var in `.env`; the JSON tells the channel which env var to read. This means the Settings forms have text inputs for env-var names — NOT password fields for secrets — and a small help line directs the user to `.env`.

## Decisions

### D1: Per-channel forms (not JSON editor)

The roadmap flagged this as a choice: a `<textarea>` JSON editor per channel vs. typed forms. We use **typed forms**.

JSON editor would be ~50 LOC per channel and power-user friendly, but the friction of remembering "what fields does ntfy need?" outweighs the LOC savings — even for a single-user app. Typed forms are ~200 LOC per channel × 3 channels (~600 LOC) and produce a page that's actually usable without docs.

The tradeoff: each channel form must mirror what the backend channel constructor reads. We pin field shapes to the actual `email.py` / `ntfy.py` / `pushover.py` config keys (see Per-channel forms below).

### D2: Per-section Save (not single-page Save)

All sections render on one scrollable page (no tabs, no accordion), but each section has its own form + Save button. SMTP and ntfy don't share state; one section's validation error doesn't block another's save. Mirrors the KidForm/WatchlistEntrySheet mutation pattern — each section is its own form with its own mutation hook.

Trade-off: more state to manage (each section tracks its own dirty/saving/error state) and more Save UI to render. But it's a more honest model of what's happening; coupling six unrelated forms behind one save was always going to bite.

### D3: Alert routing is a checkbox grid with per-cell mutations (no Save button)

The matrix is naturally a `(alert_type × channel)` grid. Render rows as alert types and columns as `[Enabled, email, ntfy, pushover]` (header + four columns). Each cell is its own checkbox; clicking it triggers an immediate optimistic PATCH to `/api/alert_routing/{type}` with the updated `channels` array (or `enabled` bool for the leftmost column). Optimistic update + rollback on error follows the canonical 5b-1b pattern.

Columns whose channel is unconfigured (e.g. `pushover` column when `pushover_config_json === null`) render disabled with a tooltip "Configure Pushover first." This matches the backend's `_get_configured_channels` enforcement.

A grid editor with per-cell save matches how users naturally interact with this kind of matrix (toggle one cell at a time, see immediate feedback). A Save button at the bottom would force users to track which cells changed and click Save when done — extra friction for no benefit.

### D4: Test-send buttons + small backend endpoint

Each channel section has a "Send test {kind}" button (e.g. "Send test email"). Clicking POSTs to `POST /api/notifiers/{channel}/test` with empty body; the backend loads `HouseholdSettings`, instantiates the appropriate channel class with the persisted JSON, dispatches a fixed test message, and returns `{ok: bool, detail: string}`.

Adds ~50 LOC of backend (one route + a tiny message factory) plus tests. Lets the user verify each channel actually works without waiting for a real alert. The cost is small enough to be worth it.

The button is **disabled while the section's form is dirty** — testing unsaved values would be confusing (you'd test the persisted config, not what's in the inputs).

### D5: Drop Home Assistant from the v1 UI

`HouseholdSettings.ha_config_json` is in the schema, but there's no `HomeAssistantChannel` notifier — nothing reads the field. Showing a config form for it would let users save data that does nothing.

Drop the HA section entirely from the v1 page. The schema field stays as-is (no backend changes). When/if an HA channel is added in Phase 8 or later, the section can be added then.

### D6: Env-var-name UX (not "store secret in DB")

The backend reads secrets from environment variables; the JSON only stores the env var name. This is a security feature: secrets never get persisted to the SQLite DB, never appear in DB backups, never surface in logs.

The forms reflect this: `password_env`, `auth_token_env`, `user_key_env`, `app_token_env` are plain text inputs (not password fields) with help text *"e.g. `YAS_PUSHOVER_USER_KEY` — set this env var in your `.env` to the actual secret."* The user's mental model is "name your env var, then set it" — slightly more friction than typing the secret directly into the form, but matches reality and keeps the security boundary intact.

### D7: Geocode preview pill (no Nominatim re-call from frontend)

After the user saves the household form with a new `home_address`, the backend's PATCH handler calls Nominatim immediately and updates the `Location` row's `lat`/`lon`. The PATCH response includes the resolved `home_address` and `home_location_name`. The UI then renders a small pill below the address field:

- Green `📍 Geocoded: <lat>, <lon>` if `home_location_id` resolves to a Location with non-null lat+lon.
- Amber `⚠️ Geocoding failed — distance gates will be skipped` if the Location exists but lat/lon are null.

The pill is informational only; the user doesn't manually re-trigger geocoding (the existing backend retry logic on subsequent PATCH calls handles that).

To get lat/lon to the frontend, `HouseholdOut` must include them. **The current schema doesn't expose lat/lon** — it has `home_location_id`, `home_address`, `home_location_name` but not the resolved coordinates. We either:

- (a) Add `home_lat: float | None`, `home_lon: float | None` to `HouseholdOut` (small backend change). OR
- (b) Show the pill state based purely on `home_location_id !== null` + a separate "geocode_status" field (string enum). OR
- (c) Skip the pill entirely; just show "Saved" text after PATCH.

Picking **(a)**: tiny backend change (4 lines in `_to_out` + 2 fields in `HouseholdOut`), gives the pill real information. The frontend renders coordinates if both are present, falls back to the amber state if address is set but coords are null.

### D8: Email transport selector with conditional fields

The email channel supports two transports: `smtp` and `forwardemail` (per `email.py:220`). The form has a `<select>` for `transport`. Fields below the selector branch:

- `smtp`: `host`, `port` (number), `username`, `password_env`, `use_tls` (default true), `from_addr`, `to_addrs` (comma-separated text → array on save)
- `forwardemail`: `api_token_env`, `from_addr`, `to_addrs`

The zod schema is a discriminated union on `transport`. Save sends the right shape; backend validates again.

### D9: "Disable channel" button per channel

Each channel section has a "Disable channel" button at the bottom that opens ConfirmDialog ("Disable {channel}? Existing alert routing entries pointing to {channel} will be cleared.") and on confirm:

1. PATCH `/api/household` with `{<channel>_config_json: null}`.
2. Side effect on the backend: any `alert_routing` rows with `<channel>` in their `channels` array get filtered out by `_get_configured_channels` on the next read.
3. Frontend invalidates both `['household']` and `['alert_routing']` after.

This is the "uninstall" path. Without it, users have no way to remove a configured-but-broken channel without DB surgery.

### D10: Disabled cell tooltips in routing matrix

Cells where the channel column is unconfigured render `<input type="checkbox" disabled aria-label="Configure <channel> first">` with a `title` attribute matching. Visually grayed out via Tailwind. No tooltip library — `title` is enough. Users learn "configure the channel first" inline; no extra docs needed.

## Architecture

### Routes

| Route | Component | Purpose |
|---|---|---|
| `/settings` (modify) | `SettingsPage` | Compose the five sections; remove read-only-row helpers. |

### Components (new)

```
SettingsPage
├── HouseholdSection           form (TanStack Form + zod) → useUpdateHousehold
├── EmailChannelSection         form + transport-conditional fields → useUpdateHousehold (smtp_config_json) + useTestNotifier('email')
├── NtfyChannelSection          form → useUpdateHousehold (ntfy_config_json) + useTestNotifier('ntfy')
├── PushoverChannelSection      form → useUpdateHousehold (pushover_config_json) + useTestNotifier('pushover')
└── AlertRoutingSection         grid → per-cell useUpdateAlertRouting

shared:
└── TestSendButton              label + onClick + dirty-disabled + result pill
```

`SettingsPage` is mostly a vertical layout with `<section>` separators; the existing `Skeleton` + `ErrorBanner` early-returns for the household + routing queries stay.

### Mutations

Add to `frontend/src/lib/mutations.ts`:

- `useUpdateHousehold()` — PATCH `/api/household`. Vars: `Partial<HouseholdPatch>`. Returns `HouseholdOut`. Optimistic (mirrors `useUpdateKid`): cancelQueries → snapshot → setQueryData → onError restore → awaited onSettled invalidate `['household']` (and `['alert_routing']` if any `*_config_json` field is in the patch with value `null`).
- `useUpdateAlertRouting()` — PATCH `/api/alert_routing/{type}`. Vars: `{type: string; patch: {channels?: string[]; enabled?: boolean}}`. Returns `AlertRoutingOut`. Optimistic: snapshot the whole routing list, setQueryData with the row updated, onError restore, onSettled invalidate `['alert_routing']`.
- `useTestNotifier()` — POST `/api/notifiers/{channel}/test`. Vars: `{channel: 'email' | 'ntfy' | 'pushover'}`. Returns `{ok: boolean, detail: string}`. Non-optimistic; no invalidation.

### Files

**Create — frontend:**
- `frontend/src/components/settings/HouseholdSection.tsx` + `.test.tsx`
- `frontend/src/components/settings/EmailChannelSection.tsx` + `.test.tsx`
- `frontend/src/components/settings/NtfyChannelSection.tsx` + `.test.tsx`
- `frontend/src/components/settings/PushoverChannelSection.tsx` + `.test.tsx`
- `frontend/src/components/settings/AlertRoutingSection.tsx` + `.test.tsx`
- `frontend/src/components/settings/TestSendButton.tsx` + `.test.tsx`

**Create — backend:**
- `src/yas/web/routes/notifier_test.py` — single endpoint.
- `src/yas/web/routes/notifier_test_schemas.py` — `TestSendOut` schema.
- `tests/web/test_notifier_test.py` — ~5 tests.

**Modify — frontend:**
- `frontend/src/routes/settings.tsx` — replace body with section composition.
- `frontend/src/lib/mutations.ts` — add 3 new hooks.
- `frontend/src/lib/mutations.test.tsx` — tests for the 3 new hooks (~6 tests).
- `frontend/src/test/handlers.ts` — MSW handlers for PATCH `/api/household`, PATCH `/api/alert_routing/:type`, POST `/api/notifiers/:channel/test`. Verify which already exist; add the missing ones.
- `frontend/src/lib/types.ts` — add channel-config interfaces (`SmtpConfig`, `ForwardEmailConfig`, `EmailConfig` discriminated union, `NtfyConfig`, `PushoverConfig`); extend `Household` with `home_lat`/`home_lon`.

**Modify — backend:**
- `src/yas/web/routes/household_schemas.py` — add `home_lat: float | None`, `home_lon: float | None` to `HouseholdOut`.
- `src/yas/web/routes/household.py` — populate `home_lat`/`home_lon` from the joined Location in `_to_out`.
- `src/yas/web/app.py` — register the new `notifier_test` router.

**No new dependencies.**

## Per-channel forms

### Email — `EmailChannelSection`

```ts
// shapes (matching email.py:218-244)
type EmailConfig = SmtpConfig | ForwardEmailConfig;

interface SmtpConfig {
  transport: 'smtp';
  host: string;
  port: number;
  username?: string;          // optional per email.py
  password_env?: string;      // optional per email.py
  use_tls: boolean;           // default true
  from_addr: string;
  to_addrs: string[];         // length >= 1
}

interface ForwardEmailConfig {
  transport: 'forwardemail';
  api_token_env: string;
  from_addr: string;
  to_addrs: string[];
}
```

Fields rendered:
- Transport `<select>` — values `smtp`, `forwardemail`. Default to whichever the persisted config has, or `smtp` if empty.
- Conditional fields per branch (above).
- "Send test email" button (`<TestSendButton channel="email">`).
- "Disable channel" button (with ConfirmDialog).

zod schema is a discriminated union on `transport`; both branches require `from_addr` (URL-shaped via simple regex) and `to_addrs.length >= 1`.

### ntfy — `NtfyChannelSection`

```ts
interface NtfyConfig {
  base_url: string;       // default 'https://ntfy.sh'
  topic: string;
  auth_token_env?: string;
}
```

Fields: `base_url`, `topic`, `auth_token_env` (optional). zod: URL on base_url; non-empty topic.

### Pushover — `PushoverChannelSection`

```ts
interface PushoverConfig {
  user_key_env: string;
  app_token_env: string;
  devices?: string[];
  emergency_retry_s?: number;     // default 60
  emergency_expire_s?: number;    // default 3600
}
```

Fields: `user_key_env`, `app_token_env`, `devices` (comma-separated), `emergency_retry_s` + `emergency_expire_s` (advanced — collapsed under a `<details>` disclosure).

zod: both `_env` fields required + non-empty.

## Backend test-send endpoint

```python
# src/yas/web/routes/notifier_test.py (sketch)
from fastapi import APIRouter, HTTPException, Request
from yas.alerts.channels import EmailChannel, NtfyChannel, PushoverChannel
from yas.db.models import HouseholdSettings
from yas.db.session import session_scope

router = APIRouter(prefix="/api/notifiers", tags=["notifiers"])

CHANNELS = {
    "email": (EmailChannel, "smtp_config_json"),
    "ntfy": (NtfyChannel, "ntfy_config_json"),
    "pushover": (PushoverChannel, "pushover_config_json"),
}

@router.post("/{channel}/test", response_model=TestSendOut)
async def test_notifier(channel: str, request: Request) -> TestSendOut:
    if channel not in CHANNELS:
        raise HTTPException(404, f"unknown channel: {channel}")
    ChannelCls, field = CHANNELS[channel]
    async with session_scope(request.app.state.yas.engine) as s:
        hh = (await s.execute(select(HouseholdSettings))).scalars().first()
        config = getattr(hh, field, None) if hh else None
    if config is None:
        raise HTTPException(503, f"{channel} not configured")
    ch = ChannelCls(config)
    result = await ch.send(_test_message())
    return TestSendOut(ok=result.ok, detail=result.detail or "")
```

`_test_message()` builds a synthetic `Alert`-like payload with subject "YAS test notification" and body "If you see this, the {channel} channel is working." (whatever shape the existing `Channel.send()` interface expects — verify when implementing).

## Validation

zod schemas co-located per section. Each form's submit calls `useUpdateHousehold.mutateAsync({<field>_config_json: parsedConfig})`. The `Partial<HouseholdPatch>` type means PATCH only sends the touched key; other channel configs are unchanged.

For `HouseholdSection`:
- `daily_llm_cost_cap_usd`: number ≥ 0
- `digest_time`: regex `/^\d\d:\d\d$/`
- `quiet_hours_start` + `quiet_hours_end`: same regex; refinement that both are present or both are null
- `default_max_distance_mi`: nullable number ≥ 0 (or null when "no limit" is checked)
- `home_address`: optional string; if provided, non-empty after trim
- `home_location_name`: optional; defaults to "Home" if home_address is set

## Data flow

### Household save

```
User edits HouseholdSection inputs
  ↓ clicks Save
useUpdateHousehold.mutateAsync({...patch})
  → backend PATCH /api/household
  → backend updates row, geocodes home_address (if changed)
  → returns HouseholdOut with home_lat/home_lon
  → frontend updates ['household'] cache
  → geocode pill renders based on home_lat/home_lon
```

### Channel save

```
User edits NtfyChannelSection inputs
  ↓ clicks Save
useUpdateHousehold.mutateAsync({ ntfy_config_json: { base_url, topic, ... } })
  → backend PATCH /api/household
  → frontend invalidates ['household']
  → AlertRoutingSection re-reads configured channels (ntfy column un-grays if it was disabled before)
```

### Test send

```
User clicks "Send test ntfy"
  ↓ button disabled if form is dirty
useTestNotifier.mutateAsync({ channel: 'ntfy' })
  → backend POST /api/notifiers/ntfy/test
  → loads HouseholdSettings.ntfy_config_json, instantiates NtfyChannel, dispatches
  → returns { ok, detail }
Frontend renders pill: green "Sent ✓" or red "Failed: <detail>" for ~5s.
```

### Routing toggle

```
User clicks the (new_match × pushover) cell
  ↓ optimistic update
useUpdateAlertRouting.mutateAsync({
  type: 'new_match',
  patch: { channels: [...current.channels, 'pushover'] }
})
  → setQueryData with row updated
  → backend PATCH /api/alert_routing/new_match
  → onError: restore snapshot + render error pill
  → onSettled: invalidate ['alert_routing']
```

### Disable channel

```
User clicks "Disable email" → ConfirmDialog → confirm
useUpdateHousehold.mutateAsync({ smtp_config_json: null })
  → backend PATCH /api/household
  → frontend invalidates ['household'] + ['alert_routing']
  → email column in routing matrix disabled
  → any rows that had 'email' in channels are filtered server-side; UI re-renders
```

## Error handling

| Failure | Behavior |
|---|---|
| Household PATCH fails | Section ErrorBanner with detail; form stays editable; rollback optimistic update via cached snapshot. |
| Channel PATCH fails | Per-section ErrorBanner; form stays editable; rollback. |
| Test-send 503 (channel not configured) | TestSendButton pill: red "Failed: not configured" — user sees they need to save first. |
| Test-send 200 with `ok=false` | Pill: red "Failed: <detail>" (e.g. "smtp 535 auth failed"). |
| Test-send 200 with `ok=true` | Pill: green "Sent ✓" for 5s. |
| Routing PATCH fails | Cell rolls back optimistic toggle; brief inline error pill near the cell. |
| Disable channel ConfirmDialog cancel | No-op. |
| zod validation fail | Inline field error; submit doesn't fire. |
| Geocoding failure (handled silently by backend) | Amber pill in HouseholdSection. |

## Testing

**Frontend test count target:** ~32 new tests, raising 165 → ~197.

### `HouseholdSection.test.tsx` (~5 tests)
1. Empty state renders empty inputs + Save disabled
2. Pre-populates from useHousehold data
3. Valid save calls PATCH with right payload (MSW capture)
4. Geocoded state shows green pill; un-geocoded shows amber pill
5. Validation: invalid `digest_time` blocks save

### `EmailChannelSection.test.tsx` (~5 tests)
1. Renders transport selector default `smtp` when no config
2. Pre-populates from existing smtp config
3. Switching transport reveals `forwardemail` fields
4. Save sends `{smtp_config_json: {...}}` PATCH (capture)
5. Disable channel → ConfirmDialog → PATCH `{smtp_config_json: null}`

### `NtfyChannelSection.test.tsx` (~5 tests)
1. Renders empty + populated states
2. Save POSTs PATCH with right shape
3. Disable button → ConfirmDialog → PATCH null
4. Test-send button disabled while form dirty
5. Validation: empty topic blocks save

### `PushoverChannelSection.test.tsx` (~5 tests)
1. Renders empty + populated states
2. Save sends right shape
3. Advanced (`emergency_retry_s`/`emergency_expire_s`) collapsed by default
4. Disable button → ConfirmDialog → PATCH null
5. Validation: missing `user_key_env` blocks save

### `AlertRoutingSection.test.tsx` (~5 tests)
1. Renders rows per alert_type and a column per configured channel
2. Cell toggle calls PATCH with updated channels array
3. Optimistic update applied immediately; rolled back on 500
4. Unconfigured channel column rendered disabled with title attr
5. Enabled checkbox toggle PATCH with `{enabled: bool}`

### `TestSendButton.test.tsx` (~3 tests)
1. Disabled while form is dirty (passes `disabled` prop through)
2. Click POSTs to right endpoint and renders green "Sent ✓"
3. Failure renders red pill with detail message

### `mutations.test.tsx` (extensions, ~6 tests)
- `useUpdateHousehold`: happy + error
- `useUpdateAlertRouting`: happy + error (with optimistic rollback)
- `useTestNotifier`: happy + error

### Backend `tests/web/test_notifier_test.py` (~5 tests)
1. `POST /api/notifiers/email/test` with smtp configured returns `{ok: true}` (mock the channel send)
2. Same for ntfy
3. Same for pushover
4. Unknown channel returns 404
5. Unconfigured channel (config_json is null) returns 503

## Acceptance criteria

- ✅ User can edit home address; on save, geocode pill reflects success/failure.
- ✅ User can edit `default_max_distance_mi`, `digest_time`, `quiet_hours_*`, `daily_llm_cost_cap_usd` and save.
- ✅ Email channel: transport selector + per-transport fields + test-send + disable.
- ✅ ntfy channel: same shape.
- ✅ Pushover channel: same shape with collapsible advanced fields.
- ✅ HA section is NOT rendered.
- ✅ Alert routing is a checkbox grid with optimistic per-cell mutations; unconfigured channel columns are disabled with tooltip.
- ✅ Each channel section's Save button is disabled while form is invalid.
- ✅ Each channel's test-send button is disabled while its form is dirty.
- ✅ Backend `POST /api/notifiers/{channel}/test` returns 404/503/200 per spec.
- ✅ Backend `HouseholdOut` includes `home_lat`/`home_lon`.
- ✅ Frontend gates clean; ~197 tests passing.
- ✅ Backend gates clean; ~590 tests passing.

## Risks

- **Channel-class constructor signatures.** This spec assumes `EmailChannel(config)`, `NtfyChannel(config)`, `PushoverChannel(config)` are constructable from the JSON config alone. Verify when implementing — if any channel needs an HTTP client or session passed in, the backend test endpoint needs to construct it.
- **`Channel.send()` signature.** The test endpoint dispatches a "test" message. The exact payload type (Alert, dict, etc.) needs verification when implementing the endpoint.
- **Backend env-var resolution timing.** Channels resolve env vars at construction time. If the user saves a config referring to an env var that's NOT set, the test-send fires the channel and gets a runtime error from the channel code. The 200/`ok=false` path handles this gracefully.
- **Geocode response timing.** PATCH `/api/household` does Nominatim synchronously; on slow connections this can take a few seconds. Acceptable; existing UX is identical.
- **Alert types listed in routing.** The routing matrix's row count depends on what `/api/alert_routing` returns. If new alert types are added later (Phase 8), the matrix renders them automatically — no UI change needed.

## Out of scope (explicit non-goals)

- Home Assistant channel
- Custom test-send messages (always fixed string)
- Browser-nav guards (`useBlocker`)
- "Save all sections" button
- Backfilling missing alert-routing rows
- Per-channel rate-limit / retry settings
- Importing/exporting settings as JSON

## After this lands

Master §7 page status:
- 6 of 9 met (after Phase 6-1/3/4 + 6-2)
- **7 of 9 met** (after this) — page #9 Settings closed.
- Remaining: page #2 (Offerings browser → Phase 7-2), page #3 combined calendar (Phase 8-1), page #7 (Enrollments → Phase 7-3), page #8 outbox/preview (Phase 7-4).
