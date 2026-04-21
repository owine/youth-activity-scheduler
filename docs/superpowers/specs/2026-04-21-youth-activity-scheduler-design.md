# Youth Activity Scheduler — Design Spec

**Status:** Draft — awaiting user review
**Date:** 2026-04-21
**Target repo:** `youth-activity-scheduler/` (single-user, self-hosted)

---

## 1. Purpose & scope

A self-hosted app that crawls a curated list of youth activity / sports / enrichment websites, extracts upcoming program offerings into a structured database, matches them against per-kid profiles, and alerts the user when:

- A new schedule or catalog is posted
- A relevant offering appears (matched to a specific kid)
- A specific offering on the user's watchlist is posted
- Registration is about to open, or has opened, for any of the above

Scope is deliberately single-household, single-user. No multi-tenant, no public sharing.

### In scope (v1)

- Curated list of 5–20 target sites
- Structured extraction with adapter-per-site + LLM fallback
- Page-diff fallback for stubborn/unstructured sites
- Per-kid profiles (DOB, interests, availability, distance) and watchlists
- Multi-channel alerting (email, Home Assistant, ntfy push) with urgency tiers
- Daily per-kid digest email
- **Time-gating against school schedules and existing commitments** (recurring unavailability)
- **Enrollment tracking** — marking an offering as enrolled blocks its time slot for future matching
- **Calendar view** — per-kid and combined week/month calendar over offerings, enrollments, and unavailability
- Self-hosted web UI (kids, sites, offerings browser, calendar, alerts, settings)
- Docker Compose deployment (API + worker)

### Explicitly out of scope (v1)

- Authenticated crawling (login-required sites)
- Multi-user / multi-household / public sharing
- Mobile app (responsive web is sufficient)
- `.ics` calendar export
- Analytics dashboards and historical charts
- Automated registration / booking

---

## 2. Architectural approach

Tiered, LLM-cached crawl pipeline:

- Every site has an **adapter**. Default is `llm` (no code required to onboard a site).
- Hand-written Python adapters are added selectively when LLM extraction is expensive, flaky, or incorrect for a given site.
- LLM extraction is **cached by content hash** of the fetched page — identical content never re-calls the LLM.
- LLM extraction uses a strict Pydantic schema for the output; validation failures retry once on a stronger model before giving up.

This lets new sites be onboarded in seconds and optimized to hand-written code only where it matters.

---

## 3. Data model (SQLite via SQLAlchemy 2.0)

SQLite is the right fit for this workload: one user, ~20 sites, low hundreds of writes per day. WAL mode handles the single-writer-worker + reader-API case cleanly. Data access goes through SQLAlchemy so a future migration to Postgres is a connection-string change.

### Tables

**`kids`** — `id, name, dob, interests (json), availability (json), max_distance_mi (nullable), alert_score_threshold (default 0.6), alert_on (json), school_weekdays (json, default [mon..fri]), school_time_start (nullable), school_time_end (nullable), school_year_ranges (json, default []), school_holidays (json, default []), notes, active`

- DOB (not age) is stored; current age is computed at match time.
- `availability` is a weekly grid of day × time-range windows — "when I'd like to do things."
- `max_distance_mi` nullable → falls back to household default.
- `alert_on` is `{ new_match, schedule_posted, reg_opens, watchlist_hit }` toggles.
- `school_year_ranges` is a list of `{ start, end }` date ranges (so you can split fall + spring semesters, or accommodate a kid who starts school mid-year).
- `school_holidays` is a list of individual dates (Thanksgiving week, winter break, MLK day, etc.) — no-school exceptions within the school year ranges.
- School fields together produce a computed set of school unavailability blocks via a materializer; see §3.x below. The raw fields stay on `kids` because they're the source of truth and rarely changed.

**`locations`** — `id, name, address, lat, lon`
Used for home address and for any offering with a parseable location.

**`sites`** — `id, name, base_url, adapter (str), needs_browser (bool), crawl_hints (json), active, default_cadence, muted_until (nullable), created_at`

- `adapter = "llm"` or `"<module_name>"` matching a file under `adapters/`.
- `crawl_hints`: free-form JSON (tracked page URLs, selectors, notes).
- `muted_until`: suppresses alerts but not crawling.

**`pages`** — `id, site_id, url, kind, content_hash, last_fetched, last_changed, next_check_at, consecutive_failures`

- `kind`: `schedule | registration | list | other`
- Change detection compares `content_hash` after HTML normalization.

**`offerings`** — `id, site_id, page_id, name, description, age_min, age_max, program_type (enum tag), start_date, end_date, days_of_week (json), time_start, time_end, location_id, price_cents, registration_opens_at, registration_url, raw_json, first_seen, last_seen, status (active | ended | withdrawn), muted_until (nullable)`

- `program_type` is drawn from a fixed vocabulary emitted by the LLM extractor (`soccer`, `swim`, `martial_arts`, `art`, `music`, `stem`, `dance`, `gym`, `multisport`, `outdoor`, `academic`, `camp_general`).
- `raw_json` preserves the full extraction so reprocessing is possible without re-crawl.

**`extraction_cache`** — `content_hash (pk), extracted_json, llm_model, cost_usd, extracted_at`
The cost killer — identical content bypasses the LLM entirely.

**`matches`** — `kid_id, offering_id, score, reasons (json), computed_at` (composite pk)
Precomputed, rebuilt on offering or kid changes.

**`watchlist_entries`** — `id, kid_id, site_id (nullable), pattern, priority (high | normal), notes, active, created_at`

- `pattern` is case-insensitive substring or glob (no regex).
- `site_id = NULL` → watches across all sites.

**`unavailability_blocks`** — recurring or one-off times a kid is unavailable.
`id, kid_id, source (manual | school | enrollment | custom), label, days_of_week (json), time_start, time_end, date_start (nullable), date_end (nullable), source_enrollment_id (nullable), active, created_at`

- **`source = school`** rows are derived from the kid's school fields and are rewritten whenever those fields change. They are never edited by hand — the derivation is idempotent. One row per contiguous school-year range, representing "weekdays `school_weekdays` from `school_time_start` to `school_time_end`." `school_holidays` dates are stored on the kid, not as blocks; the matching layer subtracts them when checking a specific date.
- **`source = enrollment`** rows are auto-created/updated/deleted as `enrollments` rows change (one block per offering occurrence pattern). `source_enrollment_id` is the FK back.
- **`source = manual | custom`** rows are user-created for ad-hoc commitments (grandma visit, family trip — for custom you can set `date_start/date_end` without a recurring pattern).

**`enrollments`** — a record that the household has committed to an offering.
`id, kid_id, offering_id, status (interested | enrolled | waitlisted | completed | cancelled), enrolled_at, notes, created_at`

- Only `status = enrolled` produces `source = enrollment` unavailability blocks. `interested` is purely a bookmark and does not affect matching.
- `status = waitlisted` does not block time either (the kid isn't actually committed yet).
- Transitioning to `cancelled` or `completed` deactivates the linked unavailability block (`active = false`).

**`alerts`** — `id, type (enum), kid_id (nullable), offering_id (nullable), site_id (nullable), channels (json), scheduled_for, sent_at (nullable), skipped (bool, default false), dedup_key, payload_json`

- Types: `watchlist_hit, new_match, reg_opens_24h, reg_opens_1h, reg_opens_now, schedule_posted, crawl_failed, digest`
- Unsent rows with the same `dedup_key` are updated rather than duplicated.
- `dedup_key` format: `{type}:{kid_id or "-"}:{offering_id or site_id or "-"}`. Scheduled alerts (`reg_opens_*`) also include the `scheduled_for` bucket so countdown rows don't collide with each other.

**`alert_routing`** — `type (pk), channels (json), enabled` — table-driven routing, editable via UI.

**`crawl_runs`** — `id, site_id, started_at, finished_at, status, pages_fetched, changes_detected, llm_calls, llm_cost_usd, error_text`

**`household_settings`** — single-row table: `home_location_id, default_max_distance_mi, digest_time, quiet_hours_start, quiet_hours_end, daily_llm_cost_cap_usd, smtp_config_json, ha_config_json, ntfy_config_json`

### Design choices worth flagging

- **No global dedup across sites.** Same-named program at two orgs = two rows.
- **Matches are precomputed**, not query-time joins. Alerting becomes "did new match rows appear?"
- **Distance is a hard gate**, fail-open if geocoding fails (with a `reasons` flag noting unknown location).
- **Mute vs. pause**: muted sites/offerings still crawl and populate UI but don't alert; paused sites don't crawl at all.

---

## 4. Crawl pipeline

Pipeline stages (each independently testable):

```
Scheduler → Fetcher → Change Detector → Extractor → Reconciler → Alert Enqueuer
```

### 4.1 Scheduler

Single async worker. Picks `pages` with `next_check_at <= now`, respects per-site concurrency of 1.

**Adaptive cadence:**

- Baseline: `site.default_cadence` (default 6h)
- Any offering on the site with `registration_opens_at` within 24h → page cadence = 10 min
- Within 1h → 2 min
- After registration opens → back to baseline
- Sites with any active watchlist entry get a tighter baseline (default hourly)

### 4.2 Fetcher

`httpx` by default; routes through Playwright when `site.needs_browser = true`. Polite UA identifying the crawler + contact URL. Respects `robots.txt` by default (per-site override in `crawl_hints`). Exponential backoff on transient errors. Returns `(status, html, final_url)`.

### 4.3 Change detector

Normalizes HTML (strips `<script>`, `<style>`, nav, footer, timestamps), SHA-256s the result, compares to `pages.content_hash`. Equal → update `last_fetched` and short-circuit. Most crawls end here.

### 4.4 Extractor

Tiered:

1. Look up `site.adapter`. If not `"llm"`, dispatch to `adapters/<name>.py` which returns `list[Offering]`.
2. Otherwise, LLM extraction:
   a. Check `extraction_cache` by content hash — cache hit short-circuits.
   b. Call Claude Haiku with cleaned HTML + Pydantic schema → structured JSON.
   c. Validate. On validation failure, retry once on Sonnet.
   d. Persist to `extraction_cache`.

### 4.5 Reconciler

Compares fresh extracted offerings against current `offerings` rows for the page:

- Match key: `(normalized_name, start_date)` where `normalized_name = lowercase → strip punctuation → collapse whitespace → trim`. This stops minor title edits from producing spurious withdrawn/new churn.
- **New** → insert, set `first_seen = now`.
- **Updated** → update in place, preserve `first_seen`.
- **Gone** → `status = withdrawn`.

Emits events: `offering.new`, `offering.updated`, `offering.withdrawn`, `page.changed`.

### 4.6 Alert enqueuer

Reacts to reconciler events:

- `offering.new` → recompute matches for all active kids; for each match above threshold or matching a watchlist entry, insert an `alerts` row.
- `offering.updated` with a newly-set `registration_opens_at` → insert three `alerts` rows with `scheduled_for` at T−24h, T−1h, T.
- `offering.updated` with `registration_opens_at` changed → delete prior unsent `reg_opens_*` rows for the offering, insert new ones.
- `page.changed` with no offerings extracted (pure diff site) → insert `schedule_posted` alert with an LLM-generated summary of what changed.

### 4.7 Alert delivery (separate worker loop)

Polls every 60s for `alerts` where `scheduled_for <= now AND sent_at IS NULL AND skipped = false`.

- **Grace window on startup:** alerts past due by less than 24h fire once; older ones are marked `skipped = true`.
- **Coalescing:** normal-urgency alerts (`new_match`, `reg_opens_24h`) buffer 10 min. Multiple alerts with the same coalescing key `(kid_id, type)` merge into one message.
- **Immediate urgency** (`reg_opens_now`, `reg_opens_1h`, `watchlist_hit`) send immediately.
- **`schedule_posted`** never sends standalone — rolls into the digest.
- **Per-kid cap:** max 5 pushes/hour **across all push channels combined** (HA + ntfy counted together; email is uncapped). Excess coalesces to "N new alerts — see dashboard."
- **Quiet hours** suppress pushes but not emails.

### 4.8 Error handling

- Every failure writes `crawl_runs.error_text` and bumps `pages.consecutive_failures`.
- After 3 consecutive failures on a site, a one-time `crawl_failed` alert fires and the site's cadence extends to daily until manually reset.
- No silent failures — channel delivery errors surface in the next daily digest.

---

## 5. Matching & filtering

### 5.1 Hard gates (all must pass)

- Age fit: kid's current age ∈ `[age_min, age_max]` (tolerance default 0)
- Distance fit: offering's location within `max_distance_mi` (fail-open if location unknown)
- Interest tag overlap: at least one of kid's `interests` equals offering's `program_type`, OR appears as a case-insensitive substring (after lowercasing + whitespace normalization) in `name` or `description`. Per-interest aliases (e.g., `soccer → [kickers, futbol]`) live in a small config map.
- Offering not ended and `status = active`
- **No-conflict with unavailability:** for every occurrence of the offering on each date in `[start_date, end_date]` matching `days_of_week`, none of the offering's `(date, time_start, time_end)` windows intersect an active `unavailability_blocks` row for the kid on that date (after subtracting `school_holidays` from `source = school` blocks). Fail-open if the offering lacks any of start_date, end_date, days_of_week, time_start, time_end (record a `reasons` flag "schedule partial, unable to verify no-conflict").

Failing any gate → no `matches` row.

### 5.2 Soft-signal score (0–1, weighted sum)

| Signal | Weight | Notes |
|---|---|---|
| Availability fit | 0.4 | % overlap of offering day/time with kid availability windows |
| Distance | 0.2 | Scaled against `max_distance_mi`: full credit ≤ 30% of cap, linear decay to 0 at the cap. Avoids flat scores when the cap is >15mi. |
| Price | 0.1 | Optional per-kid `max_price`; linear decay to 0 at 2× max |
| Registration timing | 0.2 | Full credit if registration open or opens soon; 0 if closed |
| Freshness | 0.1 | Small boost for recently added offerings |

`reasons` JSON stores per-signal contributions for UI explainability.

### 5.3 Watchlist

Watchlist entries bypass the score threshold (alert regardless of score) but still respect hard gates. Per-entry `ignore_hard_gates` flag exists but is off by default. Watchlist hits generate `watchlist_hit` alerts, routed separately from `new_match`.

### 5.4 Re-match triggers

- New or updated offering → re-match against all active kids
- Kid profile change → re-match kid against all active offerings
- **Unavailability block change** (add/edit/delete, including school-derived rewrite or enrollment status change) → re-match that kid against all active offerings
- **Enrollment transition to/from `enrolled`** → re-derive linked block, then re-match that kid
- Nightly 3am sweep (catches kids aging into a new range, and handles date-range effects of school-year boundaries / holidays)

---

## 6. Alerting

### 6.1 Channel adapters

All implement a `Notifier` protocol with `send(alert) -> SendResult`. Three in v1:

- **Email** (SMTP)
- **Home Assistant** (`POST /api/services/notify/<service>` with long-lived token)
- **ntfy** (HTTP POST, simplest self-hosted push)

Adding a channel = one new class. Pushover/Gotify deferred.

### 6.2 Default routing

| Type | Channels |
|---|---|
| `watchlist_hit` | push + email |
| `new_match` | email |
| `reg_opens_24h` | email |
| `reg_opens_1h` | push |
| `reg_opens_now` | push + HA + email |
| `schedule_posted` | digest only |
| `crawl_failed` | email |
| `digest` | email |

Editable via UI through `alert_routing` table.

### 6.3 Digest

One email **per active kid** (N emails for an N-kid household, not a combined household digest — parents can skim per-kid faster than per-household). Default 7am daily. Structure:

- Top-line: LLM-generated summary sentence
- New matches section
- Starting soon (14-day horizon)
- Registration calendar (upcoming opens)
- Silent-failure notes (any failed channel sends in the prior 24h)

Body is templated; only the top-line uses the LLM to keep it fast and cheap.

### 6.4 Cost caps

- Daily LLM spend cap (default $1/day, configurable). Hard stop + log on breach; scheduler pauses LLM extraction until next day.

---

## 7. Web UI

**Stack:** FastAPI + HTMX + Tailwind + Jinja2 templates. No JS build step. React/Alpine islands allowed for individual interactive components if needed.

**Auth:** none by default; binds to localhost. Optional HTTP basic auth via reverse proxy for remote access.

### Pages

1. **Dashboard** — counts, event feed, upcoming registration calendar, recent watchlist hits
2. **Offerings browser** — filters (kid, tag, day, time, price, distance, registration status, site), sort (match score default, date, opens-soon, newest), match-reason chips on each card, actions (add to watchlist, mute offering, open source, **mark interested / enrolled**)
3. **Calendar** — week and month views. Toggles per kid or combined (colored per kid). Renders `offerings` (matched + watchlist hits), `enrollments` (solid blocks), and `unavailability_blocks` (dimmed blocks, labeled by source — school / custom / enrollment). Click any offering cell to view details or transition its enrollment status (interested → enrolled → completed / cancelled). This is the page that answers "what's our week actually look like?"
4. **Kids** — list + detail editing (DOB, interests, availability grid, distance cap, alert thresholds, watchlist manager, **school schedule** (weekdays + times + year ranges + holidays), **manual unavailability blocks**)
5. **Sites** — list with health status and 7-day LLM cost, detail with tracked pages, `crawl_runs` history, Crawl Now, Pause, Mute, raw HTML/JSON preview. **Add Site flow:** paste URL → auto-fetch preview → LLM first pass → confirm tracked pages
6. **Watchlist** — global cross-kid view with hit history
7. **Enrollments** — list of current and historical enrollments per kid, with status transitions and linked unavailability
8. **Alerts** — outbox with filters, resend, digest preview, quiet-hours setting
9. **Settings** — home location, channel configs, routing, digest time, cost cap, quiet hours

### Live updates

Server-Sent Events endpoint pushes crawl progress and new-alert events to the dashboard and per-site pages.

---

## 8. Project layout & ops

### 8.1 Repository structure

```
youth-activity-scheduler/
├── pyproject.toml                 # uv + ruff + pytest
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── alembic/
├── docs/superpowers/specs/
├── data/                          # mounted volume
├── src/yas/
│   ├── __main__.py                # `python -m yas {api|worker|all}`
│   ├── config.py                  # pydantic-settings
│   ├── db/
│   │   ├── models.py
│   │   ├── session.py
│   │   └── repositories/
│   ├── crawl/
│   │   ├── scheduler.py
│   │   ├── fetcher.py
│   │   ├── change_detector.py
│   │   ├── extractor.py
│   │   ├── reconciler.py
│   │   └── adapters/
│   │       ├── base.py
│   │       ├── llm.py
│   │       └── <sitename>.py
│   ├── matching/
│   │   ├── gates.py
│   │   ├── scoring.py
│   │   └── matcher.py
│   ├── alerts/
│   │   ├── enqueuer.py
│   │   ├── delivery.py
│   │   ├── digest.py
│   │   └── channels/{base,email,homeassistant,ntfy}.py
│   ├── llm/
│   │   ├── client.py              # Anthropic SDK wrapper w/ model tiering
│   │   ├── cost.py                # spend tracking + daily cap
│   │   └── schemas.py             # extraction Pydantic models
│   ├── geo/geocoder.py            # Nominatim client + cache
│   └── web/
│       ├── app.py
│       ├── routes/
│       ├── templates/
│       ├── static/
│       └── sse.py
└── tests/
    ├── unit/
    ├── integration/
    ├── fixtures/
    └── test_adapters/
```

### 8.2 Runtime topology

One Docker image; two Compose services (`yas-api`, `yas-worker`) sharing a `./data` volume.

- **`yas-api`** — FastAPI + uvicorn, serves UI and API.
- **`yas-worker`** — single process running scheduler, crawler, matcher, alert enqueuer, and alert delivery as async tasks.

Split process boundary keeps Playwright renders from blocking the web UI.

### 8.3 Configuration

- **Secrets** (Anthropic key, SMTP creds, HA token, ntfy auth) via env / `.env`
- **Household / channel / routing settings** in DB, editable via UI
- **Sites / kids / watchlist** entirely in DB

### 8.4 Tooling

- **uv** (deps), **ruff** (lint + format), **mypy --strict** on `src/`
- **pytest** + `pytest-asyncio` + `respx`
- **pre-commit** runs ruff + mypy
- **alembic** migrations from day 1

### 8.5 Observability

- Structured JSON logs via `structlog`
- `/healthz`, `/readyz` (DB + worker heartbeat)
- `crawl_runs` + `alerts` tables are the primary observability surface. Prometheus exporter deferred.

### 8.6 Backups

Nightly cron in the worker container runs `sqlite3 activities.db ".backup /data/backups/activities-$(date).db"`; retains 30 days. Restore path documented.

### 8.7 Testing strategy

- **Unit** — scoring, hard gates, change detector, reconciler, schema validation
- **Integration** — SQLite + respx + fake Anthropic responder, end-to-end pipeline over saved HTML fixtures
- **Adapter golden-file tests** — one `input.html` + `expected.json` per hand-written adapter
- **Nightly LLM regression (optional)** — replay 5 representative fixtures against the real API, diff output
- **CI** — GitHub Actions: lint, typecheck, unit + integration on push

### 8.8 Safety

- Unauthenticated public pages only
- `robots.txt` respected by default
- Identifying User-Agent with contact URL

### 8.9 Cost envelope (rough)

- LLM: Claude Haiku ~$1/M input tokens; ~5–20k tokens per uncached extraction; >90% expected cache hit rate at steady state → **$1–5/month**
- Hosting: existing server, negligible
- Geocoding: Nominatim, cached, free

---

## 9. Open questions / deferred decisions

- Whether to add Pushover/Gotify alongside ntfy
- `.ics` calendar export and school-calendar `.ics` *import* (both easy adds later on top of the blocks model)
- Whether any site on the initial list requires authenticated access (would flip scope)
- Whether home-location-based driving-time (vs. great-circle) distance matters enough to integrate a routing service
- Whether to surface "soft" conflicts (e.g., offering ends at 3:15pm, school ends at 3:00pm — too tight?) as warnings rather than hard-gate failures

## 10. Terminal state for v1

The app is "done" (v1) when:

- User can add a site via the UI in < 2 minutes (paste URL → confirm pages)
- Any new offering matching a kid's hard gates and score threshold produces an alert within 10 minutes of the site's next crawl
- Registration-opens countdown alerts fire correctly for a full T−24h / T−1h / T cycle on a real site
- A full 30-day uninterrupted run shows <$5 LLM spend and zero silent failures
- User can disable alerts from a specific site or offering with one click
- Setting a kid's school hours produces an `unavailability_blocks` row that causes activities inside those hours on school-year weekdays (minus holidays) to be filtered from matches
- Marking an offering as `enrolled` creates a linked unavailability block and immediately suppresses matches for conflicting offerings; marking it `cancelled` restores them
- Calendar page renders a week view containing offerings, enrollments, and unavailability for a single kid within 1s on a realistic dataset
