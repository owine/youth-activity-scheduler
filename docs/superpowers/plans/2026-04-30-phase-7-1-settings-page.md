# Phase 7-1 — Settings Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the read-only `/settings` page with editable per-section forms covering Household basics, Email/ntfy/Pushover channel configs, and the Alert routing matrix — closing master §7 page #9.

**Architecture:** Five per-section components composed on a single `/settings` page. Each section owns its own form/state and saves independently via PATCH `/api/household` or PATCH `/api/alert_routing/{type}`. Channel sections also have a "Send test" button that fires `POST /api/notifiers/{channel}/test` (new endpoint). HouseholdOut gains `home_lat`/`home_lon` for the geocode-status pill.

**Tech Stack:** React 19, TanStack Query 5, TanStack Router 1.168, TanStack Form 1.29.1, zod 4.4.1, MSW, Vitest + RTL. FastAPI (one new route + 2 schema fields) + pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-30-phase-7-1-settings-page-design.md`

**Project conventions to maintain:**
- Frontend deps pinned exact in `frontend/package.json` (no `^`/`~`).
- All commits GPG-signed via 1Password SSH agent. Set `SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"` before each `git commit` in fresh shells. Verify with `git cat-file commit HEAD | grep -q '^gpgsig '`.
- Branch already exists: `phase-7-1-settings-page`. Spec already committed there. Do NOT commit to `main`.
- **Never use GitHub auto-close keywords** (`Closes #N`, `Fixes #N`, `Resolves #N`) in PRs/commits/docs — issue #1 is the Renovate dep dashboard. Use `Closes master §N page #M` or plain prose.
- Frontend gates: `cd frontend && npm run typecheck && npm run lint && npm run test`. Repo-wide `format:check` has pre-existing failures; only assert your touched files are Prettier-clean.
- Backend gates: `uv run pytest -q --no-cov` and `uv run ruff check .` and `uv run mypy src`.
- Frontend baseline at start: 165 tests across 24 files. Backend baseline: 585 tests.

**Master §7 page-coverage delta:** Closes page #9 (Settings). After this lands: 7 of 9 master § 7 pages met.

---

## File Structure

**Create — backend:**
- `src/yas/web/routes/notifier_test.py` — single `POST /api/notifiers/{channel}/test` route.
- `src/yas/web/routes/notifier_test_schemas.py` — `TestSendOut` schema.
- `tests/web/test_notifier_test.py` — ~5 tests.

**Modify — backend:**
- `src/yas/web/routes/household_schemas.py` — add `home_lat: float | None`, `home_lon: float | None` to `HouseholdOut`.
- `src/yas/web/routes/household.py` — populate `home_lat`/`home_lon` from the joined `Location` in `_to_out`.
- `src/yas/web/app.py` (or wherever routers are registered — verify) — register the `notifier_test` router.

**Create — frontend (per-section components + tests):**
- `frontend/src/components/settings/HouseholdSection.tsx` + `.test.tsx`
- `frontend/src/components/settings/EmailChannelSection.tsx` + `.test.tsx`
- `frontend/src/components/settings/NtfyChannelSection.tsx` + `.test.tsx`
- `frontend/src/components/settings/PushoverChannelSection.tsx` + `.test.tsx`
- `frontend/src/components/settings/AlertRoutingSection.tsx` + `.test.tsx`
- `frontend/src/components/settings/TestSendButton.tsx` + `.test.tsx`

**Modify — frontend:**
- `frontend/src/lib/types.ts` — add `Household.home_lat/home_lon`, `SmtpConfig`, `ForwardEmailConfig`, `EmailConfig` (discriminated union), `NtfyConfig`, `PushoverConfig`, `TestSendResult`.
- `frontend/src/lib/mutations.ts` — add `useUpdateHousehold`, `useUpdateAlertRouting`, `useTestNotifier`.
- `frontend/src/lib/mutations.test.tsx` — tests for the 3 new hooks (~6 tests).
- `frontend/src/test/handlers.ts` — MSW handlers for PATCH `/api/household`, PATCH `/api/alert_routing/:type`, POST `/api/notifiers/:channel/test`. Verify which already exist before adding.
- `frontend/src/routes/settings.tsx` — replace body with section composition; remove the `Row` helper.

**No new deps.** TanStack Form 1.29.1, zod 4.4.1, radix-ui 1.4.3, MSW already pinned.

---

## Task 1 — Backend: HouseholdOut lat/lon + test-send endpoint (TDD)

**Files:**
- Modify: `src/yas/web/routes/household_schemas.py`
- Modify: `src/yas/web/routes/household.py`
- Create: `src/yas/web/routes/notifier_test_schemas.py`
- Create: `src/yas/web/routes/notifier_test.py`
- Create: `tests/web/test_notifier_test.py`
- Modify: `src/yas/web/app.py` (register router)

End state: backend supports the new endpoint + `HouseholdOut` exposes lat/lon. ~5 new backend tests; existing 585 still green.

### Step 1: Verify exact paths before starting

- [ ] Read `src/yas/web/app.py` (or `src/yas/web/__init__.py`) to find where routers are registered. The task assumes a familiar pattern of `app.include_router(...)`. If routers are registered elsewhere, adjust.

```bash
grep -rn "include_router\|household.router\|alert_routing.router" src/yas/web/ | head -10
```

### Step 2: Add `home_lat`/`home_lon` to `HouseholdOut`

- [ ] **Edit `src/yas/web/routes/household_schemas.py`**:

```python
class HouseholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    home_location_id: int | None
    home_address: str | None
    home_location_name: str | None
    home_lat: float | None      # NEW
    home_lon: float | None      # NEW
    default_max_distance_mi: float | None
    digest_time: str
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    daily_llm_cost_cap_usd: float
```

- [ ] **Edit `src/yas/web/routes/household.py`**: in `_to_out`, populate `home_lat`/`home_lon` from the `Location` row that's already loaded:

```python
async def _to_out(s: AsyncSession, hh: HouseholdSettings) -> HouseholdOut:
    loc = None
    if hh.home_location_id is not None:
        loc = (
            await s.execute(select(Location).where(Location.id == hh.home_location_id))
        ).scalar_one_or_none()
    return HouseholdOut(
        id=hh.id,
        home_location_id=hh.home_location_id,
        home_address=loc.address if loc else None,
        home_location_name=loc.name if loc else None,
        home_lat=loc.lat if loc else None,             # NEW
        home_lon=loc.lon if loc else None,             # NEW
        default_max_distance_mi=hh.default_max_distance_mi,
        digest_time=hh.digest_time,
        quiet_hours_start=hh.quiet_hours_start,
        quiet_hours_end=hh.quiet_hours_end,
        daily_llm_cost_cap_usd=hh.daily_llm_cost_cap_usd,
    )
```

### Step 3: Run existing household tests — they should still pass

```bash
uv run pytest tests/web/test_household.py -q 2>&1 | tail -5
```

Expected: all green. The two new fields default to `None` when no Location is set, matching existing test fixtures.

### Step 4: Write the test-send endpoint failing tests

- [ ] **Create `tests/web/test_notifier_test.py`**:

```python
"""Tests for POST /api/notifiers/{channel}/test."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.alerts.channels.base import SendResult
from yas.db.models import HouseholdSettings
from yas.db.session import session_scope
from yas.web.app import create_app


# Pretty-print test names: each test creates an app, seeds a household, sends a test.

async def _seed_household(engine: AsyncEngine, **fields: Any) -> None:
    async with session_scope(engine) as s:
        hh = HouseholdSettings(id=1, **fields)
        s.add(hh)


@pytest.mark.asyncio
async def test_unknown_channel_returns_404(test_engine: AsyncEngine) -> None:
    app = create_app(engine=test_engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/notifiers/bogus/test")
    assert r.status_code == 404
    assert "unknown channel" in r.json()["detail"]


@pytest.mark.asyncio
async def test_unconfigured_channel_returns_503(test_engine: AsyncEngine) -> None:
    await _seed_household(test_engine)  # all *_config_json default null
    app = create_app(engine=test_engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/notifiers/email/test")
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_send_returns_ok_true_on_success(test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the channel send to return ok=True."""
    await _seed_household(
        test_engine,
        ntfy_config_json={"base_url": "https://ntfy.sh", "topic": "test"},
    )
    # Patch NtfyChannel.send to return ok=True.
    from yas.alerts.channels import ntfy as ntfy_mod
    async def fake_send(self: Any, msg: Any) -> SendResult:
        return SendResult(ok=True, transient_failure=False, detail="published")
    monkeypatch.setattr(ntfy_mod.NtfyChannel, "send", fake_send)

    app = create_app(engine=test_engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/notifiers/ntfy/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["detail"] == "published"


@pytest.mark.asyncio
async def test_channel_init_failure_surfaces_as_ok_false(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pushover constructor raises ValueError if user_key_env is missing — should surface as ok=false."""
    await _seed_household(
        test_engine,
        pushover_config_json={
            "user_key_env": "YAS_PUSHOVER_USER_KEY_DOES_NOT_EXIST",
            "app_token_env": "YAS_PUSHOVER_APP_TOKEN_DOES_NOT_EXIST",
        },
    )
    monkeypatch.delenv("YAS_PUSHOVER_USER_KEY_DOES_NOT_EXIST", raising=False)
    monkeypatch.delenv("YAS_PUSHOVER_APP_TOKEN_DOES_NOT_EXIST", raising=False)

    app = create_app(engine=test_engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/notifiers/pushover/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "channel init failed" in body["detail"]


@pytest.mark.asyncio
async def test_channel_send_failure_surfaces_as_ok_false(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the channel constructs but send returns ok=False, propagate that."""
    await _seed_household(
        test_engine,
        ntfy_config_json={"base_url": "https://ntfy.sh", "topic": "test"},
    )
    from yas.alerts.channels import ntfy as ntfy_mod
    async def fake_send(self: Any, msg: Any) -> SendResult:
        return SendResult(ok=False, transient_failure=True, detail="connection refused")
    monkeypatch.setattr(ntfy_mod.NtfyChannel, "send", fake_send)

    app = create_app(engine=test_engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/notifiers/ntfy/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["detail"] == "connection refused"
```

**Note:** Verify how the existing test files seed households + create the FastAPI app. Look at `tests/web/test_household.py` for the canonical pattern (the `test_engine` fixture + `create_app` shape). Adjust the imports to match if needed.

### Step 5: Run tests — verify fail

```bash
uv run pytest tests/web/test_notifier_test.py -q 2>&1 | tail -10
```

Expected: 5 failures with "ModuleNotFoundError" or "404 Not Found" — endpoint doesn't exist yet.

### Step 6: Implement the schemas

- [ ] **Create `src/yas/web/routes/notifier_test_schemas.py`**:

```python
"""Schemas for POST /api/notifiers/{channel}/test."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TestSendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ok: bool
    detail: str
```

### Step 7: Implement the endpoint

- [ ] **Create `src/yas/web/routes/notifier_test.py`**:

```python
"""POST /api/notifiers/{channel}/test — send a fixed test message."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from yas.alerts.channels import EmailChannel, NtfyChannel, PushoverChannel
from yas.alerts.channels.base import NotifierMessage
from yas.db.models import HouseholdSettings
from yas.db.models._types import AlertType
from yas.db.session import session_scope
from yas.web.routes.notifier_test_schemas import TestSendOut

router = APIRouter(prefix="/api/notifiers", tags=["notifiers"])

# Map URL path → (channel class, HouseholdSettings field name)
_CHANNELS: dict[str, tuple[type, str]] = {
    "email": (EmailChannel, "smtp_config_json"),
    "ntfy": (NtfyChannel, "ntfy_config_json"),
    "pushover": (PushoverChannel, "pushover_config_json"),
}


def _engine(req: Request) -> Any:
    return req.app.state.yas.engine


def _test_message(channel: str) -> NotifierMessage:
    # AlertType.new_match (NOT reg_opens_now — would trigger Pushover emergency mode).
    return NotifierMessage(
        kid_id=None,
        alert_type=AlertType.new_match,
        subject="YAS test notification",
        body_plain=f"If you see this, the {channel} channel is working.",
    )


@router.post("/{channel}/test", response_model=TestSendOut)
async def test_notifier(channel: str, request: Request) -> TestSendOut:
    if channel not in _CHANNELS:
        raise HTTPException(status_code=404, detail=f"unknown channel: {channel}")
    channel_cls, field = _CHANNELS[channel]
    async with session_scope(_engine(request)) as s:
        hh = (await s.execute(select(HouseholdSettings))).scalars().first()
        config = getattr(hh, field, None) if hh else None
    if config is None:
        raise HTTPException(status_code=503, detail=f"{channel} not configured")
    # Channel constructors raise ValueError if a referenced *_env var is missing.
    # Surface as ok=false rather than 500.
    try:
        ch = channel_cls(config)
    except ValueError as exc:
        return TestSendOut(ok=False, detail=f"channel init failed: {exc}")
    result = await ch.send(_test_message(channel))
    return TestSendOut(ok=result.ok, detail=result.detail)
```

### Step 8: Register the router

- [ ] **Edit `src/yas/web/app.py`** (path verified in Step 1): import and `include_router` for `notifier_test.router`. Match the existing router-registration style in the file.

### Step 9: Run tests — verify pass

```bash
uv run pytest tests/web/test_notifier_test.py -v 2>&1 | tail -15
```

Expected: 5/5 pass.

### Step 10: Run full backend gates

```bash
uv run pytest -q --no-cov 2>&1 | tail -5
uv run ruff check src tests
uv run mypy src
```

Expected: ~590 passing (585 + 5), no lint, no type errors.

### Step 11: Commit

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add src/yas/web/routes/household_schemas.py src/yas/web/routes/household.py src/yas/web/routes/notifier_test_schemas.py src/yas/web/routes/notifier_test.py src/yas/web/app.py tests/web/test_notifier_test.py
git commit -m "feat(backend): test-send endpoint + HouseholdOut lat/lon

- POST /api/notifiers/{channel}/test dispatches a fixed message
  through the configured channel. 404 on unknown, 503 on unconfigured.
  Channel constructor failures (missing *_env var) surface as
  {ok: false, detail: ...} (D11) instead of 500.
- Test message uses AlertType.new_match to avoid Pushover emergency
  mode (D12).
- HouseholdOut gains home_lat/home_lon so the frontend can render
  the geocode-status pill (D7)."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 2 — Frontend types + 3 mutation hooks (TDD)

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/mutations.ts`
- Modify: `frontend/src/lib/mutations.test.tsx`
- Modify: `frontend/src/test/handlers.ts`

End state: 3 typed mutation hooks following the canonical 5b-1b pattern. ~6 new frontend tests. 165 → ~171.

### Step 1: Add types

- [ ] **Edit `frontend/src/lib/types.ts`**: extend `Household` with new lat/lon fields, add channel-config types, add `TestSendResult`.

```ts
// Extend the existing Household interface — append home_lat / home_lon.
// (Verify Household exists; if there's no exported interface, add the new Household
// shape matching backend HouseholdOut.)
export interface Household {
  id: number;
  home_location_id: number | null;
  home_address: string | null;
  home_location_name: string | null;
  home_lat: number | null;          // NEW
  home_lon: number | null;          // NEW
  default_max_distance_mi: number | null;
  digest_time: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  daily_llm_cost_cap_usd: number;
}

// Channel config shapes — env-var-name pattern (D6).
export interface SmtpConfig {
  transport: 'smtp';
  host: string;
  port: number;
  username?: string;        // optional; omit when blank, never send "" (backend rejects)
  password_env?: string;    // optional
  use_tls: boolean;
  from_addr: string;
  to_addrs: string[];
}

export interface ForwardEmailConfig {
  transport: 'forwardemail';
  api_token_env: string;
  from_addr: string;
  to_addrs: string[];
}

export type EmailConfig = SmtpConfig | ForwardEmailConfig;

export interface NtfyConfig {
  base_url: string;
  topic: string;
  auth_token_env?: string;
}

export interface PushoverConfig {
  user_key_env: string;
  app_token_env: string;
  devices?: string[];
  emergency_retry_s?: number;
  emergency_expire_s?: number;
}

export interface TestSendResult {
  ok: boolean;
  detail: string;
}
```

### Step 2: Add MSW handlers

- [ ] **Edit `frontend/src/test/handlers.ts`**: append the new handlers. Verify what already exists for `/api/household`, `/api/alert_routing`, `/api/notifiers` first by searching the file.

```ts
// PATCH /api/household — echoes the patch into a default Household shape
http.patch('/api/household', async ({ request }) => {
  const body = (await request.json()) as Record<string, unknown>;
  return HttpResponse.json({
    id: 1,
    home_location_id: null,
    home_address: (body.home_address as string | null) ?? null,
    home_location_name: (body.home_location_name as string | null) ?? null,
    home_lat: null,
    home_lon: null,
    default_max_distance_mi: (body.default_max_distance_mi as number | null) ?? null,
    digest_time: (body.digest_time as string) ?? '07:00',
    quiet_hours_start: (body.quiet_hours_start as string | null) ?? null,
    quiet_hours_end: (body.quiet_hours_end as string | null) ?? null,
    daily_llm_cost_cap_usd: (body.daily_llm_cost_cap_usd as number) ?? 1.0,
  });
}),

// PATCH /api/alert_routing/:type — echoes the patch
http.patch('/api/alert_routing/:type', async ({ params, request }) => {
  const body = (await request.json()) as Record<string, unknown>;
  return HttpResponse.json({
    type: params.type,
    channels: (body.channels as string[]) ?? [],
    enabled: (body.enabled as boolean) ?? true,
  });
}),

// POST /api/notifiers/:channel/test — default success
http.post('/api/notifiers/:channel/test', () =>
  HttpResponse.json({ ok: true, detail: 'sent' }),
),
```

### Step 3: Write failing tests for `useUpdateHousehold`

- [ ] **Edit `frontend/src/lib/mutations.test.tsx`**: append a new describe block. Use the existing `makeWrapper(qc)` helper and inline `new QueryClient(...)` per test (NO `makeQc` factory).

```tsx
describe('useUpdateHousehold', () => {
  it('PATCHes the patch and returns Household', async () => {
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/household', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          id: 1, home_location_id: null, home_address: 'a',
          home_location_name: 'Home', home_lat: 12.34, home_lon: 56.78,
          default_max_distance_mi: null, digest_time: '08:00',
          quiet_hours_start: null, quiet_hours_end: null,
          daily_llm_cost_cap_usd: 2.0,
        });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const { result } = renderHook(() => useUpdateHousehold(), { wrapper: makeWrapper(qc) });
    const out = await result.current.mutateAsync({ digest_time: '08:00' });
    expect(captured).toEqual({ digest_time: '08:00' });
    expect(out.digest_time).toBe('08:00');
    expect(out.home_lat).toBe(12.34);
  });

  it('surfaces server errors as Error', async () => {
    server.use(
      http.patch('/api/household', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const { result } = renderHook(() => useUpdateHousehold(), { wrapper: makeWrapper(qc) });
    await expect(result.current.mutateAsync({ digest_time: 'X' })).rejects.toThrow();
  });
});
```

### Step 4: Run tests — verify fail

```bash
cd frontend && npm run test -- mutations.test 2>&1 | tail -10
```

Expected: 2 failures with "useUpdateHousehold is not defined".

### Step 5: Implement `useUpdateHousehold`

- [ ] **Edit `frontend/src/lib/mutations.ts`**: append after the existing household-related hooks. **Optimistic** (mirrors `useUpdateKid`): preserve the cache on rollback.

```ts
type HouseholdPatch = Partial<{
  home_address: string | null;
  home_location_name: string | null;
  default_max_distance_mi: number | null;
  digest_time: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  daily_llm_cost_cap_usd: number;
  smtp_config_json: SmtpConfig | ForwardEmailConfig | null;
  ntfy_config_json: NtfyConfig | null;
  pushover_config_json: PushoverConfig | null;
}>;

export function useUpdateHousehold() {
  const qc = useQueryClient();
  type Ctx = { snapshot: Household | undefined };
  return useMutation<Household, Error, HouseholdPatch, Ctx>({
    mutationFn: (patch) => api.patch<Household>('/api/household', patch),
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: ['household'] });
      const snapshot = qc.getQueryData<Household>(['household']);
      if (snapshot) {
        // Apply only fields known to be mirrored on Household (skip *_config_json which lives on the row but isn't on HouseholdOut).
        const merged: Household = { ...snapshot };
        for (const key of [
          'home_address', 'home_location_name', 'default_max_distance_mi',
          'digest_time', 'quiet_hours_start', 'quiet_hours_end',
          'daily_llm_cost_cap_usd',
        ] as const) {
          if (key in patch) {
            (merged as any)[key] = (patch as any)[key];
          }
        }
        qc.setQueryData<Household>(['household'], merged);
      }
      return { snapshot };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.snapshot) qc.setQueryData(['household'], ctx.snapshot);
    },
    onSettled: async (_d, _e, patch) => {
      const promises: Promise<unknown>[] = [
        qc.invalidateQueries({ queryKey: ['household'] }),
      ];
      // If a *_config_json was changed (especially set to null), routing matrix may change too.
      const touchesChannels =
        'smtp_config_json' in patch ||
        'ntfy_config_json' in patch ||
        'pushover_config_json' in patch;
      if (touchesChannels) {
        promises.push(qc.invalidateQueries({ queryKey: ['alert_routing'] }));
      }
      await Promise.all(promises);
    },
  });
}
```

(Remember to add `Household, SmtpConfig, ForwardEmailConfig, NtfyConfig, PushoverConfig` to the imports from `./types` at the top of `mutations.ts`.)

### Step 6: Run tests — verify useUpdateHousehold pass

```bash
cd frontend && npm run test -- mutations.test 2>&1 | tail -5
```

Expected: 2 new tests pass.

### Step 7: Write failing tests for `useUpdateAlertRouting`

```tsx
describe('useUpdateAlertRouting', () => {
  it('PATCHes /api/alert_routing/:type with channels[] and applies optimistic update', async () => {
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/alert_routing/:type', async ({ params, request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          type: params.type,
          channels: captured.channels ?? [],
          enabled: captured.enabled ?? true,
        });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    qc.setQueryData(['alert_routing'], [
      { type: 'new_match', channels: ['email'], enabled: true },
    ]);
    const { result } = renderHook(() => useUpdateAlertRouting(), { wrapper: makeWrapper(qc) });
    await result.current.mutateAsync({
      type: 'new_match',
      patch: { channels: ['email', 'ntfy'] },
    });
    expect(captured).toEqual({ channels: ['email', 'ntfy'] });
    const updated = qc.getQueryData<unknown[]>(['alert_routing']);
    expect(updated?.[0]).toMatchObject({ type: 'new_match', channels: ['email', 'ntfy'] });
  });

  it('rolls back on error', async () => {
    server.use(
      http.patch('/api/alert_routing/:type', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    qc.setQueryData(['alert_routing'], [
      { type: 'new_match', channels: ['email'], enabled: true },
    ]);
    const { result } = renderHook(() => useUpdateAlertRouting(), { wrapper: makeWrapper(qc) });
    await expect(
      result.current.mutateAsync({ type: 'new_match', patch: { channels: ['ntfy'] } }),
    ).rejects.toThrow();
    const after = qc.getQueryData<unknown[]>(['alert_routing']);
    expect(after?.[0]).toMatchObject({ type: 'new_match', channels: ['email'] });
  });
});
```

### Step 8: Implement `useUpdateAlertRouting`

```ts
export interface AlertRouting {
  type: string;
  channels: string[];
  enabled: boolean;
}

interface UpdateAlertRoutingInput {
  type: string;
  patch: { channels?: string[]; enabled?: boolean };
}

export function useUpdateAlertRouting() {
  const qc = useQueryClient();
  type Ctx = { snapshot: AlertRouting[] | undefined };
  return useMutation<AlertRouting, Error, UpdateAlertRoutingInput, Ctx>({
    mutationFn: ({ type, patch }) =>
      api.patch<AlertRouting>(`/api/alert_routing/${type}`, patch),
    onMutate: async ({ type, patch }) => {
      await qc.cancelQueries({ queryKey: ['alert_routing'] });
      const snapshot = qc.getQueryData<AlertRouting[]>(['alert_routing']);
      if (snapshot) {
        qc.setQueryData<AlertRouting[]>(
          ['alert_routing'],
          snapshot.map((r) => (r.type === type ? { ...r, ...patch } : r)),
        );
      }
      return { snapshot };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.snapshot) qc.setQueryData(['alert_routing'], ctx.snapshot);
    },
    onSettled: async () => {
      await qc.invalidateQueries({ queryKey: ['alert_routing'] });
    },
  });
}
```

(If `AlertRouting` is already exported from `./types`, import it from there instead of redefining.)

### Step 9: Run tests for useUpdateAlertRouting

```bash
cd frontend && npm run test -- mutations.test 2>&1 | tail -5
```

Expected: 2 new tests pass.

### Step 10: Write failing tests for `useTestNotifier`

```tsx
describe('useTestNotifier', () => {
  it('POSTs to /api/notifiers/:channel/test and returns TestSendResult', async () => {
    server.use(
      http.post('/api/notifiers/ntfy/test', () =>
        HttpResponse.json({ ok: true, detail: 'sent' })),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const { result } = renderHook(() => useTestNotifier(), { wrapper: makeWrapper(qc) });
    const r = await result.current.mutateAsync({ channel: 'ntfy' });
    expect(r).toEqual({ ok: true, detail: 'sent' });
  });

  it('returns ok=false on channel-init failure (still 200)', async () => {
    server.use(
      http.post('/api/notifiers/pushover/test', () =>
        HttpResponse.json({ ok: false, detail: 'channel init failed: missing env var' })),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const { result } = renderHook(() => useTestNotifier(), { wrapper: makeWrapper(qc) });
    const r = await result.current.mutateAsync({ channel: 'pushover' });
    expect(r.ok).toBe(false);
    expect(r.detail).toMatch(/channel init failed/);
  });
});
```

### Step 11: Implement `useTestNotifier`

```ts
type TestNotifierChannel = 'email' | 'ntfy' | 'pushover';

export function useTestNotifier() {
  return useMutation<TestSendResult, Error, { channel: TestNotifierChannel }>({
    mutationFn: ({ channel }) =>
      api.post<TestSendResult>(`/api/notifiers/${channel}/test`, {}),
  });
}
```

(Add `TestSendResult` to the import from `./types`.)

### Step 12: Run all tests — verify pass + frontend gates

```bash
cd frontend && npm run typecheck && npm run lint && npm run test 2>&1 | tail -10
npx prettier --check src/lib/types.ts src/lib/mutations.ts src/lib/mutations.test.tsx src/test/handlers.ts
```

Expected: clean. Tests: 165 → 171.

### Step 13: Commit

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add frontend/src/lib/types.ts frontend/src/lib/mutations.ts frontend/src/lib/mutations.test.tsx frontend/src/test/handlers.ts
git commit -m "feat(frontend): mutation hooks for Phase 7-1 settings

- useUpdateHousehold: PATCH /api/household; optimistic update of
  ['household'] cache; invalidates ['alert_routing'] when any
  *_config_json field is in the patch (channel disable/enable).
- useUpdateAlertRouting: PATCH /api/alert_routing/{type}; optimistic
  per-row update of ['alert_routing'] with rollback on error.
- useTestNotifier: POST /api/notifiers/{channel}/test; non-optimistic.

Plus channel-config types (SmtpConfig/ForwardEmailConfig discriminated
union, NtfyConfig, PushoverConfig) and Household.home_lat/home_lon."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 3 — `<TestSendButton>` shared component (TDD)

**Files:**
- Create: `frontend/src/components/settings/TestSendButton.tsx` + `.test.tsx`

End state: A small reusable button that POSTs to the test endpoint, disables itself while the parent's form is dirty, and shows a success/failure pill for ~3s. ~3 tests.

### Step 1: Write failing tests

```tsx
// TestSendButton.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TestSendButton } from './TestSendButton';

const makeQc = () =>
  new QueryClient({ defaultOptions: { mutations: { retry: false } } });
const wrap = (qc: QueryClient) => ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={qc}>{children}</QueryClientProvider>
);

describe('TestSendButton', () => {
  it('is disabled when the dirty prop is true', () => {
    render(<TestSendButton channel="ntfy" label="Send test" dirty />, { wrapper: wrap(makeQc()) });
    expect(screen.getByRole('button', { name: /send test/i })).toBeDisabled();
  });

  it('renders a green Sent pill on success', async () => {
    server.use(
      http.post('/api/notifiers/ntfy/test', () =>
        HttpResponse.json({ ok: true, detail: 'published' })),
    );
    render(<TestSendButton channel="ntfy" label="Send test" dirty={false} />, { wrapper: wrap(makeQc()) });
    await userEvent.click(screen.getByRole('button', { name: /send test/i }));
    expect(await screen.findByText(/Sent/i)).toBeInTheDocument();
  });

  it('renders a red Failed pill with detail on failure', async () => {
    server.use(
      http.post('/api/notifiers/ntfy/test', () =>
        HttpResponse.json({ ok: false, detail: 'boom' })),
    );
    render(<TestSendButton channel="ntfy" label="Send test" dirty={false} />, { wrapper: wrap(makeQc()) });
    await userEvent.click(screen.getByRole('button', { name: /send test/i }));
    expect(await screen.findByText(/Failed.*boom/i)).toBeInTheDocument();
  });
});
```

### Step 2: Run tests — verify fail

```bash
cd frontend && npm run test -- TestSendButton 2>&1 | tail -10
```

Expected: 3 failures with "Cannot find module './TestSendButton'".

### Step 3: Implement

```tsx
// TestSendButton.tsx
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { useTestNotifier } from '@/lib/mutations';
import type { TestSendResult } from '@/lib/types';

interface Props {
  channel: 'email' | 'ntfy' | 'pushover';
  label: string;
  dirty: boolean;
}

export function TestSendButton({ channel, label, dirty }: Props) {
  const test = useTestNotifier();
  const [result, setResult] = useState<TestSendResult | null>(null);

  const handleClick = async () => {
    setResult(null);
    try {
      const r = await test.mutateAsync({ channel });
      setResult(r);
    } catch (err) {
      setResult({ ok: false, detail: (err as Error).message });
    }
  };

  return (
    <div className="flex items-center gap-2">
      <Button type="button" variant="outline" onClick={handleClick} disabled={dirty || test.isPending}>
        {test.isPending ? 'Sending…' : label}
      </Button>
      {result && (
        <span
          className={
            result.ok
              ? 'rounded bg-green-100 px-2 py-1 text-xs text-green-800 dark:bg-green-900/30 dark:text-green-300'
              : 'rounded bg-destructive/10 px-2 py-1 text-xs text-destructive'
          }
        >
          {result.ok ? 'Sent ✓' : `Failed: ${result.detail}`}
        </span>
      )}
    </div>
  );
}
```

### Step 4: Run tests — verify pass + Prettier

```bash
cd frontend && npm run test -- TestSendButton 2>&1 | tail -5
npx prettier --check src/components/settings/TestSendButton.tsx src/components/settings/TestSendButton.test.tsx
```

Expected: 3/3 pass, Prettier clean.

### Step 5: Commit

```bash
git add frontend/src/components/settings/TestSendButton.tsx frontend/src/components/settings/TestSendButton.test.tsx
git commit -m "feat(frontend): TestSendButton shared component

Reusable across the three channel sections. Disabled while parent
form is dirty (testing unsaved values would be confusing). Green
'Sent ✓' pill on success; red 'Failed: <detail>' pill on failure.
Pill stays visible until next click or unmount."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 4 — `<HouseholdSection>` (TDD)

**Files:**
- Create: `frontend/src/components/settings/HouseholdSection.tsx` + `.test.tsx`

End state: TanStack Form-based form with `home_address`, `home_location_name`, `default_max_distance_mi` (with no-limit checkbox), `digest_time`, `quiet_hours_start/end`, `daily_llm_cost_cap_usd`. Geocode pill below address. ~5 tests.

### Step 1: Write failing tests

```tsx
// HouseholdSection.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HouseholdSection } from './HouseholdSection';
import type { Household } from '@/lib/types';

const baseHh: Household = {
  id: 1, home_location_id: null, home_address: null, home_location_name: null,
  home_lat: null, home_lon: null,
  default_max_distance_mi: null, digest_time: '07:00',
  quiet_hours_start: null, quiet_hours_end: null,
  daily_llm_cost_cap_usd: 1.0,
};

const wrap = (qc: QueryClient, household: Household) => {
  qc.setQueryData(['household'], household);
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
};
const makeQc = () => new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });

describe('HouseholdSection', () => {
  it('pre-populates from useHousehold data', () => {
    render(<HouseholdSection />, {
      wrapper: wrap(makeQc(), { ...baseHh, digest_time: '08:30', daily_llm_cost_cap_usd: 2.5 }),
    });
    expect(screen.getByLabelText(/digest time/i)).toHaveValue('08:30');
    expect(screen.getByLabelText(/daily llm cost cap/i)).toHaveValue(2.5);
  });

  it('saves valid edits via PATCH /api/household', async () => {
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch('/api/household', async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...baseHh, digest_time: '09:00' });
      }),
    );
    render(<HouseholdSection />, { wrapper: wrap(makeQc(), baseHh) });
    const digest = screen.getByLabelText(/digest time/i);
    await userEvent.clear(digest);
    await userEvent.type(digest, '09:00');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(captured?.digest_time).toBe('09:00'));
  });

  it('renders green pill when home_lat/home_lon are set', () => {
    render(<HouseholdSection />, {
      wrapper: wrap(makeQc(), {
        ...baseHh, home_address: '123 Main', home_lat: 12.34, home_lon: 56.78,
      }),
    });
    expect(screen.getByText(/Geocoded:.*12\.34/)).toBeInTheDocument();
  });

  it('renders amber pill when address is set but lat/lon are null', () => {
    render(<HouseholdSection />, {
      wrapper: wrap(makeQc(), { ...baseHh, home_address: '123 Main', home_lat: null, home_lon: null }),
    });
    expect(screen.getByText(/Geocoding failed/)).toBeInTheDocument();
  });

  it('blocks save with invalid digest_time', async () => {
    render(<HouseholdSection />, { wrapper: wrap(makeQc(), baseHh) });
    const digest = screen.getByLabelText(/digest time/i);
    await userEvent.clear(digest);
    await userEvent.type(digest, '99:99');
    expect(await screen.findByText(/HH:MM/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
  });
});
```

### Step 2: Run tests — verify fail

```bash
cd frontend && npm run test -- HouseholdSection 2>&1 | tail -10
```

Expected: 5 failures with "Cannot find module".

### Step 3: Implement `<HouseholdSection>`

```tsx
// HouseholdSection.tsx
import { useState } from 'react';
import { useForm } from '@tanstack/react-form';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { useHousehold } from '@/lib/queries';
import { useUpdateHousehold } from '@/lib/mutations';
import { ApiError } from '@/lib/api';

const TIME_RX = /^\d\d:\d\d$/;

const schema = z
  .object({
    home_address: z.string().optional().transform((v) => (v?.trim() ? v.trim() : null)),
    home_location_name: z.string().optional().transform((v) => (v?.trim() ? v.trim() : null)),
    default_max_distance_mi: z.number().min(0).nullable(),
    no_distance_limit: z.boolean(),
    digest_time: z.string().regex(TIME_RX, 'HH:MM'),
    quiet_hours_start: z.string().nullable(),
    quiet_hours_end: z.string().nullable(),
    daily_llm_cost_cap_usd: z.number().min(0),
  })
  .refine(
    (v) =>
      (v.quiet_hours_start === null && v.quiet_hours_end === null) ||
      (TIME_RX.test(v.quiet_hours_start ?? '') && TIME_RX.test(v.quiet_hours_end ?? '')),
    { message: 'Set both quiet-hours times or leave both blank', path: ['quiet_hours_start'] },
  );

export function HouseholdSection() {
  const hh = useHousehold();
  const update = useUpdateHousehold();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!hh.data) return null;
  const h = hh.data;

  const form = useForm({
    defaultValues: {
      home_address: h.home_address ?? '',
      home_location_name: h.home_location_name ?? '',
      default_max_distance_mi: h.default_max_distance_mi,
      no_distance_limit: h.default_max_distance_mi === null,
      digest_time: h.digest_time,
      quiet_hours_start: h.quiet_hours_start ?? '',
      quiet_hours_end: h.quiet_hours_end ?? '',
      daily_llm_cost_cap_usd: h.daily_llm_cost_cap_usd,
    },
    validators: { onChange: schema, onMount: schema },
    onSubmit: async ({ value }) => {
      setErrorMsg(null);
      const patch = {
        home_address: value.home_address?.trim() || null,
        home_location_name: value.home_location_name?.trim() || null,
        default_max_distance_mi: value.no_distance_limit ? null : value.default_max_distance_mi,
        digest_time: value.digest_time,
        quiet_hours_start: value.quiet_hours_start?.trim() || null,
        quiet_hours_end: value.quiet_hours_end?.trim() || null,
        daily_llm_cost_cap_usd: value.daily_llm_cost_cap_usd,
      };
      try {
        await update.mutateAsync(patch);
      } catch (err) {
        const detail = err instanceof ApiError ? (err.body as { detail?: string })?.detail : null;
        setErrorMsg(detail ?? (err as Error).message);
      }
    },
  });

  const geocodePill = h.home_address
    ? h.home_lat !== null && h.home_lon !== null
      ? <span className="text-xs text-green-700 dark:text-green-300">📍 Geocoded: {h.home_lat.toFixed(4)}, {h.home_lon.toFixed(4)}</span>
      : <span className="text-xs text-amber-700 dark:text-amber-300">⚠️ Geocoding failed — distance gates will be skipped</span>
    : null;

  return (
    <section className="space-y-3">
      <h2 className="text-xs font-semibold uppercase text-muted-foreground">Household</h2>
      {errorMsg && <ErrorBanner message={errorMsg} />}
      <form onSubmit={(e) => { e.preventDefault(); form.handleSubmit(); }} className="space-y-3 max-w-xl">
        {/* Inline form.Field blocks for each input — follow the KidForm pattern. */}
        {/* home_address with geocodePill below */}
        {/* default_max_distance_mi with no_distance_limit checkbox sibling */}
        {/* digest_time, quiet_hours_start, quiet_hours_end (type=time) */}
        {/* daily_llm_cost_cap_usd (type=number, $-prefixed via leading span) */}
        {/* form.Subscribe for canSubmit gate on the Save button */}
        <form.Subscribe selector={(state) => state.canSubmit}>
          {(canSubmit) => (
            <Button type="submit" disabled={update.isPending || !canSubmit}>
              {update.isPending ? 'Saving…' : 'Save'}
            </Button>
          )}
        </form.Subscribe>
      </form>
    </section>
  );
}
```

(The `form.Field` blocks for each input are elided in this sketch — fill them in following the exact pattern KidForm uses. Each field renders a `<label>` + input + per-field error text.)

### Step 4: Run tests — verify pass + Prettier

```bash
cd frontend && npm run test -- HouseholdSection 2>&1 | tail -5
npx prettier --check src/components/settings/HouseholdSection.tsx src/components/settings/HouseholdSection.test.tsx
```

Expected: 5/5 pass, Prettier clean.

### Step 5: Commit

```bash
git add frontend/src/components/settings/HouseholdSection.tsx frontend/src/components/settings/HouseholdSection.test.tsx
git commit -m "feat(frontend): HouseholdSection editable form

home_address, home_location_name, default_max_distance_mi (with
no-limit checkbox), digest_time, quiet_hours_start/end, and
daily_llm_cost_cap_usd. Geocode-status pill below the address
field reflects home_lat/home_lon presence per D7."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 5 — `<EmailChannelSection>` (TDD)

**Files:**
- Create: `frontend/src/components/settings/EmailChannelSection.tsx` + `.test.tsx`

End state: Transport selector with conditional fields. Test-send button. Disable button. ~5 tests.

### Step 1: Write failing tests

Tests cover:
- Empty config → renders transport=`smtp` default + empty inputs.
- Pre-populated smtp config → fields show persisted values.
- Switching transport from `smtp` to `forwardemail` reveals different fields (api_token_env shows; host/port hide).
- Save sends `{smtp_config_json: {transport:'smtp', host, port, ..., to_addrs: [...]}}` (capture POST body).
- Disable button → ConfirmDialog → PATCH `{smtp_config_json: null}`.

(Use the same wrap/QueryClient pattern as Task 4. The component takes no props — reads household from cache.)

### Step 2: Run tests — verify fail

### Step 3: Implement

Key implementation notes:
- zod discriminated union on `transport` (D8). The `username` field MUST be omitted from the patch when blank — never send `""`. Construct the patch like `{ ...common, ...(username.trim() ? { username: username.trim() } : {}) }`.
- `to_addrs` is rendered as a comma-separated text input that splits on `,` + trims + filters empty into `string[]`.
- "Send test email" button uses `<TestSendButton channel="email" label="Send test email" dirty={form.state.isDirty} />`.
- Disable button: ConfirmDialog with destructive Discard. On confirm: `await update.mutateAsync({ smtp_config_json: null })`.

### Step 4: Run tests — verify pass + Prettier

### Step 5: Commit

```bash
git commit -m "feat(frontend): EmailChannelSection (smtp + forwardemail transports)

Transport selector with discriminated-union zod schema; per-transport
fields. Send-test-email button via shared <TestSendButton>. Disable
channel via ConfirmDialog → PATCH {smtp_config_json: null}.

Critical: username field is omitted from the patch when blank rather
than sent as empty string — backend rejects empty usernames per D8."
```

---

## Task 6 — `<NtfyChannelSection>` + `<PushoverChannelSection>` (TDD)

**Files:**
- Create: `NtfyChannelSection.tsx` + `.test.tsx`
- Create: `PushoverChannelSection.tsx` + `.test.tsx`

End state: Two parallel-but-simpler channel sections. ~5 tests each = 10 total.

### NtfyChannelSection

**Tests:** empty/populated render; save POSTs PATCH with right shape; disable confirm → PATCH null; test-send button disabled while form dirty; empty topic blocks save.

**Implementation:** zod schema `{base_url: url, topic: nonempty, auth_token_env?}`. Default `base_url` to `'https://ntfy.sh'` when empty. Save: `update.mutateAsync({ ntfy_config_json: parsed })`.

### PushoverChannelSection

**Tests:** empty/populated render; save with right shape; advanced fields collapsed by default; disable; missing user_key_env blocks save.

**Implementation:** zod schema `{user_key_env: nonempty, app_token_env: nonempty, devices?: string[], emergency_retry_s?: number, emergency_expire_s?: number}`. `devices` rendered as comma-separated input. `emergency_*` fields under `<details><summary>Advanced</summary>...</details>`.

### After both implemented

```bash
cd frontend && npm run typecheck && npm run lint && npm run test 2>&1 | tail -10
```

Expected: ~10 new tests pass.

```bash
git add frontend/src/components/settings/NtfyChannelSection.tsx frontend/src/components/settings/NtfyChannelSection.test.tsx frontend/src/components/settings/PushoverChannelSection.tsx frontend/src/components/settings/PushoverChannelSection.test.tsx
git commit -m "feat(frontend): NtfyChannelSection + PushoverChannelSection

Both follow the same shape as EmailChannelSection: TanStack Form + zod;
Save → PATCH {<channel>_config_json: ...}; Disable → ConfirmDialog +
PATCH null; <TestSendButton> sibling.

Pushover hides emergency_retry_s/emergency_expire_s under an Advanced
<details> disclosure; defaults preserved."
```

---

## Task 7 — `<AlertRoutingSection>` (TDD)

**Files:**
- Create: `frontend/src/components/settings/AlertRoutingSection.tsx` + `.test.tsx`

End state: Checkbox grid driven by `useAlertRouting` + `useHousehold`. Per-cell mutations (no Save button). ~5 tests.

### Step 1: Write failing tests

```tsx
// AlertRoutingSection.test.tsx
// 1. Renders rows for each alert_type returned by useAlertRouting + columns for [Enabled, email, ntfy, pushover].
// 2. Cell toggle calls PATCH /api/alert_routing/:type with {channels: [...prev, 'pushover']} (capture body).
// 3. Optimistic update applied immediately (cache shows the toggled state before the request resolves).
// 4. Unconfigured channel column rendered with disabled+title attribute (tooltip "Configure <channel> first").
// 5. The leftmost Enabled checkbox PATCHes {enabled: bool}.
```

### Step 2: Run tests — verify fail

### Step 3: Implement

Key shape:
- Read `useHousehold().data` — derive `configuredChannels: Set<'email'|'ntfy'|'pushover'>` from `*_config_json !== null`.
- Read `useAlertRouting().data` — array of `{type, channels, enabled}`.
- Render a `<table>` with header row `[Type, Enabled, email, ntfy, pushover]` and one row per routing entry.
- Each cell is `<input type="checkbox">`. The leftmost data column toggles `enabled`. The four channel columns each toggle membership in `channels`.
- For unconfigured channel columns: render `<input disabled aria-label="Configure <channel> first" title="Configure <channel> first">`. Don't dispatch anything.
- On change: call `useUpdateAlertRouting().mutate({ type, patch: { channels: nextChannels } })` (or `{ enabled }`).

Note: the `AlertRoutingPatch` schema rejects empty `channels: []` — when the user un-checks the last channel for a row, the only way to "turn off" is to use the Enabled toggle. Document this in a small note next to the table: *"Uncheck Enabled to disable a row entirely. To remove all channels, disable the row."* The frontend can also coerce `channels: []` → `enabled: false` automatically on the last uncheck — pick the simpler path: a small note + UI-side check that prevents un-checking the last channel (toast-explanation if attempted).

### Step 4: Run tests — verify pass + Prettier

### Step 5: Commit

```bash
git commit -m "feat(frontend): AlertRoutingSection checkbox grid

Reads ['household'] for configuredChannels, ['alert_routing'] for
rows. Renders a table with per-cell checkboxes. Each toggle is its
own optimistic PATCH /api/alert_routing/{type} mutation; rollback
on error.

Unconfigured channel columns are disabled with title-attribute tooltip
per D10 (frontend-only UX guard; backend doesn't enforce — D3 spec
note). Empty channels array on a row is prevented client-side
because backend rejects channels=[] (use the Enabled toggle to
disable the row)."
```

---

## Task 8 — Compose into `/settings` page + manual smoke + push + PR

**Files:**
- Modify: `frontend/src/routes/settings.tsx`
- Final gates + smoke + roadmap update + push + PR.

### Step 1: Replace the settings page body

```tsx
// frontend/src/routes/settings.tsx
import { createFileRoute } from '@tanstack/react-router';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { useAlertRouting, useHousehold } from '@/lib/queries';
import { HouseholdSection } from '@/components/settings/HouseholdSection';
import { EmailChannelSection } from '@/components/settings/EmailChannelSection';
import { NtfyChannelSection } from '@/components/settings/NtfyChannelSection';
import { PushoverChannelSection } from '@/components/settings/PushoverChannelSection';
import { AlertRoutingSection } from '@/components/settings/AlertRoutingSection';

export const Route = createFileRoute('/settings')({ component: SettingsPage });

function SettingsPage() {
  const hh = useHousehold();
  const routing = useAlertRouting();

  if (hh.isLoading || routing.isLoading) return <Skeleton className="h-64 w-full" />;
  if (hh.isError || routing.isError || !hh.data || !routing.data) {
    return (
      <ErrorBanner
        message="Failed to load settings"
        onRetry={() => { hh.refetch(); routing.refetch(); }}
      />
    );
  }

  return (
    <div className="space-y-8 max-w-3xl">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <HouseholdSection />
      <EmailChannelSection />
      <NtfyChannelSection />
      <PushoverChannelSection />
      <AlertRoutingSection />
    </div>
  );
}
```

(The `Row` helper from the old version goes away.)

### Step 2: Frontend gates

```bash
cd frontend && npm run typecheck && npm run lint && npm run test 2>&1 | tail -10
npx prettier --check src/routes/settings.tsx
```

Expected: clean. Test count: ~165 → ~197 (+32 across 6 new component test files + 6 new mutation tests).

### Step 3: Backend gates (sanity check; should be unchanged from Task 1)

```bash
uv run pytest -q --no-cov 2>&1 | tail -5
```

Expected: ~590 passing.

### Step 4: Commit page composition

```bash
git add frontend/src/routes/settings.tsx
git commit -m "feat(frontend): wire /settings to the new section components

Replaces the read-only Card-based page with a vertical composition
of HouseholdSection, EmailChannelSection, NtfyChannelSection,
PushoverChannelSection, AlertRoutingSection. The Row helper is
dropped (each section owns its own rendering)."
```

### Step 5: Manual smoke

Bring up the dev stack:

```bash
cd /Users/owine/Git/youth-activity-scheduler
YAS_DATABASE_URL="sqlite+aiosqlite:///$(pwd)/data/activities.db" uv run alembic upgrade head 2>&1 | tail -2
YAS_DATABASE_URL="sqlite+aiosqlite:///$(pwd)/data/activities.db" uv run python -m yas api &  # in background
sleep 4 && curl -sf http://localhost:8080/healthz && echo " ✓ API up"
cd frontend && npm run dev &
sleep 5 && curl -sfI http://localhost:5173/ -o /dev/null && echo "✓ frontend up"
```

In the browser (or via Playwright MCP):

1. Navigate to `/settings`. Verify all five sections render with current persisted values.
2. **Household**: edit `digest_time` to `08:30`, click Save → verify toast or absence of error; reload; value persists.
3. **Household**: enter a real address (e.g. "1600 Amphitheatre Pkwy, Mountain View, CA") in `home_address` + Save → green geocode pill appears with lat/lon.
4. **ntfy**: configure `base_url=https://ntfy.sh`, `topic=yas-test`, save → click "Send test ntfy" → verify pill shows green "Sent ✓" (or red with detail if env vars not set).
5. **Email**: pick `transport=smtp`, fill in SMTP fields with env-var names matching your real `.env`, save, test-send.
6. **Pushover**: same shape with `user_key_env`/`app_token_env` referencing your `.env`.
7. **Alert routing**: toggle `(new_match × ntfy)` cell → see optimistic update flip + persist.
8. **Disable channel**: in any channel section, click Disable → ConfirmDialog → confirm → that section's column in the routing matrix becomes disabled.
9. Stop servers: `pkill -f "yas api"; pkill -f "vite"`.

Don't auto-clean test data — these settings are real-user state on the dev box.

### Step 6: Update roadmap doc

Edit `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md`: flip page #9 (Settings) to ✅ in the master § 7 audit table.

```bash
git add docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md
git commit -m "docs(roadmap): mark master §7 page #9 closed (Phase 7-1)

Settings page editable. 7 of 9 master §7 pages now met."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

### Step 7: Push + PR

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git push -u origin phase-7-1-settings-page
gh pr create --title "phase 7-1: editable settings page" --body "$(cat <<'EOF'
## Summary

Closes master §7 page #9 (Settings). Replaces the read-only \`/settings\` with editable per-section forms covering Household basics, three channel configs (Email with smtp+forwardemail transports, ntfy, Pushover), and the Alert routing matrix.

- **5 new section components** in \`frontend/src/components/settings/\` plus a shared \`<TestSendButton>\`.
- **3 new mutation hooks**: \`useUpdateHousehold\`, \`useUpdateAlertRouting\`, \`useTestNotifier\` (canonical 5b-1b pattern; first two optimistic).
- **One new backend endpoint**: \`POST /api/notifiers/{channel}/test\`. Channel constructor failures (missing \`*_env\` vars) surface as \`{ok: false, detail: ...}\` instead of 500 (D11). Test message uses \`AlertType.new_match\` to avoid Pushover emergency mode (D12).
- **HouseholdOut** gains \`home_lat\`/\`home_lon\` so the geocode-status pill has real data (D7).
- **No HA channel** in the v1 UI (D5); no notifier code reads \`ha_config_json\`.
- **Env-var-name UX** (D6): channel forms show plain text inputs labeled "env var name" rather than password fields. Secrets stay in \`.env\`.

Frontend tests: 165 → ~197 (+32 across 7 new test files). Backend tests: 585 → ~590 (+5 for the test-send endpoint).

## Test plan

- [x] uv run pytest -q (~590 passing)
- [x] cd frontend && npm run typecheck && npm run lint clean
- [x] cd frontend && npm run test (~197 passing)
- [x] Manual smoke: edit each section + save; geocode pill renders; test-send buttons fire; routing matrix toggles persist; disable channel clears matrix column
- [ ] CI passes

## Spec / plan

- Spec: \`docs/superpowers/specs/2026-04-30-phase-7-1-settings-page-design.md\`
- Plan: \`docs/superpowers/plans/2026-04-30-phase-7-1-settings-page.md\`
- Roadmap: \`docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md\` (page #9 flipped to ✅)

## Master §7 page-coverage delta

- Closes page #9 (Settings). After this PR: **7 of 9** master §7 pages met.
- Remaining: page #2 (Offerings browser → Phase 7-2), page #3 combined calendar (Phase 8-1), page #7 (Enrollments → Phase 7-3), page #8 outbox/preview (Phase 7-4).
EOF
)"
```

Return the PR URL.

---

## Notes for the implementer

- **TanStack Form 1.29.1** uses Standard Schema — no `zodValidator` adapter needed; pass the zod schema directly to `validators: { onChange: schema, onMount: schema }`. The `onMount` validator is what makes `form.state.canSubmit` reflect "the empty form is invalid" on initial render so the Save button is disabled.
- **`form.state.canSubmit` reactivity**: wrap the Save button in `<form.Subscribe selector={(s) => s.canSubmit}>` so it re-renders when validation status changes. Inline reads of `form.state.canSubmit` may not re-trigger.
- **`form.state.isDirty`** is what the test-send button reads via the `dirty` prop on `<TestSendButton>`.
- **ApiError extraction** matches the KidForm/SiteWizard pattern: `err instanceof ApiError ? (err.body as { detail?: string })?.detail : err.message`.
- **MSW handlers in handlers.ts are defaults**; per-test `server.use(...)` overrides them. The mutation tests rely on this.
- **HouseholdPatch null vs omit (D13)**: when "Disable channel" is clicked, the patch is constructed as `{ smtp_config_json: null }` (explicit). When merely omitting a field, leave the key out entirely. The backend's `exclude_unset=True` distinguishes these.
- **`username` field in SMTP**: zod marks it optional, but the patch construction must use a conditional spread `{...(username.trim() ? { username: username.trim() } : {})}`. Sending `username: ""` → backend rejects with ValueError.
- **Don't add a `useBlocker` browser-back guard** — the page is per-section save, so navigating away after editing one section doesn't lose the saved sections.
- **No `Save All` button** at page level (D2 + the spec). Users save section-by-section. Only the routing matrix has no Save (per-cell mutations on toggle).

## Estimated test count after each task

| Task | New tests | Cumulative frontend | Cumulative backend |
|---|---|---|---|
| 1 (backend test-send + lat/lon) | 0 frontend, +5 backend | 165 | 590 |
| 2 (types + 3 hooks) | +6 | 171 | 590 |
| 3 (TestSendButton) | +3 | 174 | 590 |
| 4 (HouseholdSection) | +5 | 179 | 590 |
| 5 (EmailChannelSection) | +5 | 184 | 590 |
| 6 (Ntfy + Pushover sections) | +10 | 194 | 590 |
| 7 (AlertRoutingSection) | +5 | 199 | 590 |
| 8 (compose + smoke + PR) | 0 | 199 | 590 |

(Spec target was ~197 frontend; 199 is acceptable.)
