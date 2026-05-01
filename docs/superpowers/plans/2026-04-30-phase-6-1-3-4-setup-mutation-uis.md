# Phase 6 (1, 3, 4) — Setup-flow Mutation UIs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build setup-flow mutation UIs (Add/Edit Kid form on dedicated routes; Watchlist add/edit/delete via sheet; Site Crawl-now + Pause/Resume buttons) so a user can run v1 without curl.

**Architecture:** Three slices share the canonical 5b-1b mutation pattern but live on three distinct surfaces. Phase 6 introduces the codebase's first form library (TanStack Form + zod), first multi-date picker (react-day-picker), and first shared confirm dialog (`<ConfirmDialog>` on radix-ui's `AlertDialog`). All backend routes already exist; this is frontend-only. Implementation order: shared infra (deps + helpers + ConfirmDialog) → mutation hooks → Kid form + routes → Watchlist sheet → Site buttons → exit gates.

**Tech Stack:** React 19, TanStack Query 5, TanStack Router 1.168, TanStack Form 1.29.1 (NEW), zod 4.4.1 (NEW), react-day-picker 9.14.0 (NEW), radix-ui 1.4.3, MSW, Vitest + RTL.

**Spec:** `docs/superpowers/specs/2026-04-30-phase-6-1-3-4-setup-mutation-uis-design.md`

**Project conventions to maintain:**
- Frontend deps pinned to exact patch in `frontend/package.json` (no `^`/`~`). Use `npm install --save-exact`.
- All commits signed via 1Password SSH agent. Set `SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"` before each `git commit` in fresh shells. Verify with `git cat-file commit HEAD | grep -q '^gpgsig '`.
- Branch already exists: `phase-6-1-3-4-setup-mutation-uis`. Do NOT commit to `main`.
- Frontend gates: `npm run typecheck`, `npm run lint`, `npm run test`. Run from `frontend/`. (`format:check` has pre-existing failures; only assert files we touch are clean.)
- Frontend baseline: 67 tests (12 files). Backend baseline: 585 tests.
- Hand-maintained types in `frontend/src/lib/types.ts` mirror Pydantic schemas; keep in sync.

**Master §10 terminal-criteria delta:** This plan closes criterion #6 (UI to set school hours that produce filter-out unavailability blocks). Does NOT close criterion #1 (that's Phase 6-2).

---

## File Structure

**Create — frontend (shared infra):**
- `frontend/src/lib/form.ts` — small TanStack Form helpers + zod schema types shared across forms.
- `frontend/src/components/common/ConfirmDialog.tsx` — radix `AlertDialog` wrapper.
- `frontend/src/components/common/ConfirmDialog.test.tsx`

**Create — frontend (Kid):**
- `frontend/src/components/kids/KidForm.tsx` — shared Add/Edit form component.
- `frontend/src/components/kids/KidForm.test.tsx`
- `frontend/src/components/kids/SchoolYearRangesField.tsx` — react-day-picker multi-range wrapper.
- `frontend/src/components/kids/SchoolHolidaysField.tsx` — react-day-picker multi-date wrapper.
- `frontend/src/components/kids/InterestsField.tsx` — chip input.
- `frontend/src/components/kids/AlertOnField.tsx` — three toggles section.
- `frontend/src/routes/kids.index.tsx` — `/kids` list page.
- `frontend/src/routes/kids.new.tsx` — `/kids/new` Add form route.
- `frontend/src/routes/kids.$id.edit.tsx` — `/kids/$id/edit` Edit form route.

**Create — frontend (Watchlist):**
- `frontend/src/components/watchlist/WatchlistEntrySheet.tsx`
- `frontend/src/components/watchlist/WatchlistEntrySheet.test.tsx`

**Modify — frontend:**
- `frontend/package.json` — add three deps; pin exact.
- `frontend/src/lib/mutations.ts` — add 7 new hooks.
- `frontend/src/lib/mutations.test.tsx` — add tests for the 7 hooks.
- `frontend/src/lib/queries.ts` — confirm `useKid`, `useKids`, `useKidWatchlist` exist; add `useKidWatchlist` if missing.
- `frontend/src/lib/types.ts` — extend `Kid` shape if missing fields, add `WatchlistEntry` shape.
- `frontend/src/components/layout/KidTabs.tsx` — add edit pencil link to `/kids/$id/edit`.
- `frontend/src/routes/__root.tsx` — register new routes (or rely on file-based codegen).
- `frontend/src/routes/kids.$id.watchlist.tsx` — add "Add" button + click-to-edit + delete affordances.
- `frontend/src/routes/sites.$id.tsx` — add Crawl-now + Pause/Resume buttons.
- `frontend/src/test/handlers.ts` — MSW handlers for the 7 mutation routes.
- `frontend/src/styles/globals.css` — import react-day-picker base CSS once.

**Modify — backend (sanity check; no logic changes expected):**
- Verify `tests/integration/test_api_kids.py`, `test_api_watchlist.py`, `test_api_sites.py` exist and cover the routes the form needs. If any field is added to the API surface during integration, extend tests; otherwise no backend changes.

---

## Task 1 — Shared infra: deps + ConfirmDialog primitive (TDD)

**Files:**
- Modify: `frontend/package.json` (and `package-lock.json`)
- Create: `frontend/src/components/common/ConfirmDialog.tsx`
- Create: `frontend/src/components/common/ConfirmDialog.test.tsx`
- Modify: `frontend/src/styles/globals.css`

End state: 3 new deps installed, ConfirmDialog primitive exists with 4 tests. ~71 frontend tests total.

- [ ] **Step 1: Install deps**

```bash
cd frontend && npm install --save-exact @tanstack/react-form@1.29.1 zod@4.4.1 react-day-picker@9.14.0
```

Verify all three pinned to exact patch (no `^`/`~`) in `frontend/package.json`.

- [ ] **Step 2: Import react-day-picker base CSS**

In `frontend/src/styles/globals.css`, add at the TOP (after any existing `@import`s):

```css
@import "react-day-picker/style.css";
```

This loads the lib's default styles. Tailwind utilities + the kid form's own classes can then override per-element.

- [ ] **Step 3: Write failing ConfirmDialog tests**

Create `frontend/src/components/common/ConfirmDialog.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfirmDialog } from './ConfirmDialog';

describe('ConfirmDialog', () => {
  it('renders title + description + actions when open', () => {
    render(
      <ConfirmDialog
        open={true}
        onOpenChange={vi.fn()}
        title="Discard changes?"
        description="Your edits will be lost."
        confirmLabel="Discard"
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByText('Discard changes?')).toBeInTheDocument();
    expect(screen.getByText('Your edits will be lost.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /discard/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('calls onConfirm when confirm button clicked', async () => {
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog
        open={true}
        onOpenChange={onOpenChange}
        title="x"
        description="y"
        confirmLabel="OK"
        onConfirm={onConfirm}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /^ok$/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('calls onOpenChange(false) on cancel without onConfirm', async () => {
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog
        open={true}
        onOpenChange={onOpenChange}
        title="x"
        description="y"
        confirmLabel="OK"
        onConfirm={onConfirm}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('renders nothing when open=false', () => {
    render(
      <ConfirmDialog
        open={false}
        onOpenChange={vi.fn()}
        title="x"
        description="y"
        confirmLabel="OK"
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.queryByText('x')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run; confirm 4 FAIL**

```bash
cd frontend && npm run test -- ConfirmDialog
```

- [ ] **Step 5: Implement ConfirmDialog**

Create `frontend/src/components/common/ConfirmDialog.tsx`:

```tsx
import { AlertDialog } from 'radix-ui';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel = 'Cancel',
  destructive,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <AlertDialog.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2',
            'rounded-lg border border-border bg-background p-6 shadow-lg',
          )}
        >
          <AlertDialog.Title className="text-lg font-semibold">{title}</AlertDialog.Title>
          <AlertDialog.Description className="mt-2 text-sm text-muted-foreground">
            {description}
          </AlertDialog.Description>
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialog.Cancel asChild>
              <Button variant="outline">{cancelLabel}</Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <Button
                variant={destructive ? 'destructive' : 'default'}
                onClick={onConfirm}
              >
                {confirmLabel}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
```

- [ ] **Step 6: Re-run; confirm 4 PASS**

```bash
cd frontend && npm run test -- ConfirmDialog
```

If `AlertDialog.Portal` causes jsdom test issues (similar to the `MuteButton` `Popover.Portal` pain), drop the Portal wrapper — same fix as in `MuteButton.tsx`.

- [ ] **Step 7: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 71 passed (67 baseline + 4 new). Typecheck and lint clean.

- [ ] **Step 8: Commit (signed)**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/package.json frontend/package-lock.json frontend/src/styles/globals.css frontend/src/components/common/ConfirmDialog.tsx frontend/src/components/common/ConfirmDialog.test.tsx
git commit -m "feat(frontend): add TanStack Form + zod + react-day-picker; new ConfirmDialog

Three new deps establish Phase 6's form patterns:
- @tanstack/react-form 1.29.1 (Standard Schema validation)
- zod 4.4.1 (validation; works natively with TanStack Form v1)
- react-day-picker 9.14.0 (multi-range + multi-date pickers)

ConfirmDialog wraps radix-ui AlertDialog. Used by kid-form dirty
cancel and watchlist delete confirm. Tag refs on actions; Renovate
will pin SHAs separately."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 2 — Mutation hooks (TDD)

**Files:**
- Modify: `frontend/src/lib/mutations.ts`
- Modify: `frontend/src/lib/mutations.test.tsx`
- Modify: `frontend/src/test/handlers.ts`
- Modify: `frontend/src/lib/types.ts` (add `WatchlistEntry` interface if missing)

End state: 7 new mutation hooks following canonical pattern. Tests cover optimistic + rollback for the 5 with surgery + happy-path for 2 without. ~85 frontend tests total.

- [ ] **Step 1: Add MSW handlers** in `frontend/src/test/handlers.ts`

Append the following 7 handlers to the existing `handlers` array. The shapes mirror the Pydantic models on the backend; check `src/yas/web/routes/kids_schemas.py` and `src/yas/web/routes/watchlist_schemas.py` to confirm response shapes if uncertain:

```ts
http.post('/api/kids', async ({ request }) => {
  const body = (await request.json()) as { name: string; dob: string };
  return HttpResponse.json({
    id: 999,
    name: body.name,
    dob: body.dob,
    interests: [],
    school_weekdays: ['mon','tue','wed','thu','fri'],
    school_time_start: null,
    school_time_end: null,
    school_year_ranges: [],
    school_holidays: [],
    max_distance_mi: null,
    alert_score_threshold: 0.6,
    alert_on: {},
    notes: null,
    active: true,
    created_at: '2026-04-30T12:00:00Z',
  }, { status: 201 });
}),

http.patch('/api/kids/:id', async ({ params, request }) => {
  const body = (await request.json()) as Record<string, unknown>;
  return HttpResponse.json({
    id: Number(params.id),
    name: 'Sam',
    dob: '2019-05-01',
    interests: [],
    school_weekdays: ['mon','tue','wed','thu','fri'],
    school_time_start: null,
    school_time_end: null,
    school_year_ranges: [],
    school_holidays: [],
    max_distance_mi: null,
    alert_score_threshold: 0.6,
    alert_on: {},
    notes: null,
    active: true,
    created_at: '2026-04-30T12:00:00Z',
    ...body,
  });
}),

http.post('/api/kids/:kid_id/watchlist', async ({ params, request }) => {
  const body = (await request.json()) as { pattern: string; priority?: string };
  return HttpResponse.json({
    id: 888,
    kid_id: Number(params.kid_id),
    pattern: body.pattern,
    priority: body.priority ?? 'normal',
    site_id: null,
    ignores_hard_gates: true,
    notes: null,
    active: true,
    created_at: '2026-04-30T12:00:00Z',
  }, { status: 201 });
}),

http.patch('/api/watchlist/:id', async ({ params, request }) => {
  const body = (await request.json()) as Record<string, unknown>;
  return HttpResponse.json({
    id: Number(params.id),
    kid_id: 1,
    pattern: 't-ball',
    priority: 'normal',
    site_id: null,
    ignores_hard_gates: true,
    notes: null,
    active: true,
    created_at: '2026-04-30T12:00:00Z',
    ...body,
  });
}),

http.delete('/api/watchlist/:id', () => new HttpResponse(null, { status: 204 })),

http.post('/api/sites/:id/crawl-now', () =>
  new HttpResponse(null, { status: 202 }),
),
```

(Note: `PATCH /api/sites/:id` already has an MSW handler from Phase 5d-1.)

- [ ] **Step 2: Add `WatchlistEntry` interface** to `frontend/src/lib/types.ts` if missing. Verify with `grep "WatchlistEntry" frontend/src/lib/types.ts`. If absent:

```ts
export interface WatchlistEntry {
  id: number;
  kid_id: number;
  pattern: string;
  priority: 'low' | 'normal' | 'high';
  site_id: number | null;
  ignores_hard_gates: boolean;
  notes: string | null;
  active: boolean;
  created_at: string;
}
```

- [ ] **Step 3: Write failing mutation tests**

Append to `frontend/src/lib/mutations.test.tsx`. Add to the imports at the top:

```tsx
import {
  useCreateKid,
  useUpdateKid,
  useCreateWatchlistEntry,
  useUpdateWatchlistEntry,
  useDeleteWatchlistEntry,
  useCrawlNow,
  useToggleSiteActive,
} from './mutations';
import type { WatchlistEntry } from './types';
```

Append at the bottom (sketch — write all 7 describe blocks following the canonical pattern from `useEnrollOffering` tests in this file as the template; trim to one happy + one rollback test per surgery-having hook, one happy test per surgery-less hook):

```tsx
describe('useCreateKid', () => {
  it('POSTs and resolves with the new kid', async () => {
    const qc = new QueryClient();
    const { result } = renderHook(() => useCreateKid(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        name: 'Sam',
        dob: '2019-05-01',
        interests: [],
        school_weekdays: ['mon','tue','wed','thu','fri'],
        alert_score_threshold: 0.6,
      } as never);
    });
    expect(result.current.isSuccess).toBe(true);
  });
});

describe('useUpdateKid', () => {
  it('optimistically updates cached useKid(id) and rolls back on error', async () => {
    // happy: setQueryData(['kids', 1], { ... }) — patch — verify cache updated
    // error: server.use(...500); patch; verify rollback to original
    // (implement via the same pattern as useEnrollOffering's tests)
    // ...
  });
});

describe('useCreateWatchlistEntry', () => {
  it('POSTs and invalidates the per-kid watchlist cache', async () => {
    // happy path; verify isSuccess
  });
});

describe('useUpdateWatchlistEntry', () => {
  it('optimistically updates the entry in the kid watchlist list cache', async () => {
    // seed ['kids', 1, 'watchlist'] with [{id: 5, ...}]; patch id=5; verify
  });
});

describe('useDeleteWatchlistEntry', () => {
  it('optimistically removes the entry from the kid watchlist list cache', async () => {
    // seed; delete id=5; verify removed; rollback test
  });
});

describe('useCrawlNow', () => {
  it('POSTs to /crawl-now and resolves successfully', async () => {
    // happy path
  });
});

describe('useToggleSiteActive', () => {
  it('flips active in cached useSite(id)', async () => {
    // seed ['sites', 1] with {active: true}; mutate; verify cache active=false
  });
});
```

Filling in ~12 tests total (1 happy + 1 rollback for 5 surgery-having hooks; 1 happy each for the 2 surgery-less hooks). Keep each test under 30 lines.

- [ ] **Step 4: Run; confirm tests FAIL** (hooks not exported):

```bash
cd frontend && npm run test -- mutations
```

- [ ] **Step 5: Implement the 7 hooks**

Append to `frontend/src/lib/mutations.ts`. Each follows the canonical 5b-1b shape. Sketches below; fill in the canonical structure (`cancelQueries → snapshot → setQueryData → onError restore → awaited onSettled invalidate`):

```ts
// --- useCreateKid ---
interface CreateKidInput {
  name: string;
  dob: string;
  interests: string[];
  school_weekdays: string[];
  school_time_start?: string | null;
  school_time_end?: string | null;
  school_year_ranges?: { start: string; end: string }[];
  school_holidays?: string[];
  max_distance_mi?: number | null;
  alert_score_threshold: number;
  alert_on?: Record<string, boolean>;
  notes?: string | null;
}

export function useCreateKid() {
  const qc = useQueryClient();
  return useMutation<KidDetail, Error, CreateKidInput>({
    mutationFn: (input) => api.post<KidDetail>('/api/kids', input),
    onSettled: async () => {
      await qc.invalidateQueries({ queryKey: ['kids'] });
    },
  });
}

// --- useUpdateKid ---
interface UpdateKidInput {
  id: number;
  patch: Partial<CreateKidInput> & { active?: boolean };
}

export function useUpdateKid() {
  const qc = useQueryClient();
  type Ctx = { snapshot: KidDetail | undefined };
  return useMutation<KidDetail, Error, UpdateKidInput, Ctx>({
    mutationFn: ({ id, patch }) => api.patch<KidDetail>(`/api/kids/${id}`, patch),
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: ['kids', id] });
      const snapshot = qc.getQueryData<KidDetail>(['kids', id]);
      if (snapshot) {
        qc.setQueryData<KidDetail>(['kids', id], { ...snapshot, ...patch });
      }
      return { snapshot };
    },
    onError: (_err, { id }, ctx) => {
      if (ctx?.snapshot) qc.setQueryData(['kids', id], ctx.snapshot);
    },
    onSettled: async (_d, _e, { id }) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['kids'] }),
        qc.invalidateQueries({ queryKey: ['kids', id] }),
        qc.invalidateQueries({ queryKey: ['matches'] }),
      ]);
    },
  });
}

// --- useCreateWatchlistEntry / useUpdateWatchlistEntry / useDeleteWatchlistEntry ---
// All target ['kids', kidId, 'watchlist'] cache; same canonical shape.
// useCreate: no optimistic surgery (no server-assigned id yet); just invalidate.
// useUpdate: snapshot + replace-in-place by id.
// useDelete: snapshot + filter-out by id.
// All invalidate ['kids', kidId, 'watchlist'] AND ['matches'].

// --- useCrawlNow ---
export function useCrawlNow() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { siteId: number }>({
    mutationFn: ({ siteId }) => api.post(`/api/sites/${siteId}/crawl-now`),
    onSettled: async (_d, _e, { siteId }) => {
      await qc.invalidateQueries({ queryKey: ['sites', siteId] });
    },
  });
}

// --- useToggleSiteActive ---
interface ToggleSiteActiveInput {
  siteId: number;
  active: boolean;
}

export function useToggleSiteActive() {
  const qc = useQueryClient();
  type Ctx = { snapshot: Site | undefined };
  return useMutation<Site, Error, ToggleSiteActiveInput, Ctx>({
    mutationFn: ({ siteId, active }) =>
      api.patch<Site>(`/api/sites/${siteId}`, { active }),
    onMutate: async ({ siteId, active }) => {
      await qc.cancelQueries({ queryKey: ['sites', siteId] });
      const snapshot = qc.getQueryData<Site>(['sites', siteId]);
      if (snapshot) {
        qc.setQueryData<Site>(['sites', siteId], { ...snapshot, active });
      }
      return { snapshot };
    },
    onError: (_err, { siteId }, ctx) => {
      if (ctx?.snapshot) qc.setQueryData(['sites', siteId], ctx.snapshot);
    },
    onSettled: async (_d, _e, { siteId }) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['sites'] }),
        qc.invalidateQueries({ queryKey: ['sites', siteId] }),
      ]);
    },
  });
}
```

Add `KidDetail`, `Site` to the imports from `./types` if not already imported.

- [ ] **Step 6: Re-run; confirm tests pass**

```bash
cd frontend && npm run test -- mutations
```

Expected: ~12 new tests pass on top of the existing mutation tests.

- [ ] **Step 7: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 71 + 12 = 83 passed (or close to it; adjust as you finalize test count). Clean.

- [ ] **Step 8: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/lib/mutations.ts frontend/src/lib/mutations.test.tsx frontend/src/test/handlers.ts frontend/src/lib/types.ts
git commit -m "feat(frontend): mutation hooks for Phase 6 (kid + watchlist + site)

Seven new hooks following the canonical 5b-1b/5c-1/5d-1 pattern:

- useCreateKid: POST /api/kids
- useUpdateKid: PATCH /api/kids/{id} (optimistic update; invalidates matches)
- useCreateWatchlistEntry: POST /api/kids/{kid_id}/watchlist
- useUpdateWatchlistEntry: PATCH /api/watchlist/{id} (optimistic; in-place)
- useDeleteWatchlistEntry: DELETE /api/watchlist/{id} (optimistic remove)
- useCrawlNow: POST /api/sites/{id}/crawl-now
- useToggleSiteActive: PATCH /api/sites/{id} {active}

All invalidate the relevant query prefixes after settle. WatchlistEntry
type added to types.ts."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 3 — Kid form sub-components (TDD)

**Files:**
- Create: `frontend/src/components/kids/InterestsField.tsx`
- Create: `frontend/src/components/kids/AlertOnField.tsx`
- Create: `frontend/src/components/kids/SchoolYearRangesField.tsx`
- Create: `frontend/src/components/kids/SchoolHolidaysField.tsx`
- Create test files alongside

End state: 4 reusable form-field components. Each accepts `{ value, onChange, error? }` props and is testable in isolation. ~12 new tests.

Each subcomponent should be a controlled component (parent owns state) — TanStack Form's `<form.Field>` will pass `value` + `onChange` from `field.state.value` + `field.handleChange`. This decoupling lets us test each field component without TanStack Form context.

- [ ] **Step 1: `InterestsField` — chip input**

Tests (`InterestsField.test.tsx`):
- Initially renders all current interests as chips with × buttons
- Typing + Enter adds a chip and clears the input
- Typing + comma adds a chip
- Click × removes a chip
- Empty trimmed input doesn't add an empty chip
- Duplicate (case-insensitive) doesn't add

Component (`InterestsField.tsx`):
```tsx
interface Props {
  value: string[];
  onChange: (value: string[]) => void;
  error?: string;
}

export function InterestsField({ value, onChange, error }: Props) {
  const [input, setInput] = useState('');
  const add = (raw: string) => {
    const trimmed = raw.trim();
    if (!trimmed) return;
    if (value.some((v) => v.toLowerCase() === trimmed.toLowerCase())) return;
    onChange([...value, trimmed]);
    setInput('');
  };
  const remove = (i: number) => onChange(value.filter((_, idx) => idx !== i));

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-1">
        {value.map((v, i) => (
          <span key={`${v}-${i}`} className="inline-flex items-center gap-1 rounded-md bg-accent px-2 py-1 text-xs">
            {v}
            <button type="button" aria-label={`Remove ${v}`} onClick={() => remove(i)}>×</button>
          </span>
        ))}
      </div>
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            add(input);
          }
        }}
        onBlur={() => add(input)}
        placeholder="Type and press Enter (e.g., baseball)"
        aria-invalid={error ? 'true' : undefined}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
```

- [ ] **Step 2: `AlertOnField` — three toggles**

Tests:
- Renders 3 toggles labeled "New matches", "Watchlist hits", "Registration opens"
- All default checked when value `{}` (treats missing key as true)
- Clicking a toggle calls onChange with `{...value, key: false}`

Component:
```tsx
const KEYS = [
  { key: 'new_match', label: 'New matches' },
  { key: 'watchlist_hit', label: 'Watchlist hits' },
  { key: 'reg_opens', label: 'Registration opens' },
] as const;

interface Props {
  value: Record<string, boolean>;
  onChange: (value: Record<string, boolean>) => void;
}

export function AlertOnField({ value, onChange }: Props) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">Alert types</legend>
      {KEYS.map(({ key, label }) => (
        <label key={key} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={value[key] !== false}  // missing or true → on
            onChange={(e) => onChange({ ...value, [key]: e.target.checked })}
          />
          {label}
        </label>
      ))}
    </fieldset>
  );
}
```

- [ ] **Step 3: `SchoolHolidaysField` — react-day-picker multi-date**

Tests:
- Calendar renders with no selections by default
- Clicking a date adds it to the chip row + onChange called with `[date]`
- Clicking a selected date removes it
- Clicking × on a chip removes that date

Component sketch:
```tsx
import { DayPicker } from 'react-day-picker';
import { format } from 'date-fns';

interface Props {
  value: string[];  // ISO date strings
  onChange: (value: string[]) => void;
  error?: string;
}

export function SchoolHolidaysField({ value, onChange, error }: Props) {
  const dates = value.map((s) => new Date(s));
  const handleSelect = (selected: Date[] | undefined) => {
    onChange((selected ?? []).map((d) => format(d, 'yyyy-MM-dd')));
  };
  return (
    <div className="space-y-2">
      <DayPicker
        mode="multiple"
        selected={dates}
        onSelect={handleSelect}
      />
      <div className="flex flex-wrap gap-1">
        {value.map((d, i) => (
          <span key={d} className="inline-flex items-center gap-1 rounded bg-accent px-2 py-1 text-xs">
            {format(new Date(d), 'MMM d, yyyy')}
            <button type="button" aria-label={`Remove ${d}`} onClick={() =>
              onChange(value.filter((_, idx) => idx !== i))
            }>×</button>
          </span>
        ))}
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
```

- [ ] **Step 4: `SchoolYearRangesField` — react-day-picker multi-range**

Tests:
- Calendar renders with no selections
- Drag-selecting a range adds `{start, end}` chip
- Click × on a chip removes that range

Note: react-day-picker's "multiple ranges" requires `mode="range"` for ONE range. For multiple ranges, a common pattern is:
- Use `mode="single"` for the START date
- Then `mode="single"` again for the END date
- OR maintain external state and use `mode="default"` with custom click handling

Simplest practical approach for a single-household app: a button "+ Add school year range" → opens a small inline `mode="range"` picker → on confirm, adds `{start, end}` to the list. Each range row shows below as a chip with start/end + ×.

This is technically the C2 ("chip + dialog") that the spec discussed but with the actual range-picker for selection. Acceptable — the user gets a real range picker per range.

Component sketch:
```tsx
import { useState } from 'react';
import { DayPicker, DateRange } from 'react-day-picker';
import { format } from 'date-fns';

interface YearRange {
  start: string;  // ISO
  end: string;
}

interface Props {
  value: YearRange[];
  onChange: (value: YearRange[]) => void;
  error?: string;
}

export function SchoolYearRangesField({ value, onChange, error }: Props) {
  const [draft, setDraft] = useState<DateRange | undefined>();
  const [open, setOpen] = useState(false);

  const commit = () => {
    if (!draft?.from || !draft?.to) return;
    onChange([
      ...value,
      {
        start: format(draft.from, 'yyyy-MM-dd'),
        end: format(draft.to, 'yyyy-MM-dd'),
      },
    ]);
    setDraft(undefined);
    setOpen(false);
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {value.map((r, i) => (
          <span key={`${r.start}-${r.end}`} className="inline-flex items-center gap-1 rounded bg-accent px-2 py-1 text-xs">
            {format(new Date(r.start), 'MMM d, yyyy')} → {format(new Date(r.end), 'MMM d, yyyy')}
            <button type="button" aria-label={`Remove range ${i}`} onClick={() =>
              onChange(value.filter((_, idx) => idx !== i))
            }>×</button>
          </span>
        ))}
      </div>
      {!open && (
        <button type="button" onClick={() => setOpen(true)} className="text-sm underline">
          + Add school year range
        </button>
      )}
      {open && (
        <div className="rounded-md border border-border p-2">
          <DayPicker mode="range" selected={draft} onSelect={setDraft} />
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" onClick={() => { setDraft(undefined); setOpen(false); }}>Cancel</button>
            <button type="button" disabled={!draft?.from || !draft?.to} onClick={commit}>Add</button>
          </div>
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
```

- [ ] **Step 5: Run all 4 sub-component test files; confirm pass**

```bash
cd frontend && npm run test -- InterestsField AlertOnField SchoolHolidaysField SchoolYearRangesField
```

- [ ] **Step 6: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

- [ ] **Step 7: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/components/kids/
git commit -m "feat(frontend): kid-form sub-component fields

Four controlled-component fields, each with its own tests:

- InterestsField: chip input (Enter/comma to add, × to remove,
  case-insensitive dedup, blur-add-on-typing)
- AlertOnField: 3 toggles (new_match, watchlist_hit, reg_opens);
  treats missing keys as true (matches backend's default behavior)
- SchoolHolidaysField: react-day-picker mode='multiple' single dates
  with chip display + remove
- SchoolYearRangesField: chip list + 'Add range' button opens an inline
  mode='range' picker; commit appends to the list (chip-and-dialog
  pattern since react-day-picker doesn't support multiple ranges natively)"
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 4 — `<KidForm>` shared component (TDD)

**Files:**
- Create: `frontend/src/components/kids/KidForm.tsx`
- Create: `frontend/src/components/kids/KidForm.test.tsx`

End state: One component handles both Add and Edit modes via `mode` prop. Form state via TanStack Form, validation via zod. Dirty-state tracking, cancel-confirm, submit + error rendering. ~6 tests.

- [ ] **Step 1: Write failing tests**

Tests cover:
1. Add mode: renders empty form + "Save" + "Cancel" buttons
2. Edit mode: pre-populates from `useKid(id)` data
3. Required field empty → submit disabled
4. Valid form → submit calls `useCreateKid` (Add) or `useUpdateKid` (Edit) with correct payload
5. Server error renders inline ErrorBanner
6. Dirty cancel → ConfirmDialog opens; clean cancel → no dialog

(Don't try to test every individual sub-component again — those are tested separately. Focus on form glue: validation, submit flow, dirty tracking.)

- [ ] **Step 2: Define zod schema**

In a new helper or co-located in `KidForm.tsx`:

```tsx
import { z } from 'zod';

export const kidSchema = z.object({
  name: z.string().trim().min(1, 'Name is required').max(80),
  dob: z.string().refine((s) => {
    const d = new Date(s);
    const now = new Date();
    const minBound = new Date(now.getFullYear() - 100, now.getMonth(), now.getDate());
    return !isNaN(d.getTime()) && d <= now && d >= minBound;
  }, 'DOB must be a valid date in the past 100 years'),
  interests: z.array(z.string().trim().min(1)).max(20),
  school_weekdays: z.array(z.enum(['mon','tue','wed','thu','fri','sat','sun'])),
  school_time_start: z.string().nullable(),
  school_time_end: z.string().nullable(),
  school_year_ranges: z.array(z.object({ start: z.string(), end: z.string() })).refine(
    (ranges) => ranges.every((r) => r.start <= r.end),
    'Each school year range must have start before end',
  ),
  school_holidays: z.array(z.string()),
  max_distance_mi: z.number().min(1).max(50).nullable(),
  alert_score_threshold: z.number().min(0).max(1),
  alert_on: z.record(z.string(), z.boolean()),
  notes: z.string().max(2000).nullable(),
  active: z.boolean(),
}).refine(
  (data) => {
    if (data.school_time_start && data.school_time_end) {
      return data.school_time_start < data.school_time_end;
    }
    return true;
  },
  { message: 'School day start must be before end', path: ['school_time_end'] },
);

export type KidFormValues = z.infer<typeof kidSchema>;
```

- [ ] **Step 3: Implement the component**

```tsx
import { useForm } from '@tanstack/react-form';
import { useNavigate } from '@tanstack/react-router';
import { useState } from 'react';
import { kidSchema, type KidFormValues } from './kidSchema';
import { useCreateKid, useUpdateKid } from '@/lib/mutations';
import { useKid } from '@/lib/queries';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { InterestsField } from './InterestsField';
import { AlertOnField } from './AlertOnField';
import { SchoolHolidaysField } from './SchoolHolidaysField';
import { SchoolYearRangesField } from './SchoolYearRangesField';
import { Button } from '@/components/ui/button';

interface KidFormProps {
  mode: 'create' | 'edit';
  id?: number;
}

export function KidForm({ mode, id }: KidFormProps) {
  const navigate = useNavigate();
  const create = useCreateKid();
  const update = useUpdateKid();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  // useKid called unconditionally (Rules of Hooks); `enabled` gates the network call.
  // For create mode, we pass id=0 + enabled=false so it never runs.
  const kidQuery = useKid(mode === 'edit' && id ? id : 0);

  // Edit mode + data still loading → render Skeleton until kid data arrives,
  // THEN mount the form below. This avoids the "defaultValues only captured
  // at first render" problem (form would otherwise stay empty if data arrived
  // after the form mounted).
  if (mode === 'edit' && (kidQuery.isLoading || !kidQuery.data)) {
    return <Skeleton className="h-96 w-full max-w-2xl" />;
  }
  // From here, kidQuery.data is defined in edit mode (or we're in create mode).

  const form = useForm({
    defaultValues: {
      name: '',
      dob: '',
      interests: [],
      school_weekdays: ['mon','tue','wed','thu','fri'],
      school_time_start: null,
      school_time_end: null,
      school_year_ranges: [],
      school_holidays: [],
      max_distance_mi: null,
      alert_score_threshold: 0.6,
      alert_on: {},
      notes: null,
      active: true,
      ...(mode === 'edit' ? kidQuery.data : {}),
    } as KidFormValues,
    validators: {
      onChange: kidSchema,
    },
    onSubmit: async ({ value }) => {
      setErrorMsg(null);
      try {
        if (mode === 'create') {
          const created = await create.mutateAsync(value);
          navigate({ to: '/kids/$id/matches', params: { id: String(created.id) } });
        } else if (id) {
          await update.mutateAsync({ id, patch: value });
          navigate({ to: '/kids/$id/matches', params: { id: String(id) } });
        }
      } catch (err) {
        setErrorMsg((err as Error).message ?? 'Failed to save');
      }
    },
  });

  const inFlight = create.isPending || update.isPending;

  const handleCancel = () => {
    if (form.state.isDirty) {
      setShowCancelConfirm(true);
    } else {
      navigateBack();
    }
  };

  const navigateBack = () => {
    if (mode === 'edit' && id) {
      navigate({ to: '/kids/$id/matches', params: { id: String(id) } });
    } else {
      navigate({ to: '/kids' });
    }
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        form.handleSubmit();
      }}
      className="max-w-2xl space-y-6"
    >
      {errorMsg && <ErrorBanner message={errorMsg} />}

      <form.Field
        name="name"
        children={(field) => (
          <div>
            <label htmlFor="name" className="block text-sm font-medium">Name</label>
            <input
              id="name"
              autoFocus={mode === 'create'}
              type="text"
              value={field.state.value}
              onChange={(e) => field.handleChange(e.target.value)}
              onBlur={field.handleBlur}
              aria-invalid={field.state.meta.errors.length > 0}
            />
            {field.state.meta.errors.map((err, i) => (
              <p key={i} className="text-xs text-destructive">{String(err)}</p>
            ))}
          </div>
        )}
      />

      {/* dob field, similar pattern */}
      {/* school_weekdays — checkbox group */}
      {/* school_time_start, school_time_end — two time inputs */}
      <form.Field
        name="interests"
        children={(field) => (
          <InterestsField
            value={field.state.value}
            onChange={field.handleChange}
            error={field.state.meta.errors[0] ? String(field.state.meta.errors[0]) : undefined}
          />
        )}
      />
      <form.Field
        name="school_year_ranges"
        children={(field) => (
          <SchoolYearRangesField
            value={field.state.value}
            onChange={field.handleChange}
          />
        )}
      />
      <form.Field
        name="school_holidays"
        children={(field) => (
          <SchoolHolidaysField
            value={field.state.value}
            onChange={field.handleChange}
          />
        )}
      />
      {/* max_distance_mi — slider + checkbox */}
      {/* alert_score_threshold — slider */}
      <form.Field
        name="alert_on"
        children={(field) => (
          <AlertOnField
            value={field.state.value}
            onChange={field.handleChange}
          />
        )}
      />
      {/* notes — textarea */}
      {mode === 'edit' && (
        <form.Field
          name="active"
          children={(field) => (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={field.state.value}
                onChange={(e) => field.handleChange(e.target.checked)}
              />
              Active
            </label>
          )}
        />
      )}

      <div className="flex gap-2">
        <Button type="submit" disabled={inFlight || !form.state.canSubmit}>
          {inFlight ? 'Saving…' : 'Save'}
        </Button>
        <Button type="button" variant="outline" onClick={handleCancel} disabled={inFlight}>
          Cancel
        </Button>
      </div>

      <ConfirmDialog
        open={showCancelConfirm}
        onOpenChange={setShowCancelConfirm}
        title="Discard changes?"
        description="Your edits will be lost."
        confirmLabel="Discard"
        destructive
        onConfirm={() => {
          setShowCancelConfirm(false);
          navigateBack();
        }}
      />
    </form>
  );
}
```

(Many fields elided for brevity in the sketch — fill in `dob`, `school_weekdays`, school times, `max_distance_mi`, `alert_score_threshold`, `notes`, `school_time_start/end` following the same `<form.Field>` pattern.)

- [ ] **Step 4: Re-run tests; confirm 6 PASS**

```bash
cd frontend && npm run test -- KidForm
```

- [ ] **Step 5: Frontend gates**

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/kids/KidForm.tsx frontend/src/components/kids/KidForm.test.tsx
git commit -m "feat(frontend): KidForm shared component (Add + Edit modes)

TanStack Form + zod validation. Composes the 4 sub-component fields
plus inline name/dob/school_weekdays/school_times/max_distance/
alert_score_threshold/notes/active fields.

Add mode → POST + redirect to /kids/{newId}/matches.
Edit mode → PATCH + redirect to /kids/{id}/matches.
Dirty cancel → ConfirmDialog. Clean cancel → navigate immediately."
```

---

## Task 5 — Kid routes + index page (TDD)

**Files:**
- Create: `frontend/src/routes/kids.index.tsx`
- Create: `frontend/src/routes/kids.new.tsx`
- Create: `frontend/src/routes/kids.$id.edit.tsx`
- Create: `frontend/src/routes/kids.index.test.tsx`
- Modify: `frontend/src/components/layout/KidTabs.tsx` (add edit pencil)

End state: Three new routes exist. KidTabs shows edit pencil on `/kids/$id/*` tabs (hidden on `/edit` itself). ~3 new tests for the index page.

- [ ] **Step 1: `/kids/new` route file**

```tsx
// frontend/src/routes/kids.new.tsx
import { createFileRoute } from '@tanstack/react-router';
import { KidForm } from '@/components/kids/KidForm';

export const Route = createFileRoute('/kids/new')({ component: NewKidPage });

function NewKidPage() {
  return (
    <div className="p-4">
      <h1 className="text-xl font-semibold mb-4">Add kid</h1>
      <KidForm mode="create" />
    </div>
  );
}
```

- [ ] **Step 2: `/kids/$id/edit` route file**

```tsx
// frontend/src/routes/kids.$id.edit.tsx
import { createFileRoute } from '@tanstack/react-router';
import { KidForm } from '@/components/kids/KidForm';

export const Route = createFileRoute('/kids/$id/edit')({ component: EditKidPage });

function EditKidPage() {
  const { id } = Route.useParams();
  return (
    <div className="p-4">
      <h1 className="text-xl font-semibold mb-4">Edit kid</h1>
      <KidForm mode="edit" id={Number(id)} />
    </div>
  );
}
```

- [ ] **Step 3: `/kids` index page (TDD)**

Tests for `frontend/src/routes/kids.index.test.tsx`:
- Empty state renders "No kids yet"
- Lists kid cards with name + age
- "Add kid" button has href `/kids/new`

Implementation:
```tsx
// frontend/src/routes/kids.index.tsx
import { createFileRoute, Link } from '@tanstack/react-router';
import { useKids } from '@/lib/queries';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { differenceInYears } from 'date-fns';

export const Route = createFileRoute('/kids/')({ component: KidsIndexPage });

function KidsIndexPage() {
  const { data: kids, isLoading } = useKids();

  if (isLoading) return <Skeleton className="h-32 w-full" />;

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Kids</h1>
        <Button asChild>
          <Link to="/kids/new">Add kid</Link>
        </Button>
      </div>
      {(!kids || kids.length === 0) ? (
        <div className="text-muted-foreground text-sm">
          No kids yet — Add your first kid to start matching.
        </div>
      ) : (
        <ul className="space-y-2">
          {kids.map((k) => (
            <li key={k.id} className="rounded-md border border-border p-3 flex items-center justify-between">
              <Link to="/kids/$id/matches" params={{ id: String(k.id) }} className="flex-1">
                <div className="font-medium">{k.name}</div>
                <div className="text-xs text-muted-foreground">
                  {differenceInYears(new Date(), new Date(k.dob))} years old
                  {k.active === false && ' · Inactive'}
                </div>
              </Link>
              <Link to="/kids/$id/edit" params={{ id: String(k.id) }} aria-label={`Edit ${k.name}`}>
                ✏️
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Add edit pencil to KidTabs**

In `frontend/src/components/layout/KidTabs.tsx`, the existing component renders kid name + tab nav. Add an edit pencil link aligned right:

```tsx
import { Link, useLocation } from '@tanstack/react-router';
// ...

export function KidTabs({ kidId }: { kidId: number }) {
  const loc = useLocation();
  const onEditPage = loc.pathname.endsWith('/edit');
  return (
    <nav className="border-b border-border flex items-center gap-2 mb-4">
      <div className="flex flex-1 gap-2">
        {tabs.map(...)}
      </div>
      {!onEditPage && (
        <Link
          to="/kids/$id/edit"
          params={{ id: String(kidId) }}
          aria-label="Edit kid"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ✏️ Edit
        </Link>
      )}
    </nav>
  );
}
```

- [ ] **Step 5: Trigger TanStack Router codegen**

```bash
cd frontend && npm run build
```

This regenerates `routeTree.gen.ts` with the three new routes. (Or run `npm run dev` briefly.)

- [ ] **Step 6: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

- [ ] **Step 7: Commit**

```bash
git add 'frontend/src/routes/kids.index.tsx' 'frontend/src/routes/kids.new.tsx' 'frontend/src/routes/kids.$id.edit.tsx' frontend/src/routes/kids.index.test.tsx frontend/src/routeTree.gen.ts frontend/src/components/layout/KidTabs.tsx
git commit -m "feat(frontend): /kids index + Add/Edit routes + edit pencil in KidTabs

/kids — list of kid cards with edit pencil per row + 'Add kid' button.
/kids/new — Add form using <KidForm mode='create'>.
/kids/\$id/edit — Edit form using <KidForm mode='edit'>.
KidTabs gains an edit pencil link to /kids/\$id/edit, hidden when
already on the edit route."
```

---

## Task 6 — Watchlist sheet (TDD)

**Files:**
- Create: `frontend/src/components/watchlist/WatchlistEntrySheet.tsx`
- Create: `frontend/src/components/watchlist/WatchlistEntrySheet.test.tsx`
- Modify: `frontend/src/routes/kids.$id.watchlist.tsx`

End state: Sheet handles add/edit; watchlist tab gains Add button + click-to-edit + delete-with-confirm. ~4 sheet tests + ~2 watchlist tab integration tests.

- [ ] **Step 1: Define zod schema** for watchlist entry fields (in `WatchlistEntrySheet.tsx` or a co-located helper):

```tsx
const watchlistSchema = z.object({
  pattern: z.string().trim().min(1, 'Pattern is required').max(200),
  priority: z.enum(['low', 'normal', 'high']),
  site_id: z.number().int().nullable(),
  ignores_hard_gates: z.boolean(),
  notes: z.string().max(500).nullable(),
  active: z.boolean(),
});
```

- [ ] **Step 2: Write failing tests** in `WatchlistEntrySheet.test.tsx`:

  1. Add mode: renders empty pattern field + "Save" + "Cancel"
  2. Edit mode: pre-populates from entry data
  3. Submit valid form in Add mode → calls `useCreateWatchlistEntry` with right payload + closes sheet
  4. Server error → inline ErrorBanner; sheet stays open

- [ ] **Step 3: Implement `<WatchlistEntrySheet>`**

```tsx
interface Props {
  kidId: number;
  mode: 'create' | 'edit';
  entry?: WatchlistEntry;  // required when mode='edit'
  open: boolean;
  onClose: () => void;
}
```

Same TanStack Form + zod pattern as `<KidForm>`. Sheet wrapper from `@/components/ui/sheet`. Submit calls `useCreateWatchlistEntry` (Add) or `useUpdateWatchlistEntry` (Edit). On success → `onClose()`.

Same dirty-cancel ConfirmDialog pattern as KidForm.

- [ ] **Step 4: Modify `kids.$id.watchlist.tsx`**

Add three pieces:

  1. State: `const [editing, setEditing] = useState<WatchlistEntry | null>(null); const [creating, setCreating] = useState(false);`
  2. "Add watchlist entry" button at top → `setCreating(true)`
  3. Each row gets click handler → `setEditing(entry)` AND a small × delete button → triggers ConfirmDialog → `useDeleteWatchlistEntry.mutate({ kidId, entryId: entry.id })`. Use `e.stopPropagation()` on the × button so it doesn't trigger the row click (lesson from 5d-1's MatchCard).
  4. Render `<WatchlistEntrySheet kidId={kidId} mode="create" open={creating} onClose={() => setCreating(false)} />` and `<WatchlistEntrySheet kidId={kidId} mode="edit" entry={editing!} open={editing !== null} onClose={() => setEditing(null)} />`

Watchlist tab tests cover: Add button opens sheet (creating=true); clicking a row opens sheet (editing=entry); delete × shows ConfirmDialog.

- [ ] **Step 5: Run all watchlist tests; confirm pass**

```bash
cd frontend && npm run test -- WatchlistEntrySheet watchlist
```

- [ ] **Step 6: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/watchlist/ 'frontend/src/routes/kids.$id.watchlist.tsx'
git commit -m "feat(frontend): WatchlistEntrySheet + watchlist tab mutation affordances

Sheet supports Add + Edit modes. Watchlist tab gains:
- 'Add watchlist entry' button (top right)
- Click any row → opens sheet in edit mode pre-populated
- × delete button on each row → ConfirmDialog → useDeleteWatchlistEntry

stopPropagation on the × button prevents the row's click handler
from firing simultaneously (MatchCard pattern from 5d-1)."
```

---

## Task 7 — Site detail page: Crawl-now + Pause/Resume (TDD)

**Files:**
- Modify: `frontend/src/routes/sites.$id.tsx`
- Modify: `frontend/src/routes/sites.$id.test.tsx` (or extend existing)

End state: Site detail page header has "Crawl now" button + "Pause/Resume" toggle. ~3 new tests.

- [ ] **Step 1: Tests**

```tsx
it('"Crawl now" button fires useCrawlNow', async () => {
  // render sites.$id with siteId=1
  // click button labeled /crawl now/i
  // verify mutation fires (assert button shows "Queued ✓" briefly)
});

it('"Pause" button toggles site.active to false', async () => {
  // seed useSite(1) with {active: true}
  // click "Pause"
  // verify cache updated optimistically
});

it('"Resume" button shows when site is paused', () => {
  // seed useSite(1) with {active: false}
  // expect "Resume" button to be present, not "Pause"
});
```

- [ ] **Step 2: Modify `frontend/src/routes/sites.$id.tsx`**

Add to header section (alongside existing mute button):

```tsx
import { useCrawlNow, useToggleSiteActive } from '@/lib/mutations';

// inside component:
const crawlNow = useCrawlNow();
const toggleActive = useToggleSiteActive();
const [crawlQueued, setCrawlQueued] = useState(false);

const handleCrawlNow = () => {
  crawlNow.mutate(
    { siteId },
    {
      onSuccess: () => {
        setCrawlQueued(true);
        setTimeout(() => setCrawlQueued(false), 2000);
      },
    },
  );
};

// in JSX header:
<div className="flex items-center gap-2">
  <Button onClick={handleCrawlNow} disabled={crawlNow.isPending}>
    {crawlQueued ? 'Queued ✓' : 'Crawl now'}
  </Button>
  <Button
    variant="outline"
    onClick={() => toggleActive.mutate({ siteId, active: !site.active })}
    disabled={toggleActive.isPending}
  >
    {site.active ? 'Pause' : 'Resume'}
  </Button>
  {site.active === false && <span className="text-xs ...">Paused</span>}
  <MuteButton ... />
</div>
```

- [ ] **Step 3: Frontend gates + commit**

---

## Task 8 — Final exit gates + manual smoke + push + PR

End state: All §12 exit criteria from the spec verified.

- [ ] **Step 1: Backend + frontend gates**

```bash
uv run pytest -q --no-cov  # 585 still passing (no backend changes)
cd frontend && npm run typecheck && npm run lint && npm run test
```

- [ ] **Step 2: Manual smoke**

Run the §9 walkthrough from the spec end-to-end against a freshly-redeployed dev stack. Capture any UX surprises as regression tests.

Critical verification: master §10 criterion #6. Create a kid via the form with school hours 8–3 Mon–Fri + a school year range that includes "today". Add a site (via curl since 6-2 isn't built yet) with an offering whose `time_start=10:00`, `time_end=11:00`, `days_of_week=["wed"]`, `start_date=today`. Verify the offering doesn't appear as a match. Edit the kid; remove the school year range. Verify the offering NOW appears as a match.

- [ ] **Step 3: Push + PR**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git push -u origin phase-6-1-3-4-setup-mutation-uis
gh pr create --title "phase 6 (1, 3, 4): setup-flow mutation UIs" --body "$(cat <<'EOF'
## Summary

Closes master §10 criterion #6 (UI for setting kid school hours that produce match-filtering unavailability blocks). Establishes Phase 6's form patterns for Phase 7 to inherit.

- 6-1: \`/kids\` list + \`/kids/new\` Add + \`/kids/\$id/edit\` Edit, all using shared \`<KidForm>\` (TanStack Form + zod)
- 6-3: \`<WatchlistEntrySheet>\` for add/edit + delete-with-confirm on watchlist tab
- 6-4: "Crawl now" + "Pause/Resume" buttons on site detail page

3 new frontend deps: @tanstack/react-form, zod, react-day-picker.
1 new shared primitive: \`<ConfirmDialog>\` (radix-ui AlertDialog).
7 new mutation hooks following canonical 5b-1b pattern.

## Test plan

- [x] uv run pytest -q (585 passing, no backend changes)
- [x] cd frontend && npm run typecheck && npm run lint clean
- [x] cd frontend && npm run test (~95 passing; +28 new across 8 files)
- [x] Manual smoke: setup-flow walkthrough end-to-end
- [x] Master §10 criterion #6 explicitly verified
- [ ] CI passes

## Spec / plan

- Spec: docs/superpowers/specs/2026-04-30-phase-6-1-3-4-setup-mutation-uis-design.md
- Plan: docs/superpowers/plans/2026-04-30-phase-6-1-3-4-setup-mutation-uis.md
- Roadmap: docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md (§6 Phase 6)

## Master §10 terminal-criteria delta

- Closes criterion #6 (school-hours UI). Backend already shipped; this UI provides the criterion's "user can set" affordance.
- Does NOT close criterion #1 (Add Site wizard) — that's Phase 6-2.

After this lands: 7 of 8 v1 terminal criteria met. Criterion #4 (30-day observation) becomes runnable as soon as #1 lands.
EOF
)"
```

---

## Notes for the implementer

- **First form library establishes precedent for Phase 7.** Watch the patterns you set: error message rendering, dirty tracking, submit timing, focus-on-error. Phase 7's Settings will be 5+ more forms; the pattern you establish here will be inherited.
- **`useKid(id)` may be undefined on first render of edit mode** — handle the loading state in `<KidForm>` so we don't try to pre-populate from undefined. The simplest path: render Skeleton until `kidQuery.data` is available, then render the form.
- **TanStack Form's `validators.onChange: zodSchema`** runs validation on every change — fine for v1, but watch for performance on the school year ranges field (lots of dates). If sluggish, switch to `onBlur` validation per-field.
- **`@tanstack/react-form`'s `<form.Field name="x" children={...}>`** is the v1 API. The render-prop child receives a `field` object with `state.value`, `handleChange`, `handleBlur`, `state.meta.errors`. Don't reach for `useField` from RHF muscle memory.
- **`useBlocker` for browser navigation guards** — TanStack Router's hook, takes `{shouldBlockFn: () => boolean}`. Wire it to `form.state.isDirty` so the user gets the same confirm dialog whether they click Cancel or hit the browser back button.
- **react-day-picker's `mode="multiple"`** emits `Date[] | undefined` on `onSelect`. Convert to ISO date strings (`format(d, 'yyyy-MM-dd')`) before storing in form state, so the values match backend expectations.
- **ConfirmDialog reuse** — built once in Task 1, used twice (kid form dirty cancel; watchlist delete). Do NOT roll a third dialog primitive.
- **Renovate + tag refs** — same pattern as the chore/ deps PRs: any new GitHub Actions used here go in as `@vX.Y.Z` tag refs; Renovate pins SHAs after push.

## Estimated test count after each task

| Task | New tests | Cumulative |
|---|---|---|
| 1 (ConfirmDialog + deps) | 4 | 71 |
| 2 (mutation hooks) | ~12 | ~83 |
| 3 (sub-component fields) | ~12 | ~95 |
| 4 (KidForm) | ~6 | ~101 |
| 5 (kid routes + index) | ~3 | ~104 |
| 6 (watchlist sheet) | ~6 | ~110 |
| 7 (site buttons) | ~3 | ~113 |

Frontend baseline pre-Phase-6: 67. Final: ~113. Backend unchanged at 585.
