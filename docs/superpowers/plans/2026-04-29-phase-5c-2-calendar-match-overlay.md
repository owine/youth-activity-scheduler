# Phase 5c-2 — Calendar Match Overlay + Click-to-Enroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the per-kid calendar with an opt-in match overlay (score ≥ 0.6, dashed-outline events) and a click-to-enroll affordance via the existing event popover.

**Architecture:** Backend extends `GET /api/kids/{id}/calendar` with one optional `include_matches` flag; when set, server merges high-score match occurrences into the response excluding offerings the kid has any non-`cancelled` enrollment for. Frontend learns about a new `kind="match"` event, renders it with a dashed outline, adds a "Show matches" toggle on the calendar route, and the popover gains an "Enroll" branch. One new mutation `useEnrollOffering` follows the canonical 5b-1b/5c-1 optimistic + rollback pattern.

**Tech Stack:** SQLAlchemy 2.x async, FastAPI, Pydantic v2, pytest-asyncio, React 19, TanStack Query 5, MSW, Vitest + RTL.

**Spec:** `docs/superpowers/specs/2026-04-29-phase-5c-2-calendar-match-overlay-design.md`

**Project conventions to maintain:**
- All deps already pinned to exact patch. No new deps in this slice.
- All commits signed via 1Password SSH agent. Set `SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"` before each `git commit` in fresh shells (subagents do NOT inherit it). Verify with `git cat-file commit HEAD | grep -q '^gpgsig '`.
- Branch already created: `phase-5c-2-calendar-match-overlay`. Do NOT commit to `main`.
- Backend gates: `uv run pytest -q --no-cov`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`.
- Frontend gates from `frontend/`: `npm run typecheck`, `npm run lint`, `npm run test`.
- Backend baseline: 561 tests. Frontend baseline: 42 tests (10 files).
- Hand-maintained types in `frontend/src/lib/types.ts` mirror Pydantic schemas; keep them in sync.
- Python 3.14 (PEP 758 — `except A, B:` is valid syntax, don't flag).

---

## File Structure

**Modify — backend:**
- `src/yas/web/routes/kid_calendar.py` — add `include_matches` query param + match merge logic + `_MATCH_THRESHOLD = 0.6` constant.
- `src/yas/web/routes/kid_calendar_schemas.py` — extend `CalendarEventOut.kind` Literal union with `"match"`; add `score: float | None` and `registration_url: str | None`.
- `tests/integration/test_api_kids_calendar.py` — append match-overlay tests.

**Modify — frontend:**
- `frontend/src/lib/types.ts` — extend `CalendarEventKind` and `CalendarEvent`.
- `frontend/src/lib/queries.ts` — extend `useKidCalendar` to accept `includeMatches`; cache key gains a 6th segment.
- `frontend/src/lib/mutations.ts` — add `useEnrollOffering` hook.
- `frontend/src/lib/mutations.test.tsx` — append `useEnrollOffering` tests.
- `frontend/src/components/calendar/CalendarView.tsx` — extend `eventPropGetter` with a third branch.
- `frontend/src/components/calendar/calendar-overrides.css` — add `.rbc-event-match` style.
- `frontend/src/components/calendar/CalendarView.test.tsx` — append a match-rendering test.
- `frontend/src/components/calendar/CalendarEventPopover.tsx` — add the `kind === 'match'` branch with Enroll button.
- `frontend/src/components/calendar/CalendarEventPopover.test.tsx` — append match-popover tests.
- `frontend/src/routes/kids.$id.calendar.tsx` — add `includeMatches` state + "Show matches" checkbox.
- `frontend/src/test/handlers.ts` — extend the calendar GET handler to honor `include_matches`; add `POST /api/enrollments` handler.

---

## Task 1 — Backend: extend calendar endpoint with `include_matches` (TDD)

**Files:**
- Modify: `src/yas/web/routes/kid_calendar_schemas.py`
- Modify: `src/yas/web/routes/kid_calendar.py`
- Modify: `tests/integration/test_api_kids_calendar.py`

End state: `GET /api/kids/{id}/calendar?include_matches=true` returns match occurrences. Backend baseline 561 → 567 (6 new tests).

- [ ] **Step 1: Extend the schema**

In `src/yas/web/routes/kid_calendar_schemas.py`:

```python
# Update the kind union
class CalendarEventOut(BaseModel):
    id: str
    kind: Literal["enrollment", "unavailability", "match"]   # add "match"
    # ...existing fields unchanged...
    # add at the bottom alongside the other optional fields:
    score: float | None = None
    registration_url: str | None = None
```

- [ ] **Step 2: Append failing tests to `tests/integration/test_api_kids_calendar.py`**

The file already has the `client` fixture, `_seed_kid_with_enrollment` helper, and imports. Add at the top of the imports block:

```python
from yas.db.models import Match
```

(`Match` is already exported from `yas.db.models`; verify if not already imported.)

Then append at the bottom of the file:

```python
async def _seed_match(engine, *, kid_id: int, offering_id: int, score: float) -> None:
    async with session_scope(engine) as s:
        s.add(
            Match(
                kid_id=kid_id,
                offering_id=offering_id,
                score=score,
                reasons={},
                computed_at=datetime.now(UTC),
            )
        )


@pytest.mark.asyncio
async def test_match_overlay_flag_off_returns_no_match_events(client):
    """Default include_matches=false: behavior unchanged from 5c-1."""
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    # Seed a 2nd offering the kid is matched but NOT enrolled in.
    async with session_scope(engine) as s:
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                days_of_week=["wed"],
                time_start=time(17, 0),
                time_end=time(18, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.85)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    assert r.status_code == 200
    body = r.json()
    assert all(e["kind"] != "match" for e in body["events"])


@pytest.mark.asyncio
async def test_match_overlay_returns_high_score_matches(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    async with session_scope(engine) as s:
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                days_of_week=["wed"],
                time_start=time(17, 0),
                time_end=time(18, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
                registration_url="https://example.com/register/soccer",
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.85)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    matches = [e for e in body["events"] if e["kind"] == "match"]
    assert len(matches) == 1
    m = matches[0]
    assert m["offering_id"] == 2
    assert m["score"] == 0.85
    assert m["registration_url"] == "https://example.com/register/soccer"
    assert m["title"] == "Soccer"
    assert m["date"] == "2026-04-29"  # the Wednesday in the range
    assert m["id"] == "match:2:2026-04-29"


@pytest.mark.asyncio
async def test_match_overlay_score_threshold_boundary(client):
    """Threshold is >=0.6: 0.59 excluded, 0.60 included, 0.61 included."""
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    cases = [(2, 0.59), (3, 0.60), (4, 0.61)]
    async with session_scope(engine) as s:
        for off_id, _ in cases:
            s.add(
                Offering(
                    id=off_id,
                    site_id=1,
                    page_id=1,
                    name=f"Off-{off_id}",
                    normalized_name=f"off-{off_id}",
                    days_of_week=["wed"],
                    time_start=time(17, 0),
                    time_end=time(18, 0),
                    start_date=date(2026, 4, 1),
                    end_date=date(2026, 6, 30),
                    status=OfferingStatus.active.value,
                )
            )
    for off_id, score in cases:
        await _seed_match(engine, kid_id=1, offering_id=off_id, score=score)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    match_offering_ids = {e["offering_id"] for e in body["events"] if e["kind"] == "match"}
    assert match_offering_ids == {3, 4}


@pytest.mark.asyncio
async def test_match_overlay_excludes_already_enrolled(client):
    """An offering the kid is enrolled in must not appear as a match."""
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    await _seed_match(engine, kid_id=1, offering_id=1, score=0.95)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    assert all(e["kind"] != "match" for e in body["events"])


@pytest.mark.asyncio
async def test_match_overlay_excludes_interested_and_waitlisted(client):
    """Status=interested or status=waitlisted excludes the match overlay too."""
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    async with session_scope(engine) as s:
        for off_id in (2, 3):
            s.add(
                Offering(
                    id=off_id,
                    site_id=1,
                    page_id=1,
                    name=f"Off-{off_id}",
                    normalized_name=f"off-{off_id}",
                    days_of_week=["wed"],
                    time_start=time(17, 0),
                    time_end=time(18, 0),
                    start_date=date(2026, 4, 1),
                    end_date=date(2026, 6, 30),
                    status=OfferingStatus.active.value,
                )
            )
        await s.flush()
        s.add(
            Enrollment(
                id=20, kid_id=1, offering_id=2,
                status=EnrollmentStatus.interested.value,
            )
        )
        s.add(
            Enrollment(
                id=21, kid_id=1, offering_id=3,
                status=EnrollmentStatus.waitlisted.value,
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.9)
    await _seed_match(engine, kid_id=1, offering_id=3, score=0.9)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    assert all(e["kind"] != "match" for e in body["events"])


@pytest.mark.asyncio
async def test_match_overlay_includes_offerings_with_only_cancelled_enrollment(client):
    """A cancelled enrollment doesn't suppress the match overlay."""
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    async with session_scope(engine) as s:
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                days_of_week=["wed"],
                time_start=time(17, 0),
                time_end=time(18, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
            )
        )
        await s.flush()
        s.add(
            Enrollment(
                id=22, kid_id=1, offering_id=2,
                status=EnrollmentStatus.cancelled.value,
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.85)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    matches = [e for e in body["events"] if e["kind"] == "match"]
    assert len(matches) == 1
    assert matches[0]["offering_id"] == 2
```

- [ ] **Step 3: Run tests; confirm all 6 FAIL**

```bash
uv run pytest tests/integration/test_api_kids_calendar.py -q --no-cov -k "match_overlay"
```

Expected: 6 failed (route ignores the new flag → no match events ever return).

- [ ] **Step 4: Extend the route handler**

In `src/yas/web/routes/kid_calendar.py`:

a. Add to imports:
```python
from typing import Annotated, Literal  # already there

from yas.db.models import Enrollment, Kid, Match, Offering, UnavailabilityBlock  # add Match
```

(`EnrollmentStatus` is already imported by the 5c-1 handler — verify with `grep` before re-adding.)

b. Add the threshold constant near `_MAX_RANGE_DAYS`:
```python
_MAX_RANGE_DAYS = 90
_MATCH_THRESHOLD: float = 0.6
```

c. Update the route signature to accept the new flag:
```python
@router.get("/{kid_id}/calendar", response_model=KidCalendarOut, response_model_by_alias=True)
async def get_kid_calendar(
    request: Request,
    kid_id: int,
    from_: Annotated[date, Query(alias="from")],
    to: Annotated[date, Query()],
    include_matches: Annotated[bool, Query()] = False,
) -> KidCalendarOut:
```

d. Inside the route handler, after the existing block_rows loop (just before `events.sort(...)`), add the match-merge block:

```python
        # 3. Match overlay (opt-in).
        if include_matches:
            # Subquery: offering ids the kid is currently committed to (any non-cancelled enrollment).
            committed_offering_ids = (
                select(Enrollment.offering_id)
                .where(Enrollment.kid_id == kid_id)
                .where(Enrollment.status != EnrollmentStatus.cancelled.value)
            )
            match_rows = (
                await s.execute(
                    select(Match, Offering)
                    .join(Offering, Offering.id == Match.offering_id)
                    .where(Match.kid_id == kid_id)
                    .where(Match.score >= _MATCH_THRESHOLD)
                    .where(~Match.offering_id.in_(committed_offering_ids))
                )
            ).all()
            for match, offering in match_rows:
                for occ in expand_recurring(
                    days_of_week=list(offering.days_of_week or []),
                    time_start=offering.time_start,
                    time_end=offering.time_end,
                    date_start=offering.start_date,
                    date_end=offering.end_date,
                    range_from=from_,
                    range_to=to,
                ):
                    events.append(
                        CalendarEventOut(
                            id=f"match:{offering.id}:{occ.date.isoformat()}",
                            kind="match",
                            date=occ.date,
                            time_start=occ.time_start,
                            time_end=occ.time_end,
                            all_day=occ.all_day,
                            title=offering.name,
                            offering_id=offering.id,
                            location_id=offering.location_id,
                            score=match.score,
                            registration_url=offering.registration_url,
                        )
                    )
```

(Keep the existing sort step `events.sort(key=lambda e: (e.date, e.time_start or time.min))` after this block.)

- [ ] **Step 5: Re-run tests; confirm all 6 PASS**

```bash
uv run pytest tests/integration/test_api_kids_calendar.py -q --no-cov
```

Expected: 14 passed (8 from 5c-1 + 6 new).

- [ ] **Step 6: Run full backend gates**

```bash
uv run pytest -q --no-cov && uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: 567 passed (561 + 6); ruff/format/mypy clean.

- [ ] **Step 7: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git add src/yas/web/routes/kid_calendar.py src/yas/web/routes/kid_calendar_schemas.py tests/integration/test_api_kids_calendar.py
git commit -m "feat(api): GET /api/kids/{id}/calendar?include_matches=true

Server merges matches scored >=0.6 into the calendar response when
the flag is set. Excludes offerings the kid has any non-cancelled
enrollment for. Reuses expand_recurring for occurrence generation."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 2 — Frontend types + extended `useKidCalendar` query

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/queries.ts`
- Modify: `frontend/src/test/handlers.ts`

End state: `CalendarEvent` has the new `kind="match"` plus `score`/`registration_url`. `useKidCalendar` accepts `includeMatches`. MSW handler honors the flag. No new tests yet — that comes in subsequent tasks.

- [ ] **Step 1: Extend types**

In `frontend/src/lib/types.ts`:

```ts
// Update the union:
export type CalendarEventKind = 'enrollment' | 'unavailability' | 'match';   // add match

// Update the interface — append two fields after the existing optionals:
export interface CalendarEvent {
  // ...existing fields unchanged...
  // match-only:
  score?: number | null;
  registration_url?: string | null;
}
```

- [ ] **Step 2: Extend `useKidCalendar`**

In `frontend/src/lib/queries.ts`, replace the existing `useKidCalendar`:

```ts
export function useKidCalendar({
  kidId,
  from,
  to,
  includeMatches = false,
}: {
  kidId: number;
  from: string;
  to: string;
  includeMatches?: boolean;
}) {
  return useQuery({
    queryKey: ['kids', kidId, 'calendar', from, to, includeMatches ? 'with-matches' : 'no-matches'],
    queryFn: () =>
      api.get<KidCalendarResponse>(
        `/api/kids/${kidId}/calendar?from=${from}&to=${to}${includeMatches ? '&include_matches=true' : ''}`,
      ),
    enabled: Number.isFinite(kidId) && !!from && !!to,
  });
}
```

- [ ] **Step 3: Extend MSW calendar handler + add enrollments handler**

In `frontend/src/test/handlers.ts`, update the existing `GET /api/kids/:id/calendar` handler:

```ts
http.get('/api/kids/:id/calendar', ({ params, request }) => {
  const url = new URL(request.url);
  const includeMatches = url.searchParams.get('include_matches') === 'true';
  const events = includeMatches
    ? [
        {
          id: 'match:99:2026-04-29',
          kind: 'match',
          date: '2026-04-29',
          time_start: '17:00:00',
          time_end: '18:00:00',
          all_day: false,
          title: 'Soccer',
          offering_id: 99,
          score: 0.85,
          registration_url: 'https://example.com/soccer',
        },
      ]
    : [];
  return HttpResponse.json({
    kid_id: Number(params.id),
    from: url.searchParams.get('from'),
    to: url.searchParams.get('to'),
    events,
  });
}),
```

And append a new handler for enrollments creation:

```ts
http.post('/api/enrollments', async ({ request }) => {
  const body = (await request.json()) as { kid_id: number; offering_id: number; status: string };
  return HttpResponse.json({
    id: 999,
    kid_id: body.kid_id,
    offering_id: body.offering_id,
    status: body.status,
    enrolled_at: '2026-04-29T12:00:00Z',
    notes: null,
    created_at: '2026-04-29T12:00:00Z',
  }, { status: 201 });
}),
```

- [ ] **Step 4: Run frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: typecheck clean, lint clean, 42 existing tests still pass.

- [ ] **Step 5: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/lib/types.ts frontend/src/lib/queries.ts frontend/src/test/handlers.ts
git commit -m "feat(frontend): types + useKidCalendar(includeMatches) + MSW handlers

Mirrors the backend extension. Cache key gains a 'with-matches'/'no-matches'
discriminator at index 5 so the two states cache independently."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 3 — `useEnrollOffering` mutation hook (TDD)

**Files:**
- Modify: `frontend/src/lib/mutations.ts`
- Modify: `frontend/src/lib/mutations.test.tsx`

End state: `useEnrollOffering` follows the canonical 5b-1b/5c-1 pattern. 3 new tests pass.

- [ ] **Step 1: Append failing tests**

Append to `frontend/src/lib/mutations.test.tsx`. The file already imports `KidCalendarResponse`, `seedCal`, `makeWrapper`, `server`, `http`, `HttpResponse`. Add to the existing imports from `./mutations`:

```tsx
import {
  useCancelEnrollment,
  useDeleteUnavailability,
  useEnrollOffering,   // add
} from './mutations';
```

Then append at the bottom:

```tsx
describe('useEnrollOffering', () => {
  it('removes match events for the offering across all calendar variants', async () => {
    const qc = new QueryClient();
    const matchEvent = {
      id: 'match:7:2026-04-29',
      kind: 'match' as const,
      date: '2026-04-29',
      time_start: '16:00:00',
      time_end: '17:00:00',
      all_day: false,
      title: 'T-Ball',
      offering_id: 7,
      score: 0.85,
    };
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'with-matches'],
      seedCal([matchEvent]),
    );
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'no-matches'],
      seedCal([]),
    );

    const { result } = renderHook(() => useEnrollOffering(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, offeringId: 7 });
    });

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'with-matches',
    ]);
    expect(after?.events).toEqual([]);
  });

  it('does not crash on a no-matches variant that has no match events', async () => {
    const qc = new QueryClient();
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'no-matches'],
      seedCal([]),
    );

    const { result } = renderHook(() => useEnrollOffering(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current.mutateAsync({ kidId: 1, offeringId: 7 });
    });

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'no-matches',
    ]);
    expect(after?.events).toEqual([]);
  });

  it('rolls back on server error', async () => {
    server.use(
      http.post('/api/enrollments', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const matchEvent = {
      id: 'match:7:2026-04-29',
      kind: 'match' as const,
      date: '2026-04-29',
      time_start: '16:00:00',
      time_end: '17:00:00',
      all_day: false,
      title: 'T-Ball',
      offering_id: 7,
      score: 0.85,
    };
    qc.setQueryData<KidCalendarResponse>(
      ['kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'with-matches'],
      seedCal([matchEvent]),
    );

    const { result } = renderHook(() => useEnrollOffering(), { wrapper: makeWrapper(qc) });
    await act(async () => {
      await result.current
        .mutateAsync({ kidId: 1, offeringId: 7 })
        .catch(() => {});
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const after = qc.getQueryData<KidCalendarResponse>([
      'kids', 1, 'calendar', '2026-04-27', '2026-05-04', 'with-matches',
    ]);
    expect(after?.events).toHaveLength(1);
    expect(after?.events[0]!.kind).toBe('match');
  });
});
```

- [ ] **Step 2: Run; confirm all 3 FAIL** (hook not exported):

```
cd frontend && npm run test -- mutations
```

- [ ] **Step 3: Implement `useEnrollOffering`**

Append to `frontend/src/lib/mutations.ts`:

```ts
interface EnrollOfferingInput {
  kidId: number;
  offeringId: number;
}

export function useEnrollOffering() {
  const qc = useQueryClient();
  type Ctx = {
    snapshots: ReadonlyArray<readonly [QueryKey, KidCalendarResponse | undefined]>;
  };
  return useMutation<unknown, Error, EnrollOfferingInput, Ctx>({
    mutationFn: ({ kidId, offeringId }) =>
      api.post('/api/enrollments', {
        kid_id: kidId,
        offering_id: offeringId,
        status: 'enrolled',
      }),

    onMutate: async ({ kidId, offeringId }) => {
      await qc.cancelQueries({ queryKey: ['kids', kidId, 'calendar'] });
      const snapshots = qc.getQueriesData<KidCalendarResponse>({
        queryKey: ['kids', kidId, 'calendar'],
      });

      for (const [key, data] of snapshots) {
        if (!data) continue;
        const filtered = data.events.filter(
          (e) => !(e.kind === 'match' && e.offering_id === offeringId),
        );
        qc.setQueryData<KidCalendarResponse>(key, { ...data, events: filtered });
      }
      return { snapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: async (_data, _err, { kidId }) => {
      await qc.invalidateQueries({ queryKey: ['kids', kidId, 'calendar'] });
    },
  });
}
```

- [ ] **Step 4: Re-run; confirm 3 PASS**

```
cd frontend && npm run test -- mutations
```

Expected: 11 passed (8 existing + 3 new).

- [ ] **Step 5: Frontend gates**

```
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 45 passed; typecheck and lint clean.

- [ ] **Step 6: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/lib/mutations.ts frontend/src/lib/mutations.test.tsx
git commit -m "feat(frontend): useEnrollOffering with optimistic match removal

Follows the canonical 5b-1b/5c-1 pattern: cancelQueries + snapshot +
optimistic setQueryData + onError rollback + awaited onSettled
invalidate. Removes match events for the target offering optimistically;
new enrollment + linked block come from the server invalidate."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 4 — Match event styling in `CalendarView` (TDD)

**Files:**
- Modify: `frontend/src/components/calendar/CalendarView.tsx`
- Modify: `frontend/src/components/calendar/calendar-overrides.css`
- Modify: `frontend/src/components/calendar/CalendarView.test.tsx`

End state: Match events render with `rbc-event-match` class and a dashed-outline style. 1 new test passes.

- [ ] **Step 1: Append failing test**

Append to `frontend/src/components/calendar/CalendarView.test.tsx`:

```tsx
it('renders match events with the rbc-event-match class', () => {
  const matchEvents: CalendarEvent[] = [
    {
      id: 'match:7:2026-04-29',
      kind: 'match',
      date: '2026-04-29',
      time_start: '17:00:00',
      time_end: '18:00:00',
      all_day: false,
      title: 'Soccer',
      offering_id: 7,
      score: 0.85,
    },
  ];
  const { container } = render(
    <CalendarView
      events={matchEvents}
      view="week"
      onView={vi.fn()}
      date={new Date('2026-04-29T12:00:00Z')}
      onNavigate={vi.fn()}
      onSelectEvent={vi.fn()}
    />,
  );
  expect(container.querySelector('.rbc-event-match')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run; confirm FAIL**

```bash
cd frontend && npm run test -- CalendarView
```

- [ ] **Step 3: Update `eventPropGetter`**

In `frontend/src/components/calendar/CalendarView.tsx`, replace the `eventPropGetter` callback with a three-way branch:

```tsx
        eventPropGetter={(rbc) => {
          const k = (rbc as RbcEvent).resource.kind;
          return {
            className:
              k === 'enrollment'
                ? 'rbc-event-enrollment'
                : k === 'match'
                  ? 'rbc-event-match'
                  : 'rbc-event-unavailability',
          };
        }}
```

- [ ] **Step 4: Add the CSS rule**

In `frontend/src/components/calendar/calendar-overrides.css`, append:

```css
.rbc-event-match {
  background-color: transparent;
  color: hsl(var(--foreground));
  border: 1px dashed hsl(var(--primary));
}
```

- [ ] **Step 5: Re-run; confirm PASS + all CalendarView tests still pass**

```bash
cd frontend && npm run test -- CalendarView
```

Expected: 4 passed (3 from 5c-1 + 1 new).

- [ ] **Step 6: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 46 passed; clean.

- [ ] **Step 7: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/components/calendar/CalendarView.tsx frontend/src/components/calendar/CalendarView.test.tsx frontend/src/components/calendar/calendar-overrides.css
git commit -m "feat(frontend): CalendarView renders match events with dashed outline

eventPropGetter dispatches rbc-event-match for kind='match'.
Visually subordinate to enrollments + unavailability via transparent
background and dashed border."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 5 — `CalendarEventPopover` Enroll branch (TDD)

**Files:**
- Modify: `frontend/src/components/calendar/CalendarEventPopover.tsx`
- Modify: `frontend/src/components/calendar/CalendarEventPopover.test.tsx`

End state: Match events in the popover render an Enroll button + (optional) View details link. Click Enroll → mutation → close. 3 new tests pass.

- [ ] **Step 1: Append failing tests**

Append to `frontend/src/components/calendar/CalendarEventPopover.test.tsx`:

```tsx
const matchEvent: CalendarEvent = {
  id: 'match:7:2026-04-29',
  kind: 'match',
  date: '2026-04-29',
  time_start: '17:00:00',
  time_end: '18:00:00',
  all_day: false,
  title: 'Soccer',
  offering_id: 7,
  score: 0.85,
  registration_url: 'https://example.com/register',
};

const matchEventNoUrl: CalendarEvent = {
  ...matchEvent,
  registration_url: null,
};

describe('CalendarEventPopover (match events)', () => {
  it('renders match details + Enroll button + View details link', () => {
    renderPopover(matchEvent);
    expect(screen.getByText(/Soccer/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /enroll/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /view details/i })).toHaveAttribute(
      'href',
      'https://example.com/register',
    );
  });

  it('omits the View details link when registration_url is null', () => {
    renderPopover(matchEventNoUrl);
    expect(screen.queryByRole('link', { name: /view details/i })).not.toBeInTheDocument();
  });

  it('calls onClose after a successful Enroll', async () => {
    const onClose = vi.fn();
    renderPopover(matchEvent, onClose);
    await userEvent.click(screen.getByRole('button', { name: /enroll/i }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
```

- [ ] **Step 2: Run; confirm 3 FAIL**

```bash
cd frontend && npm run test -- CalendarEventPopover
```

- [ ] **Step 3: Update the popover component**

In `frontend/src/components/calendar/CalendarEventPopover.tsx`:

a. Add to imports:
```tsx
import { useCancelEnrollment, useDeleteUnavailability, useEnrollOffering } from '@/lib/mutations';
```

b. Add the third mutation in the component body alongside the existing two:
```tsx
const enroll = useEnrollOffering();
```

c. Update `inFlight`:
```tsx
const inFlight = cancel.isPending || del.isPending || enroll.isPending;
```

d. Update the `useEffect` reset block:
```tsx
useEffect(() => {
  startTransition(() => {
    setErrorMsg(null);
  });
  cancel.reset();
  del.reset();
  enroll.reset();
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [event?.id]);
```

e. Add a handler:
```tsx
const handleEnroll = () => {
  if (!event?.offering_id) return;
  setErrorMsg(null);
  enroll.mutate(
    { kidId, offeringId: event.offering_id },
    {
      onSuccess: onClose,
      onError: (err) => setErrorMsg(err.message || 'Failed to enroll'),
    },
  );
};
```

f. Inside the action-button block in the JSX, add a third branch BEFORE the existing enrollment/unavailability branches (so match takes precedence over the other kinds):

```tsx
{event.kind === 'match' ? (
  <>
    <Button onClick={handleEnroll} disabled={inFlight}>
      Enroll
    </Button>
    {event.registration_url && (
      <a
        href={event.registration_url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs text-muted-foreground underline self-center"
      >
        View details ↗
      </a>
    )}
  </>
) : isEnrollment ? (
  // ...existing enrollment branch...
) : !isLinkedBlock ? (
  // ...existing standalone-block branch...
) : (
  // ...existing linked-block helper text...
)}
```

(Adjust the JSX to use a clean conditional structure — likely a chain of ternaries inside the action `<div>`, OR break into a small inline render function. Read the current component before deciding the cleanest form.)

Also, update the `SheetDescription` line to optionally show the score for match events:

```tsx
<SheetDescription>
  {event.all_day
    ? 'All day'
    : `${event.time_start?.slice(0, 5)}–${event.time_end?.slice(0, 5)}`}
  {event.kind === 'match' && event.score != null && (
    <span className="ml-2 text-xs">Score: {event.score.toFixed(2)}</span>
  )}
</SheetDescription>
```

- [ ] **Step 4: Re-run; confirm all PASS**

```bash
cd frontend && npm run test -- CalendarEventPopover
```

Expected: 7 passed (4 from 5c-1 + 3 new).

- [ ] **Step 5: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 49 passed; typecheck and lint clean.

- [ ] **Step 6: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add frontend/src/components/calendar/CalendarEventPopover.tsx frontend/src/components/calendar/CalendarEventPopover.test.tsx
git commit -m "feat(frontend): popover Enroll branch for match events

Match events render an Enroll button + optional View details external
link. Score appears in the description. Dispatches useEnrollOffering
which optimistically removes the match and lets server invalidate
add the new enrollment + linked block."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 6 — Calendar route: "Show matches" toggle

**Files:**
- Modify: `frontend/src/routes/kids.$id.calendar.tsx`

End state: Toggle wired into the route. No new tests required (the toggle is a thin pass-through to the already-tested query hook), but verify the existing test suite still passes.

- [ ] **Step 1: Add `includeMatches` state and toggle UI**

In `frontend/src/routes/kids.$id.calendar.tsx`:

a. Add the state in `KidCalendarPage`:

```tsx
const [includeMatches, setIncludeMatches] = useState(false);
```

b. Pass it to the query hook:

```tsx
const calendar = useKidCalendar({ kidId, from, to, includeMatches });
```

c. Render the toggle. Place it above the `<CalendarView>` near the heading. The exact placement is a small UX choice; the cleanest spot is between the `KidTabs` line and the `<CalendarView>`:

```tsx
<div className="my-2 flex justify-end">
  <label className="flex items-center gap-1 text-xs text-muted-foreground">
    <input
      type="checkbox"
      checked={includeMatches}
      onChange={(e) => setIncludeMatches(e.target.checked)}
    />
    Show matches
  </label>
</div>
```

- [ ] **Step 2: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 49 passed; typecheck and lint clean.

- [ ] **Step 3: Commit**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
cd /Users/owine/Git/youth-activity-scheduler
git add 'frontend/src/routes/kids.$id.calendar.tsx'
git commit -m "feat(frontend): 'Show matches' toggle on calendar route

Component-local state, defaults to off. Threads includeMatches into
useKidCalendar; the cache-key discriminator at index 5 keeps the
two states cached independently."
git cat-file commit HEAD | grep -q '^gpgsig ' && echo signed
```

---

## Task 7 — Final exit gates + manual smoke + push + PR

End state: All exit criteria from spec §8 verified. Branch ready to merge.

- [ ] **Step 1: Backend gates**

```bash
uv run pytest -q --no-cov && uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: 567 passed; lint/format/type clean.

- [ ] **Step 2: Frontend gates**

```bash
cd frontend && npm run typecheck && npm run lint && npm run test
```

Expected: 49 passed; typecheck and lint clean.

- [ ] **Step 3: Manual smoke**

In one terminal:
```bash
uv run uvicorn yas.web.app:app --reload --port 8000
```

In another:
```bash
cd frontend && npm run dev
```

Open `http://localhost:5173/kids/1/calendar`. Walk through:
1. Default view: only enrollments + unavailability. No dashed events.
2. Tick "Show matches". Dashed-outline events appear if any high-score matches exist (or seed one via API/SQL if needed).
3. Click a match → popover with title + score + Enroll + View details (if registration_url set).
4. Click Enroll → match disappears optimistically; after a beat, the new enrollment + linked block appear.
5. Click cancel on the new enrollment → row vanishes; toggle "Show matches" off and on → the just-cancelled offering may reappear as a match if its score is ≥ 0.6 (cancelled enrollments don't suppress overlay).

If any step breaks, capture the failure as a regression test.

- [ ] **Step 4: Push branch and open PR**

```bash
export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
git push -u origin phase-5c-2-calendar-match-overlay
gh pr create --title "phase 5c-2: calendar match overlay + click-to-enroll" --body "$(cat <<'EOF'
## Summary

- Backend: `GET /api/kids/{id}/calendar?include_matches=true` merges matches scored ≥ 0.6 into the response, excluding offerings the kid has any non-cancelled enrollment for. New `kind=\"match\"` event with `score` + `registration_url`.
- Frontend: dashed-outline match events on the calendar grid, opt-in via a "Show matches" toggle on the calendar route (default off, component-local state).
- New mutation: `useEnrollOffering` follows the canonical 5b-1b/5c-1 pattern. Optimistically removes the match; server invalidate brings in the new enrollment + linked unavailability block.
- Popover: match branch renders Enroll button + optional View details external link + score.

## Test plan

- [x] uv run pytest -q (567 passed; +6 integration tests for match overlay)
- [x] uv run ruff check . && uv run ruff format --check . clean
- [x] uv run mypy src clean
- [x] cd frontend && npm run typecheck clean
- [x] cd frontend && npm run lint clean
- [x] cd frontend && npm run test (49 passed; +7 new across mutations + CalendarView + CalendarEventPopover)
- [ ] CI passes
- [ ] Manual smoke: enroll → match disappears optimistically; new enrollment + linked block arrive after server confirm; toggle off hides overlay

## Spec / plan

- Spec: `docs/superpowers/specs/2026-04-29-phase-5c-2-calendar-match-overlay-design.md`
- Plan: `docs/superpowers/plans/2026-04-29-phase-5c-2-calendar-match-overlay.md`

## Out of scope (deferred)

- User-controllable score threshold
- Status picker on Enroll (always sets enrolled)
- Watchlist / "ignore this match" affordance
- Multi-kid combined view
- Bulk enroll
EOF
)"
```

- [ ] **Step 5: Wait for CI; merge with `--squash`** (project convention).

---

## Notes for the implementer

- **Pattern fidelity matters.** `useEnrollOffering` is the third mutation in the codebase; copying the canonical 5b-1b/5c-1 shape exactly (cancelQueries → snapshot → setQueryData → onError restore → awaited onSettled invalidate) means future authors can read any of the four hooks and get the same shape.
- **Optimistic-only on the match removal.** Don't try to synthesize the new enrollment + linked block events client-side — the server creates an enrollment with a fresh id and a linked block via `apply_enrollment_block`, and we don't know those ids at mutation time. Let the server invalidate paint them in.
- **Threshold is a constant.** `_MATCH_THRESHOLD = 0.6`; do not surface a query param or a CLI flag — the spec's out-of-scope §1.2 explicitly forecloses user-controllable threshold.
- **The `~Match.offering_id.in_(committed_offering_ids)` subquery** is the join semantic that excludes both `enrolled` and `interested`. Reread spec §2.1 if there's any doubt — the `!= 'cancelled'` filter is the source of truth.
- **No new dependencies.**
- **Cache key segment 5** (`'with-matches' | 'no-matches'`) is what keeps the two variants cached independently. The mutation prefix `['kids', kidId, 'calendar']` matches both, so optimistic updates apply across the toggle state.
- **CSS variables follow the project's `hsl(var(--name))` convention** (see `frontend/src/styles/globals.css`). The override file uses the same form.
