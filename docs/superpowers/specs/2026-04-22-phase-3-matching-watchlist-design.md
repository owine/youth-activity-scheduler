# Phase 3 — Matching & Watchlist Design Spec

**Status:** Draft — awaiting user review
**Date:** 2026-04-22
**Depends on:** Phase 1 (Foundation) and Phase 2 (Crawl pipeline), both merged to `main`
**Target repo:** `youth-activity-scheduler/`

---

## 1. Purpose and scope

Turn extracted offerings into per-kid **matches**. You register a kid (dob, interests, school schedule, availability, distance cap); the matcher evaluates every active offering against every active kid and writes `matches` rows with a score and explainable `reasons` JSON. Event-driven hooks rematch on every relevant mutation (offering new/updated, kid edit, unavailability change, enrollment change). A nightly sweep catches date-based shifts (birthdays, school-year boundaries). Watchlist entries let the user mark specific programs they've already verified manually — those bypass all hard gates and always produce a match row. Location addresses from the extractor are geocoded via Nominatim so the distance gate has real coordinates to work with.

### In scope

- Matcher internals: pure hard gates (age, distance, interests, offering status, no-conflict with unavailability), pure weighted score with per-signal `reasons`
- Event-driven rematch hooks at all five mutation sites from Phase 1 spec §5.4
- Daily sweep (configurable UTC time) that re-matches all active kids to catch date-based shifts
- School-block materialization on kid edit — one `unavailability_blocks` row per `school_year_ranges` entry
- Enrollment-block materialization on `status=enrolled` transitions
- Watchlist with substring + glob pattern matching; watchlist hits bypass all hard gates (the user has manually verified the program)
- Nominatim geocoder with 1 req/s rate limit, a negative-cache table so unresolvable addresses stop getting retried, and a background enricher task
- Full HTTP CRUD for `/api/kids`, `/api/kids/{id}/watchlist`, `/api/kids/{id}/unavailability`, `/api/enrollments`, `/api/household`; read-only `/api/matches`
- Age evaluated against the offering's `start_date` (not today) so a kid who turns N before program start is eligible for N-year-old programs starting after their birthday

### Explicitly out of scope

- Alert delivery (Phase 4)
- Daily LLM cost-cap enforcement (Phase 6 ops polish)
- Web UI (Phase 5)
- SSE or any real-time match stream — `GET /api/matches` is pull-only
- Adaptive scheduler cadence (Phase 6)
- Driving-distance routing; haversine only

---

## 2. Architectural approach

Phase 3 adds three layers on top of Phase 2's crawl pipeline:

```
                ┌─── /api/kids ────┐
                │                  │
POST/PATCH ─► kid_crud ──► materialize_school_blocks
                │          └────────► unavailability_blocks
                │                       │
POST ─► /api/enrollments ──► materialize_enrollment_blocks
                │                  └─► unavailability_blocks
                │
reconciler.reconcile(offering.new/updated) ─┐
kid_crud.update                              ├─► matcher.rematch ─► matches
enrollments.set_status(enrolled|cancelled)  │
unavailability.crud (manual/custom only)     │
daily_sweep_loop (age/school-year rollover) ┘

geocode_enricher_loop ─► nominatim ─► locations.lat/lon
                                         └─► matcher.rematch_offering
```

**Design choices locked during brainstorming:**

- **Event-driven rematch hooks** (not dirty-flag sweeps) — each mutation site calls `matcher.rematch_*` synchronously. At Phase 3 scale (a handful of kids, hundreds of offerings) the matcher runs in milliseconds and simplicity wins.
- **School blocks are materialized** on kid edit, so matcher and calendar consume one uniform `unavailability_blocks` shape. `school_holidays` are NOT materialized as rows — they're per-date exceptions consulted at match time.
- **Nightly sweep** runs as a fourth task in the worker's `TaskGroup` — one loop, no cron dep.
- **`matches` rows are upserted** via composite-PK conflict resolution, deleted when a kid↔offering pair no longer passes gates (and isn't a watchlist hit). History lives implicitly in `offerings.raw_json`.
- **Haversine distance**, not driving time. Real travel ≈ 1.4× haversine; tune `max_distance_mi` conservatively.
- **Watchlist bypasses all hard gates.** A user adds a watchlist entry only after manual verification, so the matcher trusts them. The Phase 1 `watchlist_entries.ignore_hard_gates` column becomes effectively unused; interpret it semantically as "strict mode" in future (currently always off).

---

## 3. Modules (new code)

### 3.1 `src/yas/matching/gates.py` — pure hard gates

Five sync pure functions, each returning a `GateResult` namedtuple:

```python
GateResult = NamedTuple("GateResult", [("passed", bool), ("code", str), ("detail", str)])

def age_fits(kid, offering, *, today) -> GateResult: ...
def distance_fits(kid, offering, *, distance_mi, household_default) -> GateResult: ...
def interests_overlap(kid, offering, aliases) -> GateResult: ...
def offering_active_and_not_ended(offering, *, today) -> GateResult: ...
def no_conflict_with_unavailability(offering, blocks, school_holidays, *, today) -> GateResult: ...
```

**Age gate** evaluates age at `offering.start_date` (fallback: `today`), clamped ≥ 0.
**Distance gate** fails open on unknown location lat/lon; records `"distance_unknown"` code.
**Interests gate** matches kid interest vs `program_type` OR `normalize_name(name + " " + description)` contains the interest (or its alias).
**No-conflict gate** iterates each date in `[offering.start_date, offering.end_date]` matching `days_of_week`; for each date, checks whether any active block has `[date_start, date_end]` containing that date (or null endpoints = always active). Dates in `kid.school_holidays` skip the `source=school` block check. **Partial-schedule fail-open**: if offering is missing any of `start_date/end_date/days_of_week/time_start/time_end`, return `GateResult(True, "schedule_partial", …)`.

### 3.2 `src/yas/matching/scoring.py` — pure weighted score

```python
@dataclass(frozen=True)
class ScoreBreakdown:
    availability: float          # weight 0.4
    distance: float              # weight 0.2
    price: float                 # weight 0.1
    registration_timing: float   # weight 0.2
    freshness: float             # weight 0.1
    @property
    def score(self) -> float: ...
```

`compute_score(kid, offering, *, distance_mi, household_max_distance_mi, today) -> tuple[float, dict]`.

**Signal defaults on missing data:** availability 0.5, distance 0.5, price 1.0, registration timing 0.5.

**Detailed signals:**
- Availability: fraction of offering occurrence time windows overlapping `kid.availability`.
- Distance: full credit ≤ 30% of `max_distance_mi`, linear decay to 0 at cap.
- Price: full credit under `max_price_cents` (if set), linear decay to 0 at 2× max.
- Registration timing: open now → 1.0; ≤7d → 0.8; ≤30d → 0.6; closed → 0.0; unknown → 0.5.
- Freshness: linear 1.0 at `first_seen=today` to 0.0 at 60 days old.

### 3.3 `src/yas/matching/aliases.py` — interest alias map

A single module-level `INTEREST_ALIASES: dict[str, list[str]]` covering every `ProgramType` value. Used only by `interests_overlap`. Adding an alias is a one-line change; promote to a DB table if it ever becomes weekly editing.

### 3.4 `src/yas/matching/watchlist.py` — pure pattern matching

```python
@dataclass(frozen=True)
class WatchlistHit:
    entry: WatchlistEntry
    reason: Literal["substring", "glob"]

def matches_watchlist(offering, entries, *, site_id) -> WatchlistHit | None: ...
```

Pattern evaluation:
- Normalize offering name and pattern via `normalize_name` (shared from Phase 2).
- If pattern contains `*` or `?`, use `fnmatch.fnmatchcase` against the normalized name.
- Otherwise, substring check.
- `entry.site_id IS NULL` matches across all sites; else must equal `offering.site_id`.
- Precedence: `priority = "high"` first, then `priority = "normal"`, then ascending `entry.id`. First match wins. (Values from Phase 1 `WatchlistPriority` StrEnum: `high`, `normal` — there is no `low`.)

### 3.5 `src/yas/matching/matcher.py` — async orchestrator

Three public functions operating on an `AsyncSession`:

```python
async def rematch_kid(session, kid_id) -> MatchResult: ...
async def rematch_offering(session, offering_id) -> MatchResult: ...
async def rematch_all_active_kids(session) -> list[MatchResult]: ...
```

Per (kid, offering) pair:

```python
watchlist = matches_watchlist(offering, kid.watchlist_entries, site_id=offering.site_id)
gates = evaluate_all_gates(kid, offering, blocks, school_holidays, distance_mi, today)
score, breakdown = compute_score(kid, offering, ...)

if watchlist or all(g.passed for g in gates):
    upsert_match(kid_id, offering_id, score, reasons={
        "gates": {g.code: {"passed": g.passed, "detail": g.detail} for g in gates},
        "score_breakdown": breakdown.as_dict(),
        "watchlist_hit": {"entry_id": ..., "pattern": ..., "match_type": ..., "priority": ...} if watchlist else None,
    })
else:
    delete_match_if_exists(kid_id, offering_id)
```

Returns a `MatchResult` with `{kid_id?, offering_id?, new, updated, removed}` for logging. Does not commit — caller owns the transaction.

### 3.6 `src/yas/unavailability/school_materializer.py`

```python
async def materialize_school_blocks(session, kid_id) -> None: ...
```

Delete-and-rewrite pattern: delete all `source=school` rows for the kid, then insert one row per `kid.school_year_ranges` entry if `school_time_start` and `school_time_end` are both set. Idempotent.

### 3.7 `src/yas/unavailability/enrollment_materializer.py`

```python
async def apply_enrollment_block(session, enrollment_id) -> None: ...
```

- `status == enrolled` → upsert a `source=enrollment` block with `source_enrollment_id` FK, pulling `days_of_week/time_start/time_end/date_start/date_end` from the linked offering (nulls allowed when the offering has partial scheduling — the no-conflict gate's partial-schedule branch then fail-opens).
- Any other status → delete the block if present.

### 3.8 `src/yas/geo/client.py` — geocoder

```python
@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lon: float
    display_name: str
    provider: str  # "nominatim"

class Geocoder(Protocol):
    async def geocode(self, address: str) -> GeocodeResult | None: ...

class NominatimClient:
    BASE_URL = "https://nominatim.openstreetmap.org/search"
    USER_AGENT = "yas/0.1 (+https://github.com/example/youth-activity-scheduler)"
    def __init__(self, http_client=None, min_interval_s=1.0): ...
    async def geocode(self, address) -> GeocodeResult | None: ...
```

Internal `asyncio.Lock` + `_last_request_at` enforce the 1 req/s policy. On HTTP transport error, one retry at 2s, then `None`. On 429, double `min_interval_s` up to a 10s cap for that session. Empty JSON array → `None`. Parse errors → `None`.

### 3.9 `src/yas/geo/distance.py`

```python
def great_circle_miles(lat1, lon1, lat2, lon2) -> float: ...
```

Pure haversine. No extra deps.

### 3.10 `src/yas/geo/enricher.py`

```python
async def enrich_ungeocoded_locations(session, geocoder) -> EnrichResult: ...
async def geocode_enricher_loop(engine, settings, geocoder) -> None: ...
```

Per-tick algorithm:
1. Select up to `geocode_batch_size` from `locations` where `lat IS NULL AND address IS NOT NULL`.
2. Skip addresses whose normalized form has a matching `geocode_attempts` row with `result IN ('not_found', 'error')`. No time-based retry in Phase 3 — once an address is flagged unresolvable, the only way to retry is to change the address itself (which produces a new `address_norm` key). If retry-after becomes useful later, it's a small change to the skip predicate.
3. For each remaining address, call `geocoder.geocode(address)`. Hit → update `locations`, record `ok`. Miss → record `not_found`. Error → record `error` with `detail`.
4. For each location that just gained coordinates, select its offerings and call `matcher.rematch_offering(id)`.

Loop sleeps `geocode_tick_s` (default 300) between ticks.

### 3.11 `src/yas/web/routes/{kids,watchlist,unavailability,enrollments,matches,household}.py`

HTTP endpoints per §4 below. Each has a paired `*_schemas.py` with Pydantic request/response models, `ConfigDict(extra="forbid")` on write schemas.

---

## 4. HTTP API (all under `/api/`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/kids` | Create kid; optional nested `unavailability` and `watchlist` arrays for atomic creation |
| `GET` | `/api/kids` | List (name, dob, interests, active) |
| `GET` | `/api/kids/{id}` | Detail with blocks, watchlist, enrollments, top-10 matches |
| `PATCH` | `/api/kids/{id}` | Partial update (any subset of fields); triggers school-block materialization and rematch |
| `DELETE` | `/api/kids/{id}` | Cascades per FK |
| `GET/POST` | `/api/kids/{kid_id}/unavailability` | List all blocks / create manual block |
| `PATCH/DELETE` | `/api/kids/{kid_id}/unavailability/{id}` | Edit/remove — refuses on `source ∈ {school, enrollment}` with HTTP 409 |
| `GET/POST` | `/api/kids/{kid_id}/watchlist` | List / add |
| `PATCH/DELETE` | `/api/kids/{kid_id}/watchlist/{id}` | Edit / remove |
| `POST` | `/api/enrollments` | Create at any status |
| `GET` | `/api/enrollments?kid_id=&status=&offering_id=` | Filtered list |
| `GET` | `/api/enrollments/{id}` | Detail with kid + offering summary |
| `PATCH` | `/api/enrollments/{id}` | Any-to-any status transitions; re-materializes the enrollment block |
| `DELETE` | `/api/enrollments/{id}` | Removes block too |
| `GET` | `/api/matches?kid_id=&offering_id=&min_score=&limit=&offset=` | Paginated, read-only, includes `reasons` JSON |
| `GET/PATCH` | `/api/household` | Single-row settings (home location, default max distance, digest_time stub, etc.) |

All write endpoints call the appropriate rematch hook synchronously before responding.

**Household home-location handling:** when `PATCH /api/household` sets `home_location_id` to a location without coords, the handler attempts an immediate `geocoder.geocode()` call. If that succeeds, the location is updated in the same transaction. If it fails, the enricher picks it up on the next tick. Home location is the one field the distance gate can't do its job without — asking the user to wait 5 minutes after save is poor UX.

---

## 5. Worker integration

Phase 3 adds two new tasks to the worker's `asyncio.TaskGroup`:

```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(heartbeat_loop(...))
    tg.create_task(crawl_scheduler_loop(...))    # Phase 2
    tg.create_task(daily_sweep_loop(...))         # NEW
    tg.create_task(geocode_enricher_loop(...))   # NEW
```

### 5.1 Daily sweep

`daily_sweep_loop(engine, settings)`:
- Every 60s, check whether the current UTC wall clock is past `settings.sweep_time_utc` and today's sweep hasn't run yet.
- When due, call `matcher.rematch_all_active_kids()` inside one session.
- Mark completion in memory (the sweep is idempotent; persistence across restarts is not required — missing one day doesn't break correctness because event hooks cover mutations). A worker restart near the sweep window can cause at most one double-run (harmless; rematch is idempotent) or one skip (next-day sweep closes the gap).

### 5.2 Geocode enricher

See §3.10.

### 5.3 Pipeline integration

`src/yas/crawl/pipeline.py` gains one call after `reconciler.reconcile` returns: for each id in `new + updated`, invoke `matcher.rematch_offering(id)` inside the same session used by the reconcile step. On `page.changed` with an extractor failure, no rematch.

---

## 6. Data model changes

### 6.1 `geocode_attempts` table (new)

```sql
CREATE TABLE geocode_attempts (
    address_norm TEXT PRIMARY KEY,       -- normalize_name(address)
    last_tried   DATETIME NOT NULL,
    result       TEXT NOT NULL,          -- 'ok' | 'not_found' | 'error'
    detail       TEXT                    -- optional short error description
);
```

Created by one new Alembic migration: `alembic/versions/0002_geocode_attempts.py`.

### 6.2 `watchlist_entries.ignore_hard_gates` reinterpretation

No schema change. The column stays. Its semantics flip: **the default behavior is now "bypass all hard gates on watchlist hit"**; the column is reserved for a future "strict mode" opt-in (currently not consulted by the matcher).

**Required in Plan 3:** update the docstring on `WatchlistEntry.ignore_hard_gates` to flag that the column is not read by Phase 3 — so future readers don't assume it's wired. A comment like `# Reserved for future "strict mode" opt-in; unused in Phase 3.` is sufficient.

### 6.3 Household settings

`household_settings` already exists from Phase 1 as a single-row table. Phase 3 populates it via the new `/api/household` endpoints. No schema change. The row is created on first `PATCH` if missing.

### 6.4 `kids.max_price_cents`?

Not added in Phase 3. Spec §5.2 mentions "optional per-kid `max_price`" for the price signal; for Phase 3 we interpret this as always-unset (price signal → default 1.0). Adding a column is a trivial Phase 4 or 6 follow-up if you find yourself wanting it.

---

## 7. Configuration additions

```python
# src/yas/config.py additions
geocode_enabled: bool = True
geocode_tick_s: int = 300
geocode_batch_size: int = 20
geocode_nominatim_min_interval_s: float = 1.0

sweep_enabled: bool = True
sweep_time_utc: str = "07:00"
```

`.env.example` updated with the new vars.

---

## 8. Testing strategy

### 8.1 Unit (pure)

- `test_gates.py`: age-uses-start-date, partial-schedule-failopen, distance-unknown, distance-over-cap, interests-via-alias, interests-via-program-type, interests-via-description, offering-ended-too-long, summer-offering-passes-school-year, school-holiday-carves-exception, enrollment-block-blocks-sibling-time.
- `test_scoring.py`: each signal's full/partial/zero credit paths; composite score math; defaults on missing data.
- `test_watchlist_matcher.py`: substring, glob (single `*`, `?`, multiple globs), site scope (null vs matching vs mismatched), priority precedence.
- `test_distance.py`: known city pairs (NYC-LA, same-point, antipodes).
- `test_aliases.py`: all ProgramType values have entries; alias normalization.

### 8.2 Unit (DB-only)

- `test_school_materializer.py`: empty → populated, populated → rewritten, no school info → zero rows, partial school info → zero rows.
- `test_enrollment_materializer.py`: enrolled → block exists, interested → no block, cancelled → block removed, offering partial schedule → block with nulls.
- `test_nominatim_client.py`: respx-mocked happy path, 429 with interval-doubling, transport-error retry, empty result, rate-limit serialization of two concurrent calls.

### 8.3 Integration (real SQLite + fakes)

- `test_matcher.py`: end-to-end `rematch_kid` and `rematch_offering` drive full pipelines; assertions on `matches` rows.
- `test_enricher.py`: seeded `FakeGeocoder`, enricher tick, assert locations updated, offerings rematched, `geocode_attempts` correctly populated.

### 8.4 Named explicit scenarios (must-have test IDs)

- `test_age_uses_offering_start_date_not_today` — 4yo today, 5yo by program start → matches a 5yo program.
- `test_summer_offering_passes_school_year_gate` — school block 2026-09 to 2027-06; offering 2026-06-15 to 2026-08-15 — passes.
- `test_school_holiday_carves_exception_on_specific_date` — offering lands on MLK Day → school block skipped for that date.
- `test_watchlist_bypasses_all_hard_gates` — wrong-age wrong-distance offering on watchlist → match exists.
- `test_enrollment_block_prevents_sibling_match` — Kid A enrolls in Sat 9am soccer; rematching Kid A against another Sat 9am offering removes it; Kid B unaffected.
- `test_rematch_on_kid_patch_fires_once` — one PATCH → one matcher call (no double-fires).
- `test_home_location_immediate_geocode_on_household_save` — `PATCH /api/household` with new `home_location_id` triggers immediate geocode.

### 8.5 API

- `test_api_kids.py`: each of 5 endpoints including nested-on-create, partial PATCH, delete cascade.
- `test_api_watchlist.py`: CRUD plus `rematch_kid` invocation check.
- `test_api_unavailability.py`: CRUD on manual/custom, 409 on school/enrollment.
- `test_api_enrollments.py`: status transitions and block materialization round-trips.
- `test_api_matches.py`: filters, pagination, `reasons` shape.
- `test_api_household.py`: single-row semantics, immediate-geocode path.

### 8.6 Fakes

- `tests/fakes/geocoder.py` — `FakeGeocoder` with injected fixtures, misses, errors, and `call_count`.

---

## 9. Exit criteria

- All new tests green; full suite green
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` clean
- `alembic upgrade head` on fresh DB applies the `geocode_attempts` migration
- End-to-end smoke on Docker Compose (macOS overlay locally, bind mount on Linux):
  - `POST /api/household` with home address → home location geocoded
  - `POST /api/kids` for a real kid (dob, interests, school hours, school year range)
  - `POST /api/sites` for Lil Sluggers (already built in Phase 2 smoke)
  - Scheduler ticks; `offerings` appear; matcher fires
  - `GET /api/matches?kid_id=1` returns rows with score + reasons including a real distance derived from the geocoded coordinates
- Add a watchlist entry with a wildcard pattern → at least one watchlist-hit match present
- Enroll the kid in one offering → the next matcher run for that kid drops any conflicting offerings
- No silent failures: crawl/extract/geocode errors all visible in `crawl_runs.error_text` or a log line

---

## 10. Open questions / deferred decisions

- **`kids.max_price_cents` column** — skipped; price signal always defaults to 1.0. Trivial to add in Phase 4 if you find yourself wanting it.
- **Distance via routing API** — deferred. Revisit if haversine produces misleading numbers in practice.
- **Driving time in `reasons.distance.detail`** — related. Spec §9 already notes this as a deferred decision.
- **Match history / audit log** — not added. Offerings' `raw_json` + the current kid state are sufficient to reconstruct why a match appeared or disappeared for the foreseeable future.
- **Alias configuration via DB or YAML** — kept in a Python dict for now. Promotion path is straightforward.
- **Nominatim alternatives (Mapbox, Google)** — not wired as pluggable providers. The `Geocoder` protocol makes this swap a ~30-line change if needed.

---

## 11. What Phase 3 does NOT touch

- Alerting / channels / digest — Phase 4
- Calendar view, dashboard, Add Site wizard — Phase 5
- Adapter framework (hand-written site adapters) — Phase 6
- Haiku → Sonnet fallback — Phase 6
- Playwright tuning, adaptive cadence — Phase 6
- LLM daily cost cap enforcement — Phase 6
