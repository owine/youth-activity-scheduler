# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`yas` — a self-hosted crawler + matcher + alerter for youth activity / sports / enrichment
websites. It crawls registered site pages, extracts program offerings with Claude Haiku,
matches them against kid profiles, and alerts via email / ntfy / Pushover / Home Assistant.
Python 3.14 backend (FastAPI + SQLAlchemy async + SQLite), React 19 SPA frontend.

## Commands

### Backend (repo root, `uv`)

```bash
uv sync                        # install (dev deps included by default)
uv run pytest                  # full suite (asyncio_mode=auto; no @pytest.mark.asyncio needed)
uv run pytest tests/unit/test_gates.py::test_age_upper_bound_inclusive   # single test
uv run pytest -k watchlist     # by keyword
uv run ruff check .            # lint (line-length 100, E/F/W/I/B/UP/SIM/RUF)
uv run ruff format .           # format
uv run mypy src                # typecheck — strict, src/yas only
uv run alembic upgrade head    # apply migrations manually
uv run alembic revision -m "..."   # new migration (versions are named NNNN_slug.py)
```

`pytest` addopts include `--cov=yas --cov-report=term-missing`, so single-test runs print a
misleadingly low coverage table. That's expected, not a failure.

Tests read settings through `pydantic-settings`, which loads `.env`. `YAS_ANTHROPIC_API_KEY`
must be set (CI uses `sk-test-nonop` — no real key is needed; LLM calls are faked).

### Frontend (`frontend/`, `pnpm`)

```bash
corepack enable && pnpm install   # Node pinned by .nvmrc (24.18.0), pnpm by packageManager
pnpm run dev                      # Vite on :5173, proxies /api /healthz /readyz to :8080
pnpm run typecheck                # tsc --noEmit
pnpm run lint                     # eslint, --max-warnings 0
pnpm run format:check             # prettier
pnpm run test                     # vitest run (happy-dom + MSW)
pnpm vitest run src/lib/format.test.ts    # single test file
pnpm run build                    # tsc -b && vite build → dist/
pnpm exec playwright test         # e2e; needs a live API at PLAYWRIGHT_BASE_URL (default :8080)
```

### Running the app

```bash
uv run python -m yas all      # api + worker in one process — what the image ships
uv run python -m yas api      # FastAPI only
uv run python -m yas worker   # background loops only
uv run python -m yas migrate  # apply schema and exit

docker compose up -d          # one `yas` container; pulls ghcr.io/owine/…:latest
./scripts/e2e_phase5a.sh      # full docker e2e: build, seed, playwright, teardown
```

The shipped compose runs **one container** in `all` mode. `api` and `worker` modes remain: CI's
`e2e` job runs `python -m yas api` with `YAS_STATIC_DIR`, and `docker-compose.split.yml` uses
both for the opt-in two-container layout. That split file is **standalone — used instead of
`docker-compose.yml`, not layered onto it**, because compose can add and modify services but
cannot remove one, so an overlay could not switch off `yas`.

On macOS, layer in `-f docker-compose.macos.yml` — VirtioFS bind mounts break SQLite locking
and produce sporadic `disk I/O error`; the overlay swaps `./data` for a named volume. One
container removes cross-*process* contention but SQLAlchemy still pools several connections to
the same file, so the overlay stays until someone reproduces its absence.

`docker-compose.yml` targets prod: it pins `image: ghcr.io/...:latest` with **no `build:`**. So
any script that must exercise local source has to layer in `-f docker-compose.dev.yml` (last —
it overrides `image:` with `build: .`). Omit it and `docker compose build` prints
`No services to build` and exits 0, `up` pulls the published image, and the run silently
validates GHCR instead of your working tree. `scripts/lib.sh::assert_local_build` asserts a
`build:` on each **named service** for exactly this reason — a whole-config check would pass on
a phantom service that a stale override added, since compose adds services an override names
but the base lacks rather than erroring.

`scripts/smoke_phase2.sh` is the exception: it reads `data/activities.db` from the host via
`sqlite3`, so it needs the base file's `./data` bind mount and cannot use `compose_cmd()` (which
would layer in `macos.yml` on Darwin and swap that for a named volume). It consequently still
runs against the published image.

## Architecture

### Process model

`src/yas/__main__.py` is the single entrypoint with four modes. **Every mode calls
`upgrade_to_head()` before opening the engine** — migrations are programmatic, not a separate
container (`docker-compose.yml` has no migrate service). `alembic/env.py` takes the URL from
`config.attributes["sqlalchemy.url"]` when present, falling back to `Settings`.

In `all` mode one `Fetcher`, one `AnthropicClient`, and one `NominatimClient` are constructed
at startup and shared between the API and the worker. `api` mode builds its own LLM + geocoder
because `/discover` and household geocoding need them.

`all` mode runs uvicorn and the worker as siblings in `_supervise`'s `TaskGroup`, so **either
one failing cancels the other and exits the process non-zero** — `restart: unless-stopped` then
does what a per-container crash used to do. This is load-bearing now that both run in one
container: a bare `create_task` would leave a dead worker unobserved behind a healthy-looking
API, detectable only as `/readyz` reporting `heartbeat_fresh: false`.

`worker/runner.py` runs every background loop as a task in one `asyncio.TaskGroup`: heartbeat,
crawl scheduler, daily sweep, geocode enricher, alert delivery, digest, detector. Each is
individually gated by a `Settings` flag.

### Crawl pipeline

`crawl/scheduler.py` selects pages whose `next_check_at` has passed, then `crawl/pipeline.py`
runs the stages:

1. `fetcher.py` — httpx, or Playwright when `site.needs_browser`. `robots.txt` is ignored
   unless `site.crawl_hints.respect_robots` is true.
2. `change_detector.py` — `content_hash(normalize(html))`. Matching hash short-circuits the
   whole run (no LLM spend).
3. `extractor.py` — checks `extraction_cache` by content hash first; on miss calls the LLM
   via structured tool use (`llm/client.py` prompts Claude to call a `report_offerings` tool,
   validates with `llm/schemas.py`, and computes per-call cost from token usage).
4. `reconciler.py` — diffs extracted offerings against active DB rows keyed by
   `(normalized_name, start_date)`, classifying new / updated / withdrawn / unchanged.
5. Rematch + alert enqueue, inside the same session as the reconcile.

Failures increment `page.consecutive_failures` and back off exponentially (capped at 4×
`site.default_cadence_s`); the third consecutive failure fires a `crawl_failed` alert.

### Matching

`matching/gates.py`, `scoring.py`, `watchlist.py`, `soft_conflicts.py`, `aliases.py` are
**pure sync functions over already-loaded ORM rows — no I/O, no session**. `matching/matcher.py`
is the only async part, and it hoists per-kid queries (blocks, watchlist, enrollments) out of
the per-offering loop.

Five hard gates must all pass for a match: age, distance, interests, offering active/not-ended,
no unavailability conflict. **Watchlist hits bypass every gate** — they represent manually
verified programs. Score is a weighted blend (availability .4, distance .2, registration .2,
price .1, freshness .1) stored alongside a `reasons` JSON blob the UI renders as chips.

Distance normally uses great-circle miles; when `YAS_DRIVE_TIME_ENABLED=true` the matcher
switches to OSRM drive minutes against `kid.max_drive_minutes`, cached in `drive_time_cache`.

Unavailability blocks are *materialized*, not computed on read: `unavailability/school_materializer.py`
turns a kid's school schedule into blocks, and `enrollment_materializer.py` does the same for
enrollments. The matcher filters out an enrollment-sourced block when evaluating the offering
that enrollment points at, so an enrolled kid keeps matching their own program.

### Alerts

Two independent code paths create alerts: `crawl/pipeline.py` (after a crawl tick) and
`matching/matcher.py::_upsert_match` (during the daily sweep). They converge because
`alerts/enqueuer.py::dedup_key_for()` derives a deterministic key per alert type and
`_upsert_alert` updates an existing *unsent* row rather than inserting a duplicate. When adding
an alert type, add its dedup rule there — the function raises on unknown types by design.

`alerts/routing.py` maps type → channels; `alerts/channels/` holds the notifier implementations;
`worker/delivery_loop.py` rebuilds notifiers **every tick** so household config changes take
effect within ~60s without a worker restart. Rate limiting lives in `alerts/rate_limit.py`.

Channel secrets can be inlined in the household JSON config or referenced by env-var name
(`password_env`, `api_token_env`, `auth_token_env`, `user_key_env`, `app_token_env`). A named
var that isn't set in the environment makes the channel silently fail to construct.

### Email rendering

`email/registry.py` maps each `AlertType` → `(builder, html template, txt template)`.
`tests/unit/test_email_registry.py` asserts completeness strictly — **a missing entry is a CI
failure, not a runtime fallback**. `AlertType.digest` is deliberately excluded; digests are
assembled by `worker/digest_loop.py` and rendered via `render_digest_payload`.

Rendered output is golden-tested against `tests/golden/email/` and `tests/golden/digest/`.
`tests/golden/_scenarios.py` seeds the DB for both the per-kind unit tests and the goldens, so
the two can't drift. Goldens use a frozen `GOLDEN_NOW`; changing a template means regenerating
the golden files.

### Web layer

`web/app.py` is a factory taking injected `engine` / `settings` / `fetcher` / `llm` / `geocoder`,
which is how tests swap in fakes. Routes live in `web/routes/`, one module per resource plus a
paired `*_schemas.py` for its Pydantic request/response models.

`web/spa_fallback.py` **must be installed last**. It mounts `/assets`, registers an
`/api/{path:path}` 404 guard so unknown API paths return JSON instead of `index.html`, then a
catch-all serving the SPA. Static root is `/app/static` in the image, overridable with
`YAS_STATIC_DIR` for local dev and CI.

### Frontend

TanStack Router (file-based routes in `src/routes/`, `routeTree.gen.ts` is generated — never
hand-edit, it's eslint-ignored) + TanStack Query. All server state goes through `lib/queries.ts`
(reads) and `lib/mutations.ts` (writes, several with optimistic updates + snapshot rollback);
`lib/api.ts` is the thin fetch wrapper that throws `ApiError`. Components are grouped by feature
under `src/components/<feature>/`, with shadcn-style primitives in `src/components/ui/`.
Tailwind v4 (no config file — CSS-first in `src/styles/globals.css`). Unit tests are colocated
`*.test.tsx` files using vitest + Testing Library + MSW (`src/test/handlers.ts`); Playwright
specs live in `e2e/` and run against a real API.

## Conventions

- Database sessions always go through `db/session.py::session_scope` (commit on success,
  rollback on error, `expire_on_commit=False`). SQLite connections get WAL, `foreign_keys=ON`,
  `synchronous=NORMAL`, and a 5s busy timeout.
- Timestamps are UTC-aware via `db/models/_types.py::timestamp_column`. SQLite can hand back
  naive datetimes on read — normalize with `.replace(tzinfo=UTC)` before comparing (see
  `crawl/pipeline.py` around the registration-countdown check).
- Logging is structlog with dotted event names (`pipeline.alerts_enqueued`, `offering.new`)
  and keyword context, never f-strings.
- Enums are `StrEnum` in `db/models/_types.py`; models are one class per file, re-exported
  through `db/models/__init__.py`.
- Design docs go in `docs/superpowers/specs/`, implementation plans in
  `docs/superpowers/plans/`, both named `YYYY-MM-DD-slug.md`.

## Gotchas

- **TypeScript 6 and 7 run side-by-side on purpose.** `typescript` is aliased to
  `@typescript/typescript6` (so anything doing a bare `require("typescript")` — typescript-eslint,
  msw, vitest — gets a working JS API) while `@typescript/native` is aliased to real
  `typescript@7`, which puts the v7 `tsc` on the bin path for `build`. Don't collapse this until
  typescript-eslint supports TS 7.1+.
- **pnpm 11 reads only auth and registry settings from `.npmrc`** — every other key is silently
  ignored, no warning. All project config belongs in `frontend/pnpm-workspace.yaml`; the repo
  has no `.npmrc` at all, and re-adding one for settings would be dead config.
- Supply-chain hardening is split deliberately. The **release-age soak lives in the shared
  Renovate preset** (`github>owine/renovate-config`): 3 days minor/patch, 7 days majors, 0 for
  CVEs and lockfile maintenance. Do **not** add a second pnpm-side soak (`minimumReleaseAge`) —
  the two gates are adversarial, not additive. Renovate's decides when a PR opens, pnpm's would
  decide when a lockfile can be written; whenever pnpm's is stricter, Renovate bumps
  `package.json` to a version pnpm then refuses to resolve, `renovate/artifacts` fails, the
  lockfile goes stale, and `pnpm install --frozen-lockfile` rejects the PR. The 0-day CVE tier
  fails hardest. **Exact pinning** is enforced by `saveExact` in `frontend/pnpm-workspace.yaml`
  plus the preset's `rangeStrategy: pin`; backend deps are pinned exactly too.
- `frontend/pnpm-workspace.yaml` uses pnpm v11's single `allowBuilds` key, not the older
  `onlyBuiltDependencies` family, and camelCase settings (`preferFrozenLockfile`, `saveExact`,
  `audit.level`) rather than the kebab-case `.npmrc` spellings.
- CI's `ci-pass` job is a stable-named aggregator over all other jobs and treats `skipped` as
  success — docs-only PRs skip `docker-build` via the `changes` paths-filter and must still merge.
- The HTTP API is unauthenticated by design and intended for trusted networks only.
