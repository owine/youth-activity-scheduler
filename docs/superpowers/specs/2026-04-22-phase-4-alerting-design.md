# Phase 4 — Alerting Design Spec

**Status:** Draft — awaiting user review
**Date:** 2026-04-22
**Depends on:** Phase 1 (Foundation), Phase 2 (Crawl), Phase 3 (Matching), Phase 3.5 (Site Discovery) — all merged to `main`
**Target repo:** `youth-activity-scheduler/`

---

## 1. Purpose and scope

Turn `matches` rows + pipeline events + daily DB-state inspection into delivered alerts the user actually reads. Two new-match notifications for Sam should produce one email saying "Sam has two new matches today." A registration that opens in 24 hours should produce an email now; at 1 hour should produce a push; at 0 should produce an emergency-priority push that retries until the user acknowledges. A site that hasn't yielded a new offering in 30 days should surface in the next daily digest, not as an alarming push. A kid registered 7 days ago with zero matches should get a honest "we looked, here's what we saw (nothing yet)" nudge.

### Learnings from Phase 3 / Phase 3.5 smokes baked into this design

1. **"Tracked page → zero offerings" is a silent state.** Phase 3's Lil Sluggers snapshot was stale (6 offerings extracted, all `end_date=2024-06-13`); Phase 3.5's YSIFC listing page produced zero offerings entirely. In both cases nothing was wrong in the pipeline and the user had no visibility. Phase 4 introduces a `site_stagnant` alert type (fires when a site has had no `offering.first_seen` events in N days) surfaced in the daily digest.

2. **"Kid registered → zero matches after N days" is also silent.** Phase 4 introduces `no_matches_for_kid` (fires once when an active kid has been registered for N days with zero matches ever).

3. **Watchlist hits are the user's manual trust signal.** Honored by routing — `watchlist_hit` is never coalesced, bypasses score thresholds entirely (upstream, in the matcher), routes to both email and push by default.

4. **Registration-opens timing is the premium use case.** The `reg_opens_24h → reg_opens_1h → reg_opens_now` countdown is the feature the user explicitly opted in to get woken up for. `reg_opens_now` hardcoded to bypass quiet hours.

5. **Stale-data detection isn't "crawl failed."** An extractor succeeding against a snapshot of 2024 dates is healthy by Phase 2's definitions but useless to the user. `site_stagnant` catches this via `offering.first_seen` volume — not via `crawl_runs.status`.

6. **SQLite + Docker-for-macOS concurrency.** Alert delivery is a new writer that bursts during digest builds (~20 rows in one tick). Phase 1's `busy_timeout=5000` helps; delivery is idempotent and retries transient failures so the occasional write collision doesn't lose alerts.

### In scope

- Three channels: **Email** (multi-transport: SMTP via `aiosmtplib`, or ForwardEmail REST API), **ntfy** (HTTP POST; self-hostable), **Pushover** (HTTP POST; `priority=2` emergency for reg-opens-now)
- 8 alert types: `watchlist_hit`, `new_match`, `reg_opens_24h`, `reg_opens_1h`, `reg_opens_now`, `schedule_posted`, `crawl_failed`, `digest`, plus 2 new per learnings: `site_stagnant`, `no_matches_for_kid`
- Event-driven enqueuer at each pipeline and matcher event site
- Polled delivery loop (60s tick) with: coalescing within `(kid_id, type)` × 10-minute window, per-kid push rate cap (5/h across push channels combined), quiet-hours suppression for pushes (`reg_opens_now` exempt), exponential-backoff retries (1m / 5m / 30m / then failed-digest)
- Countdown scheduling: on `offering.registration_opens_at` set/change, insert `T-24h / T-1h / T-0` rows with dedup_key; delete-and-rewrite on date change
- Daily digest (07:00 UTC, per active kid) with LLM top-line + Jinja body; falls back to template on LLM failure; skipped on empty days (except within `no_matches_for_kid` threshold window)
- Daily detector loop (09:00 UTC): `site_stagnant`, `no_matches_for_kid`
- Silent-failure visibility: failed deliveries surfaced in the next daily digest
- HTTP: `GET /api/alerts`, `GET /api/alerts/{id}`, `POST /api/alerts/{id}/resend`, `GET /api/alert_routing`, `PATCH /api/alert_routing/{type}`, `POST /api/digest/preview?kid_id=N`
- Secrets policy: channel config in DB stores env-var NAMES, not values; actual secrets live in `.env`

### Explicitly out of scope

- Home Assistant channel (removed from roadmap; reinstate only if asked)
- Web UI for configuring channels / routing / quiet hours (Phase 5)
- SMS, Slack, Discord (YAGNI)
- Alert acknowledgement / dismissal endpoint (Phase 5 UI)
- User-level (vs household-level) routing preferences (Phase 5+ if needed)
- Anomaly detection or ML-based "unusual" alerts
- Async job queue (Phase 5 if the delivery loop becomes a bottleneck)

---

## 2. Architectural approach

Three new concurrent tasks alongside the Phase 3 worker TaskGroup:

```
Phase 3 tasks (kept):
  heartbeat_loop, crawl_scheduler_loop, daily_sweep_loop, geocode_enricher_loop

Phase 4 additions:
  alert_delivery_loop        tick=60s; drains due alerts
  daily_digest_loop          07:00 UTC; builds + enqueues digests
  detector_loop              09:00 UTC; site_stagnant + no_matches_for_kid
```

Seven concurrent async tasks in one process, same single-writer sqlite pattern as Phase 3. Enqueuer is synchronous at event boundaries (pipeline, matcher) — same pattern as Phase 3's event-driven rematch hooks. Delivery is polled, not pushed — a 60-second tick is responsive enough for a T-1h countdown alert (will deliver within a minute of due).

### Data flow

```
pipeline.crawl_page                     matcher.rematch_*
    │ reconcile + rematch                     │ MatchResult.new
    │ offering.new/updated                    │ watchlist_hit newly true
    │ registration_opens_at set/changed       │
    └──────┬─────────────┬────────────────────┘
           │             │
           ▼             ▼
    enqueue_new_match  enqueue_watchlist_hit
    enqueue_registration_countdowns
                        │
                        ▼
              ┌──────────────────────┐
              │  alerts table        │
              │  (scheduled_for,     │
              │   dedup_key,         │
              │   payload_json)      │
              └──────────────────────┘
                        ▲
    ┌───────────────────┤
    │                   │
  detector_loop    daily_digest_loop
    │                   │
    │ site_stagnant     │ build per-kid digest
    │ no_matches_kid    │ LLM top-line + template
    │                   │ enqueue_digest
    └───────────────────┘
                        ▲
                        │
          ┌─ alert_delivery_loop (60s) ──────────┐
          │                                      │
          │  SELECT due → coalesce → rate-cap   │
          │    → quiet-hours filter (push)      │
          │    → route via alert_routing        │
          │    → Notifier.send                   │
          │    → on transient fail: reschedule  │
          │    → on success: mark sent_at        │
          │    → on final fail: skipped + note   │
          │                                      │
          └──────────────────────────────────────┘
                        │
                        ▼
             Email | ntfy | Pushover
```

### Three notes locked during brainstorming

1. **Enqueuer at event, delivery by poll.** No event bus. Each pipeline/matcher mutation hook inserts rows; one shared loop drains.
2. **Coalescing at delivery time, not enqueue time.** A 10-min window group happens when the delivery tick finds multiple due rows sharing `(kid_id, type)`. Adding a new alert type doesn't need enqueuer changes.
3. **`reg_opens_now` bypasses quiet hours.** Hardcoded. The user opted in to getting woken up for THIS event; suppressing it defeats the point.

---

## 3. Modules

```
src/yas/alerts/                         # NEW package
├── __init__.py
├── enqueuer.py                          # event-hook entry points
├── schemas.py                           # alert payload shapes (Pydantic)
├── delivery.py                          # coalesce + send-one-group orchestrator
├── routing.py                           # reads alert_routing table; chooses channels
├── rate_limit.py                        # per-kid push cap + quiet-hours helper (pure)
├── digest/
│   ├── __init__.py
│   ├── builder.py                       # DB gather + Jinja render
│   ├── llm_summary.py                   # LLM top-line + template fallback
│   └── templates/
│       ├── digest.html.j2
│       └── digest.txt.j2
├── channels/
│   ├── __init__.py
│   ├── base.py                          # Notifier Protocol + NotifierMessage + SendResult
│   ├── email.py                         # EmailChannel + _SMTPTransport + _ForwardEmailTransport
│   ├── ntfy.py                          # NtfyChannel
│   └── pushover.py                      # PushoverChannel
└── detectors/
    ├── __init__.py
    ├── site_stagnant.py                 # async detect_stagnant_sites(session, threshold_days)
    └── no_matches_for_kid.py            # async detect_kids_without_matches(session, threshold_days)

src/yas/worker/
├── delivery_loop.py                     # NEW
├── digest_loop.py                       # NEW
└── detector_loop.py                     # NEW

src/yas/web/routes/
├── alerts.py                            # NEW
├── alerts_schemas.py                    # NEW
├── alert_routing.py                     # NEW
└── alert_routing_schemas.py             # NEW

tests/fakes/
├── notifier.py                          # NEW
└── smtp_server.py                       # NEW (thin wrapper over aiosmtpd)
```

### 3.1 Enqueuer — `src/yas/alerts/enqueuer.py`

One function per event source. Each operates on an open `AsyncSession`, computes a `dedup_key` per spec §6.1, inserts or updates an `alerts` row, and returns the id:

```python
async def enqueue_new_match(session, kid_id, offering_id, score, reasons) -> int | None: ...
async def enqueue_watchlist_hit(session, kid_id, offering_id, watchlist_entry_id, reasons) -> int: ...
async def enqueue_schedule_posted(session, page_id, site_id, summary) -> int: ...
async def enqueue_crawl_failed(session, site_id, consecutive_failures, last_error) -> int | None: ...
async def enqueue_registration_countdowns(session, offering_id, kid_id, opens_at) -> list[int]: ...
async def enqueue_site_stagnant(session, site_id, days_silent) -> int | None: ...
async def enqueue_no_matches_for_kid(session, kid_id, days_since_created) -> int | None: ...
async def enqueue_digest(session, kid_id, for_date, payload) -> int: ...
```

**dedup_key format** (extends Phase 3 convention):
- General: `{type}:{kid_id or "-"}:{offering_id or site_id or "-"}`
- `new_match`: `new_match:{kid_id}:{offering_id}` — identical from pipeline-path and matcher-path rematch calls, so either ordering dedups correctly
- `watchlist_hit`: `watchlist_hit:{kid_id}:{offering_id}`
- Countdowns: append `scheduled_for` ISO bucket (minute precision) so the three rows don't collide: `reg_opens_24h:{kid_id}:{offering_id}:{scheduled_for_iso_minute}`
- `digest`: append `for_date`: `digest:{kid_id}:{for_date_iso}`
- `site_stagnant`: `site_stagnant:-:{site_id}` — no kid; one alert per stagnant site regardless of affected-kid count
- `no_matches_for_kid`: `no_matches_for_kid:{kid_id}:-`
- `crawl_failed`: `crawl_failed:-:{site_id}` — one alert per site escalation, not per failed page
- `schedule_posted`: `schedule_posted:-:{site_id}:{page_id}` — rolls into digest only
- `push_cap` (consolidated excess): `push_cap:{kid_id}:{hour_bucket_iso}` — see §3.7

Dedup behavior: if an UNSENT row exists with the same key, the enqueuer **updates** the row's `payload_json` and `scheduled_for` (for countdown-style update) rather than inserting. Sent rows don't dedup — they're history.

### 3.2 Event hook wiring

| Event | Site | Call |
|---|---|---|
| `reconciler.reconcile` produced new/updated offerings | `pipeline.crawl_page` (after existing rematch_offering loop) | for each match `MatchResult.new`: `enqueue_new_match` if above threshold OR `enqueue_watchlist_hit` if `reasons.watchlist_hit` |
| `offering.registration_opens_at` newly set or changed | same spot, after rematch | for each active match on that offering: `enqueue_registration_countdowns` |
| `page.changed`, `reconcile_result.new==0 AND .updated==0` | pipeline | `enqueue_schedule_posted` (rolls into digest only) |
| `page.consecutive_failures` hits 3 | pipeline's failure branch | `enqueue_crawl_failed` once per escalation |
| matcher's `rematch_kid` / `rematch_offering` return `MatchResult.new` | matcher (after upsert) | same `enqueue_new_match` / `enqueue_watchlist_hit` as the pipeline path. In practice the pipeline's rematch_offering call upstream-triggers this; guard with dedup_key so we don't duplicate |
| Daily detectors fire | `detector_loop` | `enqueue_site_stagnant`, `enqueue_no_matches_for_kid` |
| Digest build completes | `daily_digest_loop` | `enqueue_digest` |

**Only `MatchResult.new` produces alerts** — not `.updated` or `.removed`. An offering's score climbing or falling doesn't re-notify.

### 3.3 Countdown scheduling — `enqueue_registration_countdowns`

1. Delete unsent `reg_opens_*` alerts for this `(kid_id, offering_id)` pair. Idempotent; handles the "registration date shifted" case cleanly.
2. Compute `T-24h`, `T-1h`, `T` timestamps.
3. Skip any `scheduled_for < now`.
4. Insert rows with `payload_json = {kid_id, offering_id, opens_at, offering_name, registration_url}`.

**Startup grace window:** on worker startup, alerts with `scheduled_for > now - 24h AND scheduled_for <= now` are still due (fire once). Older past-due alerts are marked `skipped=true, sent_at=now` with detail "past-due beyond grace window". Grace configured via `alert_countdown_past_due_grace_s` (86400).

### 3.4 Silent-state detectors

Pure functions over DB state, called from `detector_loop` once per day at `alert_detector_time_utc` (09:00 UTC).

**`site_stagnant.py`:**
```python
async def detect_stagnant_sites(session, threshold_days: int = 30) -> list[int]:
    """Return active, non-muted site_ids with zero offering.first_seen events
    in the last N days. Sites with no offerings at all (fresh registrations)
    are excluded so we don't nag during the first N days after adding a site."""
```

**`no_matches_for_kid.py`:**
```python
async def detect_kids_without_matches(session, threshold_days: int = 7) -> list[int]:
    """Return kid_ids where: kid.active=True AND kid.created_at <= now-N days
    AND zero matches rows exist (ever) for this kid."""
```

Both detectors are idempotent; the enqueuer's dedup_key prevents re-alerting the same state.

### 3.5 Delivery loop — `src/yas/worker/delivery_loop.py`

```python
async def alert_delivery_loop(engine, settings, notifiers: dict[str, Notifier]) -> None:
    """Every alert_delivery_tick_s: drain up to 100 due alerts per tick."""
```

Per-tick algorithm:

1. SQL: `SELECT * FROM alerts WHERE sent_at IS NULL AND skipped=FALSE AND scheduled_for <= now ORDER BY scheduled_for ASC LIMIT 100`
2. Apply startup grace window: past-due beyond 24h → mark skipped, continue.
3. Coalesce groups (section 3.6).
4. For each group, lookup channels via `alert_routing` table.
5. Apply per-kid push rate cap (section 3.7).
6. Apply quiet-hours filter to push channels (section 3.8).
7. Call `Notifier.send` per channel; on success → `sent_at=now`; on transient failure → reschedule with backoff; on non-transient or exhausted retries → `skipped=true`, detail in payload for digest.

### 3.6 Coalescing — `src/yas/alerts/delivery.py::coalesce`

```python
@dataclass(frozen=True)
class AlertGroup:
    lead: Alert
    members: list[Alert]
    kid_id: int | None
    alert_type: AlertType

def coalesce(due: list[Alert], *, window_s: int) -> list[AlertGroup]: ...
```

- Key: `(kid_id, type)` where alerts are within `window_s` of each other (by `scheduled_for`).
- **Never coalesced** (always sent individually): `reg_opens_now`, `reg_opens_1h`, `watchlist_hit`, `crawl_failed`, `digest`.
- Mainly merges `new_match` and `reg_opens_24h`.

### 3.7 Per-kid push rate cap — `src/yas/alerts/rate_limit.py`

```python
async def count_pushes_sent_in_last_hour(session, kid_id) -> int: ...
def should_rate_limit_push(sent_count: int, max_per_hour: int) -> bool: ...
```

Applied only to push-channel routings (ntfy + Pushover combined). Email uncapped.

**Excess handling:** when a push group would exceed the cap, the worker skips push for that group AND enqueues a single consolidated push with `dedup_key="push_cap:{kid_id}:{hour_bucket}"` where `hour_bucket = now_utc.strftime("%Y-%m-%dT%H")`. On successive hits within the same hour, the dedup-key collision means the enqueuer **updates** the existing unsent row's `payload_json.count` (incrementing) and `payload_json.alert_type_counts` (per-type tally), rather than inserting a duplicate. Subject/body render at send time using the current count. Email side of the same group still delivers uncapped.

### 3.8 Quiet hours — `src/yas/alerts/rate_limit.py`

```python
def is_in_quiet_hours(now_utc, quiet_start, quiet_end) -> bool: ...
```

Pure. Both fields `HH:MM` UTC; wrap-around (e.g. `22:00..07:00`) handled. During quiet hours, push channels are **skipped entirely** (not buffered). Email continues. **`reg_opens_now` bypasses quiet hours** hardcoded.

### 3.9 Channel adapters

All implement `Notifier` Protocol from `src/yas/alerts/channels/base.py`:

```python
class NotifierCapability(StrEnum):
    email = "email"
    push = "push"
    push_emergency = "push_emergency"

@dataclass(frozen=True)
class NotifierMessage:
    kid_id: int | None
    alert_type: AlertType
    subject: str
    body_plain: str
    body_html: str | None = None
    url: str | None = None
    urgent: bool = False

@dataclass(frozen=True)
class SendResult:
    ok: bool
    transient_failure: bool
    detail: str

class Notifier(Protocol):
    name: str
    capabilities: set[NotifierCapability]
    async def send(self, msg: NotifierMessage) -> SendResult: ...
    async def aclose(self) -> None: ...
```

#### 3.9.1 EmailChannel — `src/yas/alerts/channels/email.py`

Multi-transport. DB config selects `transport: "smtp" | "forwardemail"`.

**`_SMTPTransport`** (default): `aiosmtplib` to configured host/port with STARTTLS, credentials from env (`password_env` names the env var).

**`_ForwardEmailTransport`**: `httpx.AsyncClient.post` to `https://api.forwardemail.net/v1/emails` with Basic Auth (token from env), form fields `from`, `to`, `subject`, `text`, `html`.

Both implement `_EmailTransport` Protocol. `_build_email()` is a shared pure function that produces the multipart/alternative MIME structure.

Capabilities: `{email}`.

#### 3.9.2 NtfyChannel — `src/yas/alerts/channels/ntfy.py`

`httpx.AsyncClient.post` to `{base_url}/{topic}` with headers:
- `Title`: `msg.subject`
- `Priority`: `high` if `msg.urgent` else unset
- `Click`: `msg.url` if set
- `Authorization: Bearer <token>` if token configured

Capabilities: `{push}`. No emergency-priority.

#### 3.9.3 PushoverChannel — `src/yas/alerts/channels/pushover.py`

`httpx.AsyncClient.post` to `https://api.pushover.net/1/messages.json` form-encoded:
- `token`, `user`, `title`, `message`, `url` + `url_title` if set
- `priority=2` when `alert_type == reg_opens_now` (emergency); `retry` + `expire` params
- `devices` if configured

Capabilities: `{push, push_emergency}`.

### 3.10 Routing — `src/yas/alerts/routing.py`

Reads `alert_routing` table (created in Phase 1 migration; currently unused). One row per alert type with `channels: list[str]` and `enabled: bool`.

**Seeded defaults** (inserted at worker startup if the table is empty):

| Type | Channels |
|---|---|
| `watchlist_hit` | push + email |
| `new_match` | email |
| `reg_opens_24h` | email |
| `reg_opens_1h` | push |
| `reg_opens_now` | push + email |
| `schedule_posted` | (none — digest only) |
| `crawl_failed` | email |
| `site_stagnant` | (none — digest only) |
| `no_matches_for_kid` | (none — digest only) |
| `digest` | email |

"push" resolves to the first configured channel with `NotifierCapability.push`. For `reg_opens_now` the routing layer prefers a channel with `push_emergency` capability (Pushover), falling back to `push` with a downgrade log line if Pushover isn't configured. Downgrades also enqueue a `schedule_posted`-equivalent note for the next digest so the user sees "we couldn't emergency-push; Pushover not configured" in context, not just in logs.

### 3.11 Digest

**`daily_digest_loop`** at `alert_digest_time_utc` (07:00 UTC). Same tick-check pattern as the Phase 3 sweep loop. Per active kid:

1. Gather data:
   - **New matches**: `matches` rows where `computed_at >= now - 24h` AND `matches.kid_id = kid.id`
   - **Starting soon**: active offerings matched to this kid with `start_date IN (today, today + 14d]`
   - **Registration calendar**: active offerings matched to this kid with `registration_opens_at IN (now, now + 14d]`
   - **Delivery failures**: `alerts` rows where `skipped=true AND sent_at >= previous_digest_timestamp_for_kid OR now - 24h, whichever is earlier`. `previous_digest_timestamp_for_kid` is the most recent `alerts.sent_at` where `type=digest AND kid_id=this kid`.
   - **Stagnant site ids**: from today's `detect_stagnant_sites()` result
   - **Silent page changes**: `schedule_posted` alerts scheduled in the last 24h (always skipped from direct delivery per routing; digest is their only surface)
2. LLM top-line via `llm_summary.generate_top_line` with cost-cap gate. Falls back to templated `"{kid.name}'s activities — {n_new} new matches, {n_soon_reg} opening soon"` on any failure.
3. Render `digest.html.j2` + `digest.txt.j2`.
4. `enqueue_digest(kid_id, today, payload={subject, body_plain, body_html})`.

**Empty-day skip:** if zero new matches, zero starting-soon, zero registration-calendar rows, zero watchlist hits, zero delivery failures → skip enqueue (debug-log "digest.skipped.empty"). **Exception:** if kid is within `alert_no_matches_kid_days` (7 default) AND has zero matches, send anyway — this is the "we looked, nothing yet" signal.

Delivery routes via `alert_routing[digest]` — email-only by default.

### 3.12 HTTP endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/alerts` | Paginated; filters: `kid_id`, `type`, `status=pending\|sent\|skipped`, `since`, `until`, `limit`, `offset` |
| `GET` | `/api/alerts/{id}` | Detail with delivery history |
| `POST` | `/api/alerts/{id}/resend` | Clone an already-sent alert with `scheduled_for=now` |
| `GET` | `/api/alert_routing` | Read routing table |
| `PATCH` | `/api/alert_routing/{type}` | Edit channels + enabled |
| `POST` | `/api/digest/preview?kid_id=N` | Build + render digest without enqueueing; returns `{subject, body_plain, body_html}` |

All under the existing `sites_router`-adjacent pattern; no auth.

---

## 4. Secrets and configuration

### 4.1 Secrets policy

Channel config stored in DB references env var NAMES, not values. Example `email_config_json`:

```json
{
  "transport": "smtp",
  "from_addr": "yas@example.com",
  "to_addrs": ["you@example.com"],
  "host": "smtp.fastmail.com",
  "port": 587,
  "username": "...",
  "password_env": "YAS_SMTP_PASSWORD",
  "use_tls": true
}
```

Startup check verifies required env vars per configured channel; missing env → channel disabled at runtime with a log warning (not a crash). Makes DB dumps shareable without leaking secrets.

### 4.2 New config fields — `src/yas/config.py`

```python
alerts_enabled: bool = True
alert_delivery_tick_s: int = 60
alert_coalesce_normal_s: int = 600                  # 10 min
alert_max_pushes_per_hour: int = 5
alert_digest_time_utc: str = "07:00"
alert_detector_time_utc: str = "09:00"
alert_stagnant_site_days: int = 30
alert_no_matches_kid_days: int = 7
alert_countdown_past_due_grace_s: int = 86400       # 24 h
alert_digest_empty_skip: bool = True

# Channel secrets (env-only; optional)
smtp_password: str | None = None
forwardemail_api_token: str | None = None
ntfy_auth_token: str | None = None
pushover_user_key: str | None = None
pushover_app_token: str | None = None
```

`.env.example` updated with all `YAS_*` entries.

---

## 5. Dependencies

Added runtime:
- `aiosmtplib>=3.0` (SMTP transport)
- `jinja2` already in deps from Phase 1

Added dev:
- `aiosmtpd>=1.4` (test-only SMTP server fixture)

ntfy, Pushover, ForwardEmail all use existing `httpx`.

---

## 6. Testing strategy

### 6.1 Unit (pure)

- `dedup_key` generation per alert type; includes scheduled_for bucket for countdowns, for_date for digest
- `coalesce(due, window_s)` — parametrized: single-alert group, multi-alert same-window merge, across-window non-merge, across-type non-merge, non-coalesceable types pass-through
- `should_rate_limit_push(count, max)`
- `is_in_quiet_hours(now, start, end)` — wrap-around cases (22:00..07:00); same-day cases; None fields
- `_build_email(subject, from, to, text, html)` — MIME correctness, multipart/alternative
- Jinja filters: `price`, `rel_date`, `fmt`

### 6.2 Unit (DB-backed)

- Each `enqueue_*`: insert-on-first, update-on-dedup-hit, no-op when preconditions unmet (e.g. `kid.alert_on.new_match=false`)
- `detect_stagnant_sites(session)` with seeded offerings; edge cases: brand-new site (no offerings), site with offerings only in last N days, site with offerings all older than N days
- `detect_kids_without_matches(session)` with seeded kids and matches

### 6.3 Channel unit

- `EmailChannel` with `_SMTPTransport` against `aiosmtpd` fixture: real SMTP session, assert message arrival, headers, body, multipart structure
- `EmailChannel` with `_ForwardEmailTransport` against `respx`: assert Basic Auth header, form body
- `NtfyChannel` against `respx`: POST path, `Title`/`Priority`/`Click` headers, bearer-token header when configured
- `PushoverChannel` against `respx`: form fields; `priority=2` ONLY for `reg_opens_now`; `devices` list passed through when configured

### 6.4 Integration

- `delivery_loop` with `FakeNotifier`: drive mixed batch including coalesce groups, quiet-hours suppression (push skipped, email still sent), rate-cap overflow (first 5 send, rest → one consolidated push), transient-failure retry (3 retries then failed-digest note), `reg_opens_now` bypass of quiet hours
- `digest_loop` with seeded matches + offerings: assert correct enqueue shape + body content; LLM top-line present; fallback on LLM failure; empty-day skip; exception for kid under no-matches threshold
- `detector_loop`: site_stagnant + no_matches detection end-to-end
- Countdown scheduling: reconcile sets `registration_opens_at` → three alerts appear in DB with correct `scheduled_for`; change the date → old unsent rows deleted, new inserted
- `/api/alerts` pagination; `/api/alerts/{id}/resend` inserts a cloned row; `/api/digest/preview` returns rendered HTML + text without enqueueing

### 6.5 Named must-have tests

- `test_reg_opens_now_bypasses_quiet_hours`
- `test_push_rate_cap_coalesces_excess_to_single_message`
- `test_coalesce_merges_within_window_but_not_across_types`
- `test_digest_empty_day_skipped_but_logs_debug`
- `test_digest_no_matches_kid_under_threshold_sends_honest_message`
- `test_pushover_priority_2_for_reg_opens_now`
- `test_forwardemail_transport_sends_via_api_on_config_select`
- `test_alerts_resend_clones_original_payload`
- `test_startup_grace_window_fires_recent_past_due_countdown_once`
- `test_site_stagnant_detector_ignores_fresh_sites`
- `test_no_matches_for_kid_detector_requires_N_days_active`
- `test_llm_top_line_falls_back_to_template_on_failure`
- `test_countdown_rewrite_on_registration_date_change`

### 6.6 Fakes

- `tests/fakes/notifier.py` — `FakeNotifier(records=[], failure_queue=None)`; records sends, configurable transient/non-transient failure simulation
- `tests/fakes/smtp_server.py` — thin wrapper that starts `aiosmtpd` on port 0, captures messages

### 6.7 Manual smoke

`scripts/smoke_phase4.sh`:

- Adds a **Mailpit sidecar** to `docker-compose.yml` (image `axllent/mailpit`, published :1025 SMTP + :8025 web UI). Not a Python dep — a compose service. Disabled in production compose; only used by this smoke script.
- Configures email via Mailpit sidecar (catches all outbound SMTP; web UI at :8025 for inspection) OR ForwardEmail when `FORWARDEMAIL_SMOKE=1`
- Configures ntfy against `https://ntfy.sh/<random-topic>` (subscribe before running)
- Configures Pushover from real env (optional; skipped if `YAS_PUSHOVER_USER_KEY` absent)
- Onboards a kid + site (YSIFC), forces a crawl + watchlist add
- Waits; asserts Pushover received a watchlist-hit push; asserts email received in Mailpit (or the `to` inbox for ForwardEmail)
- Forces a digest build via `POST /api/digest/preview`; verifies `body_html` contains expected sections

---

## 7. Exit criteria

- `uv run pytest` green including all Phase 4 tests + prior phases
- `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` clean
- End-to-end smoke:
  - Real Pushover configured; watchlist entry + offering reconcile → push received with `priority=2` for `reg_opens_now` path, regular priority for `watchlist_hit`
  - Daily digest built via `/api/digest/preview` returns rendered HTML + text; both `body_plain` and `body_html` contain the expected sections (new matches, registration calendar, delivery issues if any)
  - ForwardEmail transport: toggle `email_config_json.transport` from `smtp` → `forwardemail` → digest arrives via the API path (Mailpit sees zero; ForwardEmail inbox receives)
  - Push rate cap: inject 10 pushes to the same kid within 10 min → first 5 deliver, next 5 coalesce into one "+5 more" consolidated push
  - Quiet hours: `reg_opens_now` at 3am bypasses; `new_match` at 3am is suppressed for push but email still sends
- `GET /api/alerts?type=new_match&limit=20` returns paginated history with delivery status
- No silent failures: every transient send failure surfaces in the next digest's "Delivery issues" section

---

## 8. Open questions / deferred

- **Phase 5 will want UI for channel/routing config.** Phase 4 surfaces this via `/api/alert_routing` PATCH; no blocker.
- **Secrets-in-DB vs env** — current choice is env-referenced. If Phase 5 UI would prefer writable-from-UI (inline secrets), revisit.
- **Coalescing window 10 min** — a guess. Configurable; tune after observing real usage.
- **Digest-empty weekly rollup** — not shipped. If the user ever wants a "we looked, here's a week's worth of nothing" heartbeat, promote `alert_digest_empty_skip=false` to per-kid cadence.
- **`MatchResult.updated` alerts** — currently silent (only `.new` fires). If "score climbed significantly" becomes useful, add a threshold-delta check in the matcher and a new alert type.
- **HTTPS for local ntfy** — when users point at self-hosted ntfy, assume HTTPS or plain HTTP per their `base_url`. No cert pinning.

## 9. What Phase 4 does NOT touch

- Home Assistant channel (removed from roadmap)
- Calendar view / dashboard / Web UI (Phase 5)
- SMS, Slack, Discord
- Per-user alert preferences (household-level is sufficient for this project's single-family target)
- Email attachments
- Async job queue
