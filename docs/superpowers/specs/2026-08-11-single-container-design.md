# Single-Container Deployment — Design

**Status:** approved (brainstormed 2026-08-11)

**Goal:** Ship `yas` as one container running `python -m yas all`, instead of two containers (`yas-api`, `yas-worker`) built from the same image with different `command:` values.

**Motivation (user-stated):** deployment simplicity — one service for a self-hoster to run, understand, and upgrade — and resource footprint: one Python interpreter, one SQLAlchemy engine and pool, one set of httpx / Playwright / Anthropic / Nominatim clients instead of two.

**Explicit non-goal:** removing `docker-compose.macos.yml`. See "Deliberately unresolved".

---

## Context

"Single image" is already true. `docker-compose.yml` references one image (`ghcr.io/owine/youth-activity-scheduler:latest`) through an `x-image` YAML anchor and runs it twice with different commands. This change is purely about container *count*.

The collapsed process model also already exists. `src/yas/__main__.py::_run_all` constructs one `DefaultFetcher`, one `AnthropicClient`, and one `NominatimClient`, passes them to both `create_app` and `run_worker`, and runs the worker as an `asyncio` task alongside uvicorn. `CLAUDE.md` documents `all` as the dev mode.

There is precedent: the `yas-migrate` one-shot service was eliminated in #116 by moving `upgrade_to_head()` into every CLI mode's startup path.

## Architecture

### 1. Fail-fast supervision in `_run_all`

This is the only source change, and it is a prerequisite rather than a nicety.

Today `_run_all` does:

```python
worker_task = asyncio.create_task(run_worker(...))
try:
    await server.serve()
finally:
    worker_task.cancel()
```

Nothing observes `worker_task` while the server runs. If a worker loop raises, the exception sits unretrieved until shutdown; the API keeps serving, and the only symptom is `/readyz` reporting `heartbeat_fresh: false`. In the two-container layout this cannot happen — a worker crash exits its container and `restart: unless-stopped` revives it. Collapsing to one container without this fix would trade a self-healing crawler for a silently dead one.

Replace with a `TaskGroup`:

```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(server.serve())
    tg.create_task(run_worker(engine, settings, fetcher=fetcher, llm=llm, geocoder=geocoder))
```

Either task raising cancels the other; the exception propagates out of `main()`, the process exits non-zero, and Docker's restart policy restarts the container. Failure semantics then match today's per-container behavior, at the cost of the API blipping for a few seconds on a worker fault. This is the accepted trade: chosen over in-process retry-with-backoff because it is roughly fifteen lines instead of a new state machine, and because "the container restarts" is a model an operator already holds.

`run_worker` already runs its seven loops inside a single `TaskGroup`, so this composes with existing behavior rather than layering a second supervision scheme.

### 2. `docker-compose.yml` — one service

```yaml
services:
  yas:
    image: ghcr.io/owine/youth-activity-scheduler:latest
    command: ["python", "-m", "yas", "all"]
    env_file: .env
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

The `x-image` anchor goes away — an anchor for a single service is noise.

Both `healthcheck:` blocks also go away. `yas-worker` needed `healthcheck: disable: true` only because it runs no HTTP server and would fail the inherited probe forever; `yas-api` restated the Dockerfile's probe verbatim. One service that serves HTTP inherits the Dockerfile `HEALTHCHECK` correctly, so neither override has a reason to exist.

### 3. `docker-compose.split.yml` — standalone, not an overlay

The two-container layout is retained as an opt-in for crash-domain isolation or independent worker scaling.

It must be a **standalone file used instead of the base**, not layered on top:

```bash
docker compose -f docker-compose.split.yml up -d
```

Compose overlays can add and modify services but cannot remove them, so a layered override could not turn off the base `yas` service. The failure would also be quiet rather than loud: `docker-compose.macos.yml` currently overrides `yas-worker` and `yas-api`, and layering it onto a base that no longer defines those services *adds two phantom services* rather than erroring.

Rejected alternatives: `deploy.replicas: 0` on the base service (relies on obscure non-swarm behavior), and putting every service behind a profile (breaks bare `docker compose up -d`, which is the exact simplicity this change buys). The cost of standalone is ~25 duplicated lines in the configuration that is tested least — acceptable in exchange for being unambiguous.

Because `docker-compose.macos.yml` will target the `yas` service after this change, the split file carries its own macOS story. It should use a named volume directly rather than depending on an overlay that no longer fits it.

### 4. Script and doc updates

`scripts/e2e_phase5a.sh`, `smoke_phase3.sh`, `smoke_phase3_5.sh`, and `smoke_phase4.sh` all reference the old service names in two ways: `up -d yas-worker yas-api` and `exec -T yas-api …`. Both become `yas`.

`README.md` (Quickstart, "Local dev on macOS", the `sqlite3` inspection example) and `CLAUDE.md` (the process-model section, the compose commands, and the `docker-compose.dev.yml` gotcha added in #333) need the new service name and the upgrade note below.

## Operator-facing risks

### Orphaned containers on upgrade — the sharpest edge

An existing deployment is running `youth-activity-scheduler-yas-api-1` and `-yas-worker-1`. After pulling this change, `docker compose up -d` creates the new `yas` container and leaves both old ones running, because compose only reconciles services it still knows about. The README upgrade instructions must therefore say:

```bash
docker compose up -d --remove-orphans
```

**Rehearsed 2026-08-11, and the outcome is milder than first assumed.** The initial draft of this spec claimed the result was three processes writing one SQLite file. It is not. Compose prints an explicit `Found orphan containers` warning, and the new container then *fails to start*:

```
Bind for 0.0.0.0:8080 failed: port is already allocated
```

because the old `yas-api` still holds the port. The operator is left with the old pair still serving and a failed deploy — loud and safe, not silent and data-adjacent. Re-running with `--remove-orphans` removes both old containers and leaves exactly one.

The port collision is what provides that protection, so it does not hold for a deployment that publishes the API on a different port than the old stack did. The flag is still the right instruction unconditionally; the warning text just should not claim data corruption.

The compose project name is unchanged, so the `youth-activity-scheduler_yas-data` named volume and the `./data` bind mount both carry over untouched.

### Sequencing against PR #333

PR #333 (docker image size reduction) modifies all four scripts this change also touches, including adding `scripts/lib.sh` and the `assert_local_build` guard. It must land first; otherwise the two changes conflict head-on in the same regions.

## Deliberately unresolved

**Whether `docker-compose.macos.yml` can be deleted.** It exists because Docker Desktop's VirtioFS does not fully honor SQLite's locking primitives, producing sporadic `disk I/O error` under "concurrent api ↔ worker access". One container removes cross-*process* contention, which is suggestive — but SQLAlchemy's async engine maintains a **connection pool**, so a single process still holds several connections to the same file. That may be sufficient to keep triggering the bug.

No claim either way belongs in this change. The overlay stays, retargeted to the `yas` service. "Can macos.yml be deleted" is a separate follow-up requiring an actual reproduction on a bind mount, not an inference from architecture.

## Testing

- `pytest` — unaffected by compose changes; the `_run_all` `TaskGroup` change wants a unit test asserting that a worker exception propagates out rather than being swallowed.
- `./scripts/e2e_phase5a.sh` — the real regression net. Exercises migrations, the API, the seeded fixtures, and the Playwright specs against a live single container.
- Manual: bring up the old two-container layout, then upgrade in place and confirm `--remove-orphans` is required and sufficient.
- `docker compose -f docker-compose.split.yml config` — confirm the standalone file resolves, and that the base + `macos.yml` chain still resolves to exactly one service.

## Files

**New:** `docker-compose.split.yml`, `docs/superpowers/specs/2026-08-11-single-container-design.md`

**Modified:** `src/yas/__main__.py`, `docker-compose.yml`, `docker-compose.dev.yml`, `docker-compose.macos.yml`, `scripts/lib.sh`, `scripts/e2e_phase5a.sh`, `scripts/smoke_phase3.sh`, `scripts/smoke_phase3_5.sh`, `scripts/smoke_phase4.sh`, `README.md`, `CLAUDE.md`

`docker-compose.dev.yml` is load-bearing and easy to miss: it applies `build: .` to `yas-worker` and `yas-api` through an `x-build` anchor. Renaming the base service without renaming it there leaves the real `yas` service with no `build:` while compose *adds* two phantom services that do have one. `assert_local_build` (tightened in #333 to check named services individually) catches this, which is the reason that tightening had to land first.

**Untouched:** the `api` / `worker` / `migrate` CLI modes. CI's `e2e` job runs `python -m yas api` with `YAS_STATIC_DIR` (`.github/workflows/ci.yml:140`), so `api` mode has a live consumer and is not deprecated by this change.
