# Phase 8-1: Combined Multi-Kid Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new top-level `/calendar` route that overlays all active kids' enrollments, unavailability, and (optional) matches in one calendar view, color-coded by kid.

**Architecture:** Frontend-only. Reuses the existing `GET /api/kids/{kid_id}/calendar` endpoint by parallel-fetching across active kids via TanStack Query's `useQueries`. Pure-function merge step injects `kid_id` and a `"{name}: {title}"` prefix; `<CalendarView>` gets a small optional `eventStyle` hook to layer kid color onto the existing kind-based class names. New filter component for kid + event-type checkboxes. URL state mirrors Phase 7-4 alerts pattern (untyped string passthrough via `validateSearch`).

**Tech Stack:** React 19, TanStack Router (file-based routing), TanStack Query 5 (`useQueries`), react-big-calendar, date-fns, Tailwind, vitest + Testing Library, MSW for API mocking in tests.

**Spec:** `docs/superpowers/specs/2026-05-02-phase-8-1-combined-calendar-design.md`

---

## File Structure

### Create

| File | Responsibility |
|---|---|
| `frontend/src/lib/calendarRange.ts` | `rangeFor(view, cursor)` + `BUFFER_DAYS` — extracted from per-kid route |
| `frontend/src/lib/calendarRange.test.ts` | Range computation tests (week / month boundaries, buffer days) |
| `frontend/src/lib/calendarColors.ts` | 8-color palette + `colorForKid(kidId)` indexer |
| `frontend/src/lib/calendarColors.test.ts` | Stable assignment by id, no in-palette collisions |
| `frontend/src/lib/combinedCalendar.ts` | Pure `mergeKidCalendars(responses, kidsById, filters): CombinedCalendarEvent[]` |
| `frontend/src/lib/combinedCalendar.test.ts` | Merge ordering, kid filter, type filter, empty inputs |
| `frontend/src/components/calendar/CombinedCalendarFilters.tsx` | Kid checkboxes (with color swatches) + type checkboxes + Clear button |
| `frontend/src/components/calendar/CombinedCalendarFilters.test.tsx` | Render, toggle interactions, Clear visibility |
| `frontend/src/routes/calendar.tsx` | Route + state + URL params + fan-out queries |
| `frontend/src/routes/-calendar.test.tsx` | Skeleton → events render, URL filter changes, empty states |

### Modify

| File | Change |
|---|---|
| `frontend/src/lib/types.ts` | Add `CombinedCalendarEvent` + `CombinedCalendarFilterState` |
| `frontend/src/components/calendar/CalendarView.tsx` | Optional `eventStyle?(event)` prop with className-concat + style-shallow-merge composition |
| `frontend/src/routes/kids.$id.calendar.tsx` | Replace inline `rangeFor`/`BUFFER_DAYS` with import from `lib/calendarRange.ts` |
| `frontend/src/components/layout/TopBar.tsx` (+ test) | Add `Calendar` link with `CalendarDays` icon between Kids and Offerings |

---

## Task Order Rationale

Each task produces a self-contained, testable change. Order minimizes rework:

1. **Range helper extraction** — pure refactor, no new behavior. Lowest risk, unblocks the new route.
2. **Color palette** — pure module, no deps on other tasks.
3. **Type additions** — extends existing types non-destructively.
4. **Merge function** — pure, depends on (3) types only.
5. **`CalendarView` `eventStyle` prop** — additive, optional, no callers change.
6. **Filters component** — depends on (2) for swatches, (3) for filter state shape.
7. **Route assembly** — wires (1)-(6) together. Biggest task, most integration.
8. **TopBar link** — enables nav once the route exists.
9. **Smoke + roadmap + PR** — finalize.

---

## Task 1: Lift range helper to shared module

**Files:**
- Create: `frontend/src/lib/calendarRange.ts`
- Create: `frontend/src/lib/calendarRange.test.ts`
- Modify: `frontend/src/routes/kids.$id.calendar.tsx` (replace inline `rangeFor` with import)

Pure refactor: no behavior change, just moves the inline `rangeFor` and `BUFFER_DAYS` from the per-kid route into a shared module so the new combined route can import the same logic.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/calendarRange.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { rangeFor, BUFFER_DAYS } from './calendarRange';

describe('rangeFor', () => {
  it('returns week range with 3-day buffer on either side', () => {
    // Wednesday 2026-05-13 — week (Sun-start) is May 10-16
    const { from, to } = rangeFor('week', new Date(2026, 4, 13));
    expect(from).toBe('2026-05-07'); // May 10 - 3 days
    expect(to).toBe('2026-05-20');   // May 16 + 4 (week wrap +7 +3 buffer = +10 from weekStart)
  });

  it('returns month range covering surrounding weeks plus buffer', () => {
    const { from, to } = rangeFor('month', new Date(2026, 4, 13)); // May
    expect(from).toBe('2026-04-23'); // first week of May starts Apr 26 - 3 buffer
    expect(to).toBe('2026-06-10');   // last day May 31 + 7 + 3
  });

  it('exposes BUFFER_DAYS = 3', () => {
    expect(BUFFER_DAYS).toBe(3);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/calendarRange.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the helper**

Read the inline function at `frontend/src/routes/kids.$id.calendar.tsx:15-32` first. Then create `frontend/src/lib/calendarRange.ts`:

```ts
import { addDays, endOfMonth, format, startOfMonth, startOfWeek } from 'date-fns';
import type { View } from 'react-big-calendar';

export const BUFFER_DAYS = 3;

export function rangeFor(view: View, cursor: Date): { from: string; to: string } {
  if (view === 'month') {
    const monthStart = startOfMonth(cursor);
    const monthEnd = endOfMonth(cursor);
    const weekStart = startOfWeek(monthStart, { weekStartsOn: 0 });
    return {
      from: format(addDays(weekStart, -BUFFER_DAYS), 'yyyy-MM-dd'),
      to: format(addDays(monthEnd, 7 + BUFFER_DAYS), 'yyyy-MM-dd'),
    };
  }
  const weekStart = startOfWeek(cursor, { weekStartsOn: 0 });
  return {
    from: format(addDays(weekStart, -BUFFER_DAYS), 'yyyy-MM-dd'),
    to: format(addDays(weekStart, 7 + BUFFER_DAYS), 'yyyy-MM-dd'),
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/calendarRange.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Refactor the per-kid route to use the helper**

Edit `frontend/src/routes/kids.$id.calendar.tsx`:
- Remove imports `addDays, startOfWeek, startOfMonth, endOfMonth, format` from `date-fns` if no longer used elsewhere in the file (keep ones still used).
- Remove the local `BUFFER_DAYS` constant and `rangeFor` function (lines 15-32).
- Add `import { rangeFor } from '@/lib/calendarRange';` near the top.

- [ ] **Step 6: Run all calendar-related tests + typecheck**

Run:
```bash
cd frontend && npx vitest run src/routes/-kids.index.test.tsx src/lib/calendarRange.test.ts && npm run typecheck
```
Expected: all tests pass, typecheck clean. (Per-kid calendar route has no dedicated test file; behavior is equivalent.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/calendarRange.ts frontend/src/lib/calendarRange.test.ts frontend/src/routes/kids.\$id.calendar.tsx
git commit -m "phase 8-1: lift calendar rangeFor to shared lib"
```

---

## Task 2: Color palette

**Files:**
- Create: `frontend/src/lib/calendarColors.ts`
- Create: `frontend/src/lib/calendarColors.test.ts`

Stable per-kid colors, indexed by `kid.id`. 8-color palette chosen for color-blind contrast (no red+green pair).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/calendarColors.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { CALENDAR_KID_COLORS, colorForKid } from './calendarColors';

describe('colorForKid', () => {
  it('returns same color for same kid id', () => {
    expect(colorForKid(1)).toEqual(colorForKid(1));
  });

  it('returns different colors for different ids within palette length', () => {
    const colors = new Set<string>();
    for (let i = 0; i < CALENDAR_KID_COLORS.length; i++) {
      colors.add(colorForKid(i + 1).bg);
    }
    expect(colors.size).toBe(CALENDAR_KID_COLORS.length);
  });

  it('wraps around palette length', () => {
    const len = CALENDAR_KID_COLORS.length;
    expect(colorForKid(1)).toEqual(colorForKid(1 + len));
  });

  it('palette has at least 8 colors', () => {
    expect(CALENDAR_KID_COLORS.length).toBeGreaterThanOrEqual(8);
  });

  it('each entry has bg and text class strings', () => {
    for (const c of CALENDAR_KID_COLORS) {
      expect(c.bg).toMatch(/^bg-/);
      expect(c.text).toMatch(/^text-/);
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/calendarColors.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the palette**

Create `frontend/src/lib/calendarColors.ts`:

```ts
export interface KidColor {
  /** Tailwind background class for the event chip */
  bg: string;
  /** Tailwind text class chosen for AA contrast against bg */
  text: string;
  /** Hex value for inline style fallback (used in eventStyle prop) */
  hex: string;
}

// Color-blind-aware palette: avoids relying on red/green pairs.
// Order tuned so adjacent kid ids get visually distinct colors.
export const CALENDAR_KID_COLORS: readonly KidColor[] = [
  { bg: 'bg-blue-500',    text: 'text-white', hex: '#3b82f6' },
  { bg: 'bg-amber-500',   text: 'text-white', hex: '#f59e0b' },
  { bg: 'bg-emerald-500', text: 'text-white', hex: '#10b981' },
  { bg: 'bg-violet-500',  text: 'text-white', hex: '#8b5cf6' },
  { bg: 'bg-rose-500',    text: 'text-white', hex: '#f43f5e' },
  { bg: 'bg-teal-500',    text: 'text-white', hex: '#14b8a6' },
  { bg: 'bg-orange-500',  text: 'text-white', hex: '#f97316' },
  { bg: 'bg-cyan-600',    text: 'text-white', hex: '#0891b2' },
] as const;

/** Stable color assignment by kid id. Wraps around palette length. */
export function colorForKid(kidId: number): KidColor {
  const idx = ((kidId - 1) % CALENDAR_KID_COLORS.length + CALENDAR_KID_COLORS.length) % CALENDAR_KID_COLORS.length;
  return CALENDAR_KID_COLORS[idx]!;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/calendarColors.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/calendarColors.ts frontend/src/lib/calendarColors.test.ts
git commit -m "phase 8-1: add per-kid color palette"
```

---

## Task 3: Type additions

**Files:**
- Modify: `frontend/src/lib/types.ts`

Add `CombinedCalendarEvent` (extends `CalendarEvent` with `kid_id`) and `CombinedCalendarFilterState` (URL state shape). No behavior change.

- [ ] **Step 1: Read existing types**

Read `frontend/src/lib/types.ts` to confirm `CalendarEvent`, `KidCalendarResponse`, and `CalendarEventKind` shapes (lines ~288-317).

- [ ] **Step 2: Add the types**

Append at the end of `frontend/src/lib/types.ts`:

```ts
// Phase 8-1 combined calendar
export interface CombinedCalendarEvent extends CalendarEvent {
  /** Injected at merge time; not present in API response. */
  kid_id: number;
}

export interface CombinedCalendarFilterState {
  /** Selected kid ids; null/undefined means "all active". */
  kidIds: number[] | null;
  /** Selected event types; null means "all". */
  types: CalendarEventKind[] | null;
  /** Pull match events into the calendar (defaults false). */
  includeMatches: boolean;
}
```

- [ ] **Step 3: Verify typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "phase 8-1: add combined-calendar types"
```

---

## Task 4: Merge function

**Files:**
- Create: `frontend/src/lib/combinedCalendar.ts`
- Create: `frontend/src/lib/combinedCalendar.test.ts`

Pure function. Takes per-kid responses + kid lookup + filter state; returns flat sorted `CombinedCalendarEvent[]` with `kid_id` injected and titles prefixed.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/combinedCalendar.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { mergeKidCalendars } from './combinedCalendar';
import type { KidBrief, KidCalendarResponse, CalendarEvent } from './types';

const sam: KidBrief = { id: 1, name: 'Sam', dob: '2019-05-01', interests: [], active: true };
const lila: KidBrief = { id: 2, name: 'Lila', dob: '2017-08-12', interests: [], active: true };

function ev(date: string, title: string, kind: CalendarEvent['kind'] = 'enrollment', time_start: string | null = '09:00:00'): CalendarEvent {
  return {
    id: `${kind}:${title}:${date}`,
    kind,
    date,
    time_start,
    time_end: time_start ? '10:00:00' : null,
    all_day: time_start === null,
    title,
  };
}

const samResp = (events: CalendarEvent[]): KidCalendarResponse => ({
  kid_id: 1, from: '2026-05-10', to: '2026-05-16', events,
});
const lilaResp = (events: CalendarEvent[]): KidCalendarResponse => ({
  kid_id: 2, from: '2026-05-10', to: '2026-05-16', events,
});

describe('mergeKidCalendars', () => {
  it('flattens responses and prefixes title with kid name', () => {
    const out = mergeKidCalendars(
      [samResp([ev('2026-05-13', 'T-Ball')]), lilaResp([ev('2026-05-13', 'Soccer')])],
      new Map([[1, sam], [2, lila]]),
      { kidIds: null, types: null, includeMatches: true },
    );
    expect(out).toHaveLength(2);
    expect(out.map(e => e.title).sort()).toEqual(['Lila: Soccer', 'Sam: T-Ball']);
    expect(out.every(e => typeof e.kid_id === 'number')).toBe(true);
  });

  it('sorts by (date, time_start)', () => {
    const out = mergeKidCalendars(
      [
        samResp([ev('2026-05-14', 'B', 'enrollment', '08:00:00'), ev('2026-05-13', 'A', 'enrollment', '09:00:00')]),
        lilaResp([ev('2026-05-13', 'C', 'enrollment', '08:00:00')]),
      ],
      new Map([[1, sam], [2, lila]]),
      { kidIds: null, types: null, includeMatches: true },
    );
    expect(out.map(e => e.title)).toEqual(['Lila: C', 'Sam: A', 'Sam: B']);
  });

  it('filters by kidIds', () => {
    const out = mergeKidCalendars(
      [samResp([ev('2026-05-13', 'A')]), lilaResp([ev('2026-05-13', 'B')])],
      new Map([[1, sam], [2, lila]]),
      { kidIds: [1], types: null, includeMatches: true },
    );
    expect(out).toHaveLength(1);
    expect(out[0]!.title).toBe('Sam: A');
  });

  it('filters by types', () => {
    const out = mergeKidCalendars(
      [samResp([ev('2026-05-13', 'A', 'enrollment'), ev('2026-05-13', 'B', 'unavailability', null)])],
      new Map([[1, sam]]),
      { kidIds: null, types: ['unavailability'], includeMatches: true },
    );
    expect(out).toHaveLength(1);
    expect(out[0]!.title).toBe('Sam: B');
  });

  it('drops match events when includeMatches=false', () => {
    const out = mergeKidCalendars(
      [samResp([ev('2026-05-13', 'A', 'enrollment'), ev('2026-05-13', 'M', 'match')])],
      new Map([[1, sam]]),
      { kidIds: null, types: null, includeMatches: false },
    );
    expect(out).toHaveLength(1);
    expect(out[0]!.title).toBe('Sam: A');
  });

  it('returns empty for empty responses', () => {
    const out = mergeKidCalendars([], new Map(), { kidIds: null, types: null, includeMatches: true });
    expect(out).toEqual([]);
  });

  it('skips events for kids missing from kidsById', () => {
    const out = mergeKidCalendars(
      [{ kid_id: 99, from: 'x', to: 'y', events: [ev('2026-05-13', 'orphan')] }],
      new Map([[1, sam]]),
      { kidIds: null, types: null, includeMatches: true },
    );
    expect(out).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/combinedCalendar.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the merge function**

Create `frontend/src/lib/combinedCalendar.ts`:

```ts
import type {
  CalendarEvent,
  CombinedCalendarEvent,
  CombinedCalendarFilterState,
  KidBrief,
  KidCalendarResponse,
} from './types';

function timeKey(e: CalendarEvent): string {
  return `${e.date}T${e.time_start ?? '00:00:00'}`;
}

export function mergeKidCalendars(
  responses: readonly KidCalendarResponse[],
  kidsById: ReadonlyMap<number, KidBrief>,
  filters: CombinedCalendarFilterState,
): CombinedCalendarEvent[] {
  const out: CombinedCalendarEvent[] = [];
  for (const resp of responses) {
    const kid = kidsById.get(resp.kid_id);
    if (!kid) continue; // orphan response — kid not in lookup
    if (filters.kidIds !== null && !filters.kidIds.includes(kid.id)) continue;
    for (const event of resp.events) {
      if (!filters.includeMatches && event.kind === 'match') continue;
      if (filters.types !== null && !filters.types.includes(event.kind)) continue;
      out.push({
        ...event,
        kid_id: kid.id,
        title: `${kid.name}: ${event.title}`,
      });
    }
  }
  out.sort((a, b) => {
    const ak = timeKey(a);
    const bk = timeKey(b);
    if (ak < bk) return -1;
    if (ak > bk) return 1;
    return 0;
  });
  return out;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/combinedCalendar.test.ts`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/combinedCalendar.ts frontend/src/lib/combinedCalendar.test.ts
git commit -m "phase 8-1: add mergeKidCalendars pure function"
```

---

## Task 5: `CalendarView` `eventStyle` prop

**Files:**
- Modify: `frontend/src/components/calendar/CalendarView.tsx`

Add an optional `eventStyle?(event): { className?: string; style?: React.CSSProperties }` prop. The existing kind-based className (e.g. `rbc-event-enrollment`) is preserved; the override's `className` is concatenated and `style` is shallow-merged on top.

Per-kid callers don't pass `eventStyle` and get unchanged behavior.

- [ ] **Step 1: Read the existing component**

Read `frontend/src/components/calendar/CalendarView.tsx`. Confirm `eventPropGetter` lives at lines 72-82 and returns `{ className }`.

- [ ] **Step 2: Add the prop and composition logic**

Edit `frontend/src/components/calendar/CalendarView.tsx`:

In the props interface, after `onSelectEvent`:

```ts
eventStyle?: (event: CalendarEvent) => {
  className?: string;
  style?: React.CSSProperties;
};
```

In the function signature destructure, add `eventStyle`.

In the existing `eventPropGetter`, replace the body so it composes:

```ts
const eventPropGetter = (event: RbcEvent) => {
  const ev = event.resource;
  const kindClass = `rbc-event-${ev.kind}`;
  const override = eventStyle?.(ev) ?? {};
  return {
    className: [kindClass, override.className].filter(Boolean).join(' '),
    style: override.style ?? {},
  };
};
```

(If the existing implementation differs, preserve its kind-class derivation — only add the `eventStyle` composition. Read the actual lines before editing.)

- [ ] **Step 3: Verify per-kid calendar still renders**

Run: `cd frontend && npm run typecheck && npx vitest run`
Expected: typecheck clean, all existing tests pass (this is purely additive).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/calendar/CalendarView.tsx
git commit -m "phase 8-1: add optional eventStyle prop to CalendarView"
```

---

## Task 6: Filters component

**Files:**
- Create: `frontend/src/components/calendar/CombinedCalendarFilters.tsx`
- Create: `frontend/src/components/calendar/CombinedCalendarFilters.test.tsx`

Decoupled component: takes `filters`, `kids`, `onChange`, `onClear` props. Doesn't read URL or context directly — easier to test, reusable. Color swatches next to kid names use `colorForKid`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/calendar/CombinedCalendarFilters.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CombinedCalendarFilters } from './CombinedCalendarFilters';
import type { KidBrief, CombinedCalendarFilterState } from '@/lib/types';

const sam: KidBrief = { id: 1, name: 'Sam', dob: '2019-05-01', interests: [], active: true };
const lila: KidBrief = { id: 2, name: 'Lila', dob: '2017-08-12', interests: [], active: true };
const allOn: CombinedCalendarFilterState = { kidIds: null, types: null, includeMatches: false };

describe('CombinedCalendarFilters', () => {
  it('renders one checkbox per kid, all checked when kidIds=null', () => {
    render(<CombinedCalendarFilters kids={[sam, lila]} filters={allOn} onChange={() => {}} onClear={() => {}} />);
    expect(screen.getByLabelText('Sam')).toBeChecked();
    expect(screen.getByLabelText('Lila')).toBeChecked();
  });

  it('renders type checkboxes — all checked when types=null', () => {
    render(<CombinedCalendarFilters kids={[sam]} filters={allOn} onChange={() => {}} onClear={() => {}} />);
    expect(screen.getByLabelText(/Enrollment/i)).toBeChecked();
    expect(screen.getByLabelText(/Unavailability/i)).toBeChecked();
    expect(screen.getByLabelText(/Match/i)).toBeChecked();
  });

  it('toggling a kid checkbox invokes onChange with that kid removed', async () => {
    const onChange = vi.fn();
    render(<CombinedCalendarFilters kids={[sam, lila]} filters={allOn} onChange={onChange} onClear={() => {}} />);
    await userEvent.click(screen.getByLabelText('Sam'));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ kidIds: [2] }));
  });

  it('hides Clear button when filters are at defaults', () => {
    render(<CombinedCalendarFilters kids={[sam]} filters={allOn} onChange={() => {}} onClear={() => {}} />);
    expect(screen.queryByRole('button', { name: /Clear/i })).toBeNull();
  });

  it('shows Clear button when any filter is set', () => {
    render(
      <CombinedCalendarFilters
        kids={[sam]}
        filters={{ kidIds: [1], types: null, includeMatches: false }}
        onChange={() => {}}
        onClear={() => {}}
      />,
    );
    expect(screen.getByRole('button', { name: /Clear/i })).toBeInTheDocument();
  });

  it('clicking Clear invokes onClear', async () => {
    const onClear = vi.fn();
    render(
      <CombinedCalendarFilters
        kids={[sam]}
        filters={{ kidIds: [1], types: null, includeMatches: false }}
        onChange={() => {}}
        onClear={onClear}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /Clear/i }));
    expect(onClear).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/calendar/CombinedCalendarFilters.test.tsx`
Expected: FAIL — component does not exist.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/calendar/CombinedCalendarFilters.tsx`:

```tsx
import type { CombinedCalendarFilterState, KidBrief, CalendarEventKind } from '@/lib/types';
import { colorForKid } from '@/lib/calendarColors';

const ALL_TYPES: { kind: CalendarEventKind; label: string }[] = [
  { kind: 'enrollment', label: 'Enrollment' },
  { kind: 'unavailability', label: 'Unavailability' },
  { kind: 'match', label: 'Match' },
];

function isAtDefaults(f: CombinedCalendarFilterState): boolean {
  return f.kidIds === null && f.types === null && f.includeMatches === false;
}

interface Props {
  kids: readonly KidBrief[];
  filters: CombinedCalendarFilterState;
  onChange: (next: CombinedCalendarFilterState) => void;
  onClear: () => void;
}

export function CombinedCalendarFilters({ kids, filters, onChange, onClear }: Props) {
  const activeKids = kids.filter((k) => k.active);
  const selectedKidIds = filters.kidIds ?? activeKids.map((k) => k.id);
  const selectedTypes: CalendarEventKind[] = filters.types ?? ALL_TYPES.map((t) => t.kind);

  const toggleKid = (id: number) => {
    const next = selectedKidIds.includes(id)
      ? selectedKidIds.filter((k) => k !== id)
      : [...selectedKidIds, id].sort((a, b) => a - b);
    const allSelected = next.length === activeKids.length && activeKids.every((k) => next.includes(k.id));
    onChange({ ...filters, kidIds: allSelected ? null : next });
  };

  const toggleType = (kind: CalendarEventKind) => {
    const next = selectedTypes.includes(kind)
      ? selectedTypes.filter((t) => t !== kind)
      : [...selectedTypes, kind];
    const allSelected = ALL_TYPES.every((t) => next.includes(t.kind));
    onChange({ ...filters, types: allSelected ? null : next });
  };

  return (
    <div className="flex flex-wrap items-center gap-4 text-sm">
      <div className="flex flex-wrap gap-3" aria-label="Kid filters">
        {activeKids.map((k) => {
          const color = colorForKid(k.id);
          return (
            <label key={k.id} className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={selectedKidIds.includes(k.id)}
                onChange={() => toggleKid(k.id)}
                aria-label={k.name}
              />
              <span className={`inline-block h-3 w-3 rounded-sm ${color.bg}`} aria-hidden />
              <span>{k.name}</span>
            </label>
          );
        })}
      </div>
      <div className="flex flex-wrap gap-3" aria-label="Type filters">
        {ALL_TYPES.map((t) => (
          <label key={t.kind} className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={selectedTypes.includes(t.kind)}
              onChange={() => toggleType(t.kind)}
              aria-label={t.label}
            />
            <span>{t.label}</span>
          </label>
        ))}
      </div>
      <label className="flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={filters.includeMatches}
          onChange={(e) => onChange({ ...filters, includeMatches: e.target.checked })}
        />
        <span>Include matches</span>
      </label>
      {!isAtDefaults(filters) && (
        <button
          type="button"
          onClick={onClear}
          className="text-xs text-muted-foreground hover:text-foreground underline"
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/calendar/CombinedCalendarFilters.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/calendar/CombinedCalendarFilters.tsx frontend/src/components/calendar/CombinedCalendarFilters.test.tsx
git commit -m "phase 8-1: add CombinedCalendarFilters component"
```

---

## Task 7: Combined calendar route

**Files:**
- Create: `frontend/src/routes/calendar.tsx`
- Create: `frontend/src/routes/-calendar.test.tsx`

Wires everything together. Uses `useQueries` for parallel per-kid fetches. URL search params drive view/date/kids/types/includeMatches. Decoupled inner component takes `searchParams` prop for testability.

- [ ] **Step 1: Read the alerts route as the URL-state reference pattern**

Read `frontend/src/routes/alerts.tsx` and `frontend/src/routes/-alerts.test.tsx` to confirm the **decoupled-component pattern**:
- The route exports `CalendarPage({ searchParams })` (the testable inner component) AND `CalendarPageRoute()` (the file-route wrapper that calls `Route.useSearch()` and passes it down).
- Tests mock heavy children + `@tanstack/react-router`'s `Link` and `useNavigate`, then render `<CalendarPage searchParams={...} />` directly without a router.

- [ ] **Step 2: Write the failing route test**

Create `frontend/src/routes/-calendar.test.tsx` following the `-alerts.test.tsx` pattern:

```tsx
import { vi } from 'vitest';

interface MockCalendarViewProps {
  events: Array<{ title: string }>;
}
interface MockFiltersProps {
  filters: { kidIds: number[] | null };
  onChange: (next: { kidIds: number[] | null }) => void;
  onClear: () => void;
}

// Mock children before importing the page
vi.mock('@/components/calendar/CalendarView', () => ({
  CalendarView: ({ events }: MockCalendarViewProps) => (
    <div data-testid="calendar-view">
      {events.map((e, i) => (
        <div key={i}>{e.title}</div>
      ))}
    </div>
  ),
}));

vi.mock('@/components/calendar/CalendarEventPopover', () => ({
  CalendarEventPopover: () => null,
}));

vi.mock('@/components/calendar/CombinedCalendarFilters', () => ({
  CombinedCalendarFilters: ({ filters, onChange, onClear }: MockFiltersProps) => (
    <div data-testid="filters">
      <button onClick={() => onChange({ ...filters, kidIds: [1] })}>FilterKid1</button>
      <button onClick={onClear}>ClearFilters</button>
    </div>
  ),
}));

vi.mock('@tanstack/react-router', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-router')>(
    '@tanstack/react-router',
  );
  return {
    ...actual,
    Link: ({ to, children, ...props }: { to: string; children?: React.ReactNode }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
    useNavigate: () => vi.fn(),
  };
});

import { describe, it, expect, beforeAll, afterEach, afterAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { CalendarPage } from './calendar';

const sam = { id: 1, name: 'Sam', dob: '2019-05-01', interests: [], active: true };
const lila = { id: 2, name: 'Lila', dob: '2017-08-12', interests: [], active: true };

const server = setupServer(
  http.get('/api/kids', () => HttpResponse.json([sam, lila])),
  http.get('/api/kids/1/calendar', () =>
    HttpResponse.json({
      kid_id: 1,
      from: '2026-05-10',
      to: '2026-05-16',
      events: [
        {
          id: 'enrollment:1:2026-05-13',
          kind: 'enrollment',
          date: '2026-05-13',
          time_start: '09:00:00',
          time_end: '10:00:00',
          all_day: false,
          title: 'T-Ball',
        },
      ],
    }),
  ),
  http.get('/api/kids/2/calendar', () =>
    HttpResponse.json({
      kid_id: 2,
      from: '2026-05-10',
      to: '2026-05-16',
      events: [
        {
          id: 'enrollment:2:2026-05-13',
          kind: 'enrollment',
          date: '2026-05-13',
          time_start: '14:00:00',
          time_end: '15:00:00',
          all_day: false,
          title: 'Soccer',
        },
      ],
    }),
  ),
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPage(searchParams: Record<string, string> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CalendarPage searchParams={searchParams} />
    </QueryClientProvider>,
  );
}

describe('CalendarPage', () => {
  it('renders both kids events with prefixed titles', async () => {
    renderPage();
    expect(await screen.findByText(/Sam: T-Ball/)).toBeInTheDocument();
    expect(await screen.findByText(/Lila: Soccer/)).toBeInTheDocument();
  });

  it('renders empty state when no active kids', async () => {
    server.use(http.get('/api/kids', () => HttpResponse.json([])));
    renderPage();
    expect(await screen.findByText(/Add a kid/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/routes/-calendar.test.tsx`
Expected: FAIL — route does not exist.

- [ ] **Step 4: Implement the route**

Create `frontend/src/routes/calendar.tsx`:

```tsx
import { useMemo, useState } from 'react';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import { useQueries } from '@tanstack/react-query';
import type { View } from 'react-big-calendar';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorBanner } from '@/components/common/ErrorBanner';
import { useKids } from '@/lib/queries';
import { api } from '@/lib/api';
import { CalendarView } from '@/components/calendar/CalendarView';
import { CalendarEventPopover } from '@/components/calendar/CalendarEventPopover';
import { CombinedCalendarFilters } from '@/components/calendar/CombinedCalendarFilters';
import { rangeFor } from '@/lib/calendarRange';
import { mergeKidCalendars } from '@/lib/combinedCalendar';
import { colorForKid } from '@/lib/calendarColors';
import type {
  CalendarEvent,
  CalendarEventKind,
  CombinedCalendarEvent,
  CombinedCalendarFilterState,
  KidCalendarResponse,
} from '@/lib/types';

type SearchParams = Record<string, string>;

export const Route = createFileRoute('/calendar')({
  component: CalendarPageRoute,
  validateSearch: (input: Record<string, unknown>): SearchParams => {
    const out: SearchParams = {};
    for (const [k, v] of Object.entries(input)) {
      if (typeof v === 'string') out[k] = v;
    }
    return out;
  },
});

function parseFilters(sp: SearchParams): CombinedCalendarFilterState {
  const kidIds = sp.kids
    ? sp.kids
        .split(',')
        .map((s) => Number(s))
        .filter((n) => Number.isFinite(n) && n > 0)
    : null;
  const types = sp.types
    ? (sp.types.split(',') as CalendarEventKind[]).filter((t): t is CalendarEventKind =>
        ['enrollment', 'unavailability', 'match'].includes(t),
      )
    : null;
  return {
    kidIds: kidIds && kidIds.length > 0 ? kidIds : null,
    types: types && types.length > 0 ? types : null,
    includeMatches: sp.include_matches === 'true',
  };
}

function filtersToParams(f: CombinedCalendarFilterState): SearchParams {
  const out: SearchParams = {};
  if (f.kidIds !== null) out.kids = f.kidIds.join(',');
  if (f.types !== null) out.types = f.types.join(',');
  if (f.includeMatches) out.include_matches = 'true';
  return out;
}

// Decoupled inner component — takes searchParams as a prop so tests
// can render it without router context. Phase 7-4 alerts pattern.
export function CalendarPage({ searchParams }: { searchParams: SearchParams }) {
  const navigate = useNavigate();
  const kids = useKids();

  const view: View = searchParams.view === 'month' ? 'month' : 'week';
  const cursor = useMemo(
    () => (searchParams.date ? new Date(`${searchParams.date}T00:00:00`) : new Date()),
    [searchParams.date],
  );
  const filters = useMemo(() => parseFilters(searchParams), [searchParams]);
  const { from, to } = useMemo(() => rangeFor(view, cursor), [view, cursor]);
  const activeKids = useMemo(() => kids.data?.filter((k) => k.active) ?? [], [kids.data]);

  const queries = useQueries({
    queries: activeKids.map((k) => ({
      queryKey: ['kid-calendar', k.id, from, to, filters.includeMatches],
      queryFn: () =>
        api.get<KidCalendarResponse>(
          `/api/kids/${k.id}/calendar?from=${from}&to=${to}${filters.includeMatches ? '&include_matches=true' : ''}`,
        ),
      enabled: kids.isSuccess,
    })),
  });

  const kidsById = useMemo(() => new Map(activeKids.map((k) => [k.id, k])), [activeKids]);
  const [selected, setSelected] = useState<CombinedCalendarEvent | null>(null);

  const updateSearch = (next: Partial<SearchParams>) => {
    const merged: SearchParams = { ...searchParams };
    for (const [k, v] of Object.entries(next)) {
      if (v === undefined) delete merged[k];
      else merged[k] = v;
    }
    navigate({ to: '/calendar', search: merged });
  };

  if (kids.isLoading) return <Skeleton className="h-32 w-full" />;
  if (kids.isError) {
    return <ErrorBanner message={(kids.error as Error).message} onRetry={() => kids.refetch()} />;
  }

  if (activeKids.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <p className="mb-3">Add a kid to see a combined calendar.</p>
        <Link to="/kids/new" className="underline">
          Add kid
        </Link>
      </div>
    );
  }

  const allLoaded = queries.every((q) => q.isSuccess);
  const failedKidNames = queries
    .map((q, i) => (q.isError ? activeKids[i]!.name : null))
    .filter((n): n is string => n !== null);

  if (!allLoaded && queries.some((q) => q.isLoading)) {
    return <Skeleton className="h-96 w-full" />;
  }

  const responses: KidCalendarResponse[] = queries
    .map((q) => q.data)
    .filter((r): r is KidCalendarResponse => r !== undefined);
  const events = mergeKidCalendars(responses, kidsById, filters);

  const visibleKidCount =
    filters.kidIds === null ? activeKids.length : filters.kidIds.length;
  if (visibleKidCount === 0) {
    return (
      <div>
        <h1 className="text-xl font-semibold mb-2">Combined calendar</h1>
        <CombinedCalendarFilters
          kids={activeKids}
          filters={filters}
          onChange={(next) => updateSearch(filtersToParams(next))}
          onClear={() => navigate({ to: '/calendar', search: { view: searchParams.view ?? '', date: searchParams.date ?? '' } as SearchParams })}
        />
        <p className="mt-8 text-center text-muted-foreground">No kids selected.</p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-xl font-semibold mb-2">Combined calendar</h1>
      {failedKidNames.length > 0 && (
        <ErrorBanner
          message={`Failed to load: ${failedKidNames.join(', ')}`}
          onRetry={() => queries.forEach((q) => q.isError && q.refetch())}
        />
      )}
      <div className="my-2">
        <CombinedCalendarFilters
          kids={activeKids}
          filters={filters}
          onChange={(next) => updateSearch(filtersToParams(next))}
          onClear={() => navigate({ to: '/calendar', search: {} as SearchParams })}
        />
      </div>
      <CalendarView
        events={events}
        view={view}
        onView={(v) => updateSearch({ view: v })}
        date={cursor}
        onNavigate={(d) => updateSearch({ date: d.toISOString().slice(0, 10) })}
        onSelectEvent={(e: CalendarEvent) => setSelected(e as CombinedCalendarEvent)}
        eventStyle={(e) => {
          const cev = e as CombinedCalendarEvent;
          const c = colorForKid(cev.kid_id);
          return { className: c.bg, style: { color: 'white' } };
        }}
      />
      <CalendarEventPopover
        event={selected}
        kidId={selected?.kid_id ?? 0}
        open={selected !== null}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}

// Thin wrapper used by the file-route. Reads search params from the
// router and forwards them to CalendarPage.
function CalendarPageRoute() {
  const search = Route.useSearch();
  return <CalendarPage searchParams={search} />;
}
```

**Verify before implementing:**
- `useKids()` returns `{ data, isLoading, isError, error, refetch, isSuccess }` — see `frontend/src/lib/queries.ts:42-46`. Confirm before using these property names.
- `KidBrief` (used as the kid type) has fields `{ id, name, dob, interests, active }` — see `frontend/src/lib/types.ts`.
- `<CalendarEventPopover>` props: `{ kidId: number; event: CalendarEvent | null; open: boolean; onClose }` — see `frontend/src/components/calendar/CalendarEventPopover.tsx:20-30`. Render unconditionally; toggle visibility with `open`.
- `<CalendarView>` prop names: read the per-kid call site at `frontend/src/routes/kids.$id.calendar.tsx` and copy that shape; the new `eventStyle` prop is the only addition.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/routes/-calendar.test.tsx`
Expected: PASS (2 tests).

If it fails on prop-name mismatches with `<CalendarView>`, adjust to match the per-kid route's call. If `useKids()` doesn't expose `data`/`isLoading`/`isError`/`refetch`, check `frontend/src/lib/queries.ts` for the actual hook signature.

- [ ] **Step 6: Run typecheck + full test suite + lint**

Run: `cd frontend && npm run typecheck && npm run lint && npm run test`
Expected: typecheck clean, lint clean, all tests pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/calendar.tsx frontend/src/routes/-calendar.test.tsx
git commit -m "phase 8-1: add /calendar combined view route"
```

---

## Task 8: TopBar link

**Files:**
- Modify: `frontend/src/components/layout/TopBar.tsx`
- Modify: `frontend/src/components/layout/TopBar.test.tsx`

Add a `Calendar` link with the `CalendarDays` icon between Kids and Offerings.

- [ ] **Step 1: Read the existing TopBar**

Read `frontend/src/components/layout/TopBar.tsx`. Note current order: YAS · KidSwitcher · Inbox · Kids · Offerings · Alerts · Sites · Settings.

- [ ] **Step 2: Update the test**

Edit `frontend/src/components/layout/TopBar.test.tsx`:

After the existing `Kids` link assertion, add:

```ts
expect(screen.getByRole('link', { name: 'Calendar' })).toHaveAttribute('href', '/calendar');
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/layout/TopBar.test.tsx`
Expected: FAIL — no `Calendar` link rendered.

- [ ] **Step 4: Add the link**

Edit `frontend/src/components/layout/TopBar.tsx`:

Update the lucide import to include `CalendarDays`. Insert this `Link` after the `Kids` link and before the `Offerings` link:

```tsx
<Link
  to="/calendar"
  className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
>
  <CalendarDays className="h-4 w-4" /> Calendar
</Link>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/layout/TopBar.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/layout/TopBar.tsx frontend/src/components/layout/TopBar.test.tsx
git commit -m "phase 8-1: add Calendar link to TopBar"
```

---

## Task 9: Final gates, smoke, roadmap, push, PR

**Files:**
- Modify: `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md`

- [ ] **Step 1: Run all gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run format:check && npm run test
cd .. && uv run pytest -q
```
Expected: all green. Frontend test count rises by ~15 (calendarRange 3 + colors 5 + combinedCalendar 7 + filters 6 + route 2 + topbar 1 - 1 if topbar test count was already 2).

- [ ] **Step 2: Manual smoke**

```bash
# In one terminal:
docker compose -f docker-compose.dev.yml up -d
# Or whatever local-dev workflow you use.
# Visit http://localhost:5173/calendar (or the configured dev URL)
```

Verify:
- TopBar shows Calendar between Kids and Offerings
- Calendar page renders one event per active kid in distinct colors
- Toggling a kid checkbox updates URL `?kids=...` and removes that kid's events
- Toggling event-type checkbox filters by kind
- Toggling Include matches reloads (or refetches) and includes match events
- Week ↔ Month toggle works; Date navigation persists in URL `?date=`
- Clear filters removes all `?kids` / `?types` / `?include_matches` from URL
- Empty state shows when no kids exist (manually delete kids via API or test with empty seed)

- [ ] **Step 3: Update roadmap**

Edit `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md`:

Find §5 master § 7 audit, line for page #3 ("Calendar (per-kid + combined)"). Change `⚠️ per-kid ✓; combined → Phase 8-1` to `✅ per-kid ✓; combined ✅ Phase 8-1 (2026-05-02)`.

Find §6 Phase 8 section. Mark Phase 8-1 as shipped. Add a row to §2 "What shipped" if maintained.

- [ ] **Step 4: Commit roadmap**

```bash
git add docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md
git commit -m "docs(roadmap): close phase 8-1 (combined calendar)"
```

- [ ] **Step 5: Push + PR**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git push -u origin phase-8-1-combined-calendar
gh pr create --title 'phase 8-1: combined multi-kid calendar' --body "$(cat <<'EOF'
## Summary

Closes roadmap §6 Phase 8-1 and master §7 page #3 (combined-calendar half).

New top-level `/calendar` route overlays all active kids' enrollments / unavailability / matches in one view, color-coded by kid. Frontend-only — reuses the existing per-kid `GET /api/kids/{id}/calendar` endpoint via `useQueries` parallel fan-out, with a pure merge step that injects `kid_id` and a `"{name}: {title}"` prefix.

- **Filters**: kid checkboxes (with color swatches), event-type checkboxes, Include-matches toggle. State in URL search params (`?view=`, `?date=`, `?kids=`, `?types=`, `?include_matches=`).
- **Reuse**: `<CalendarView>` (gained an optional `eventStyle` prop), `<CalendarEventPopover>` (passes resolved `kid_id`), range helper lifted from per-kid route into `lib/calendarRange.ts`.
- **Color palette**: 8-color palette indexed by `kid.id`, color-blind-aware (no red+green pair).
- **TopBar**: new `Calendar` link with `CalendarDays` icon between Kids and Offerings.

## Master §10 terminal criteria delta

None — Phase 8 is polish. Closes master §7 page #3.

## Test plan

- [x] uv run pytest -q (594 passing — no backend touch)
- [x] cd frontend && npm run typecheck / lint / format:check clean
- [x] cd frontend && npm run test (~290 passing, +~15)
- [x] Manual smoke: nav, filters, kid toggling, event-type toggling, week/month, date persistence, empty state
- [ ] CI passes
EOF
)"
```

---

## Coverage Summary

| What | Test |
|---|---|
| Range helper | `calendarRange.test.ts` (3 tests) |
| Color palette stability | `calendarColors.test.ts` (5 tests) |
| Merge function | `combinedCalendar.test.ts` (7 tests) |
| Filter component interactions | `CombinedCalendarFilters.test.tsx` (6 tests) |
| Route integration (data flow + empty state) | `-calendar.test.tsx` (2 tests) |
| TopBar nav | extended assertion in existing TopBar test |

Per-kid calendar gets covered indirectly by the range-helper test + existing manual usage. No new backend tests (no backend changes).

---

## Out of Scope

- Holiday/school-year visual integration (Phase 8-2)
- Watchlist on calendar (Phase 8-3)
- Drag-to-reschedule, ICS export (master §9 deferred)
- Backend combined-calendar endpoint
- Conflict highlighting
- Per-kid color persistence in DB
