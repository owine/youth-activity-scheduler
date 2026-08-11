# Single-Container Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `yas` as one container running `python -m yas all`, replacing the two containers (`yas-api`, `yas-worker`) that today run the same image with different `command:` values.

**Architecture:** `_run_all` already shares one `Fetcher`/`AnthropicClient`/`NominatimClient` between the API and the worker, so the process model exists. Two changes make it deployable: a `TaskGroup` in `_run_all` so a worker fault exits the process (letting Docker's restart policy do what a per-container crash used to do), and a compose collapse from three service definitions to one. The two-container layout survives as a standalone opt-in file.

**Tech Stack:** Python 3.14, asyncio `TaskGroup`, uvicorn, Docker Compose v2, bash.

**Spec:** `docs/superpowers/specs/2026-08-11-single-container-design.md`

---

## Prerequisite

**PR #333 must be merged first.** It touches all four scripts this plan also edits, adds `scripts/lib.sh`, and — critically — tightens `assert_local_build` to check named services individually. That tightening is what catches the `docker-compose.dev.yml` rename hazard in Task 4. Starting before #333 lands means conflicts in every script *and* losing the guard that makes Task 4 safe.

Verify before starting:

```bash
git checkout main && git pull
git log --oneline -1          # expect the #333 squash commit
test -f scripts/lib.sh && grep -q 'config --format json' scripts/lib.sh && echo "PREREQ OK"
```

Then branch: `git checkout -b feat/single-container`.

---

## File Structure

**New files:**
- `docker-compose.split.yml` — standalone two-container layout (opt-in)
- `tests/unit/test_run_all_supervision.py` — supervision unit tests

**Modified files:**
- `src/yas/__main__.py` — extract `_supervise`, rewrite `_run_all` to use it
- `docker-compose.yml` — three service definitions → one `yas`
- `docker-compose.dev.yml` — `x-build` anchor retargeted to `yas`
- `docker-compose.macos.yml` — volume override retargeted to `yas`
- `scripts/lib.sh` — `compose_cmd` docstring, default service list
- `scripts/e2e_phase5a.sh`, `scripts/smoke_phase3.sh`, `scripts/smoke_phase3_5.sh`, `scripts/smoke_phase4.sh` — service names
- `README.md`, `CLAUDE.md` — quickstart, upgrade note, macOS section, service names

**Untouched:** the `api` / `worker` / `migrate` CLI modes. `.github/workflows/ci.yml:140` runs `python -m yas api`, so `api` mode has a live consumer.

---

## Task 1: Fail-fast supervision in `_run_all`

Today `_run_all` creates `worker_task` and then blocks on `await server.serve()`. Nothing observes the task while the server runs, so a worker exception sits unretrieved until shutdown — the API keeps serving and the only symptom is `/readyz` reporting `heartbeat_fresh: false`. In the two-container layout this cannot happen: a worker crash exits its container and `restart: unless-stopped` revives it. Collapsing to one container without this fix would trade a self-healing crawler for a silently dead one.

Rather than test `_run_all` directly (it boots uvicorn and blocks), extract the supervision into a helper that takes two awaitables. That is the actual unit of behavior, and it is testable in milliseconds.

**Files:**
- Modify: `src/yas/__main__.py`
- Test: `tests/unit/test_run_all_supervision.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_run_all_supervision.py`:

```python
import asyncio

import pytest

from yas.__main__ import _supervise


async def test_supervise_returns_when_both_finish():
    async def ok():
        return None

    await _supervise(ok(), ok())


async def test_worker_failure_propagates():
    async def server():
        await asyncio.sleep(3600)  # would outlive the worker

    async def worker():
        raise RuntimeError("worker exploded")

    with pytest.raises(ExceptionGroup) as ei:
        await _supervise(server(), worker())
    assert any(isinstance(e, RuntimeError) for e in ei.value.exceptions)


async def test_worker_failure_cancels_server():
    cancelled = asyncio.Event()

    async def server():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def worker():
        await asyncio.sleep(0)
        raise RuntimeError("worker exploded")

    with pytest.raises(ExceptionGroup):
        await _supervise(server(), worker())
    assert cancelled.is_set(), "server task must be cancelled when the worker dies"


async def test_server_failure_cancels_worker():
    cancelled = asyncio.Event()

    async def server():
        await asyncio.sleep(0)
        raise RuntimeError("server exploded")

    async def worker():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with pytest.raises(ExceptionGroup):
        await _supervise(server(), worker())
    assert cancelled.is_set(), "worker task must be cancelled when the server dies"
```

Note: `pytest.ini` sets `asyncio_mode = auto`, so no `@pytest.mark.asyncio` decorators are needed.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/unit/test_run_all_supervision.py -v
```

Expected: all four ERROR with `ImportError: cannot import name '_supervise'`.

- [ ] **Step 3: Add `_supervise` to `src/yas/__main__.py`**

Insert above `_run_all`:

```python
async def _supervise(server_coro, worker_coro) -> None:  # type: ignore[no-untyped-def]
    """Run the API server and the worker as siblings; either dying kills both.

    In the two-container layout a worker crash exited its container and the
    restart policy revived it. Collapsed into one container we need the same
    outcome, so a TaskGroup is used rather than a bare create_task: it cancels
    the surviving sibling and re-raises, the process exits non-zero, and Docker
    restarts the container. A bare create_task would leave a dead worker
    unobserved behind a healthy-looking API.
    """
    async with asyncio.TaskGroup() as tg:
        tg.create_task(server_coro)
        tg.create_task(worker_coro)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_run_all_supervision.py -v
```

Expected: 4 passed. (The coverage table will show a low percentage — `pytest` addopts include `--cov`; that is expected on a single-file run, not a failure.)

- [ ] **Step 5: Rewrite `_run_all` to use `_supervise`**

Replace the body of the inner `try:` in `_run_all`. Find:

```python
        server = uvicorn.Server(config)
        worker_task = asyncio.create_task(
            run_worker(engine, settings, fetcher=fetcher, llm=llm, geocoder=geocoder)
        )
        try:
            await server.serve()
        finally:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
```

Replace with:

```python
        server = uvicorn.Server(config)
        await _supervise(
            server.serve(),
            run_worker(engine, settings, fetcher=fetcher, llm=llm, geocoder=geocoder),
        )
```

The outer `try/finally` that calls `await fetcher.aclose()` and `await geocoder.aclose()` stays — shared clients still need closing on the way out.

- [ ] **Step 6: Remove the now-unused `contextlib` import if nothing else uses it**

```bash
grep -n contextlib src/yas/__main__.py
```

If the only remaining hit is the `import contextlib` line, delete it. Then:

```bash
uv run ruff check src/yas/__main__.py && uv run mypy src
```

Expected: both clean.

- [ ] **Step 7: Run the full suite**

```bash
uv run pytest
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/yas/__main__.py tests/unit/test_run_all_supervision.py
git commit -m "fix(all): exit the process when the worker dies

_run_all created worker_task then blocked on server.serve(), so a worker
exception went unobserved until shutdown — the API kept serving and the only
symptom was /readyz heartbeat_fresh: false. Harmless with a dedicated worker
container (crash -> restart policy), load-bearing once both run in one
container. TaskGroup cancels the sibling and re-raises so Docker restarts."
```

---

## Task 2: Collapse `docker-compose.yml` to one service

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Replace the whole file**

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

Three deletions worth understanding rather than pattern-matching:

- The `x-image` anchor existed to share one `image:` between two services. With one service it is indirection for nothing.
- `yas-worker`'s `healthcheck: disable: true` existed because that container runs no HTTP server, so the Dockerfile's inherited `curl /healthz` probe would fail forever and break `depends_on: service_healthy`. A single service that *does* serve HTTP inherits the probe correctly.
- `yas-api`'s `healthcheck:` block restated the Dockerfile's probe verbatim. Redundant.
- `depends_on` goes away with the service it pointed at.

- [ ] **Step 2: Verify it resolves to exactly one service**

```bash
docker compose -f docker-compose.yml config --services
```

Expected: exactly `yas`.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(compose): collapse yas-api + yas-worker into one yas service"
```

---

## Task 3: Retarget the `dev` and `macos` overlays

Both overlays name `yas-worker` and `yas-api`. Compose *adds* services an overlay names but the base lacks — it does not error. Left unrenamed, `dev.yml` would create two phantom services carrying `build:` while the real `yas` service still pulls from GHCR, and `macos.yml` would attach its named volume to containers nothing starts.

**Files:**
- Modify: `docker-compose.dev.yml`, `docker-compose.macos.yml`

- [ ] **Step 1: Rewrite `docker-compose.dev.yml`**

```yaml
# Override that swaps the GHCR `image:` for a local `build: .` so devs can
# iterate on uncommitted source. The base compose targets prod (pulls from
# GHCR); this override is opt-in and must come LAST so its build: wins.
#
# Usage:
#   docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
#
# Stack with the macOS volume override:
#   docker compose \
#     -f docker-compose.yml \
#     -f docker-compose.macos.yml \
#     -f docker-compose.dev.yml \
#     up --build

services:
  yas:
    build: .
    image: yas-local:dev   # local-only tag; not pushed
```

The `x-build` anchor goes too — it existed only to share the block across two services.

- [ ] **Step 2: Rewrite the `services:` block of `docker-compose.macos.yml`**

Keep the explanatory header comment; replace the services block with:

```yaml
services:
  yas:
    volumes:
      - yas-data:/data

volumes:
  yas-data:
```

Update the header's inspection example from `exec yas-api sqlite3 …` to `exec yas sqlite3 …`.

- [ ] **Step 3: Verify no phantom services appear**

```bash
docker compose -f docker-compose.yml -f docker-compose.macos.yml -f docker-compose.dev.yml config --services
```

Expected: exactly `yas`. **If `yas-api` or `yas-worker` appear, an overlay was missed** — that is the phantom-service failure, and it is silent at `up` time.

- [ ] **Step 4: Verify `yas` actually resolves to a local build**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml config --format json \
  | jq '.services.yas | {image, build: (.build != null)}'
```

Expected: `{"image": "yas-local:dev", "build": true}`.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.dev.yml docker-compose.macos.yml
git commit -m "feat(compose): retarget dev and macos overlays at the yas service"
```

---

## Task 4: Add the standalone split layout

The two-container layout is retained for crash-domain isolation or independent worker scaling. It must be **standalone**, used *instead of* the base file — compose overlays cannot remove a service, so a layered split file could not turn off `yas`.

It uses a named volume rather than a bind mount so it needs no macOS overlay: the split layout is precisely the configuration with concurrent api ↔ worker writes, which is what the VirtioFS bug needs.

**Files:**
- Create: `docker-compose.split.yml`

- [ ] **Step 1: Create the file**

```yaml
# Opt-in two-container layout: API and worker in separate containers.
#
# Use this INSTEAD OF docker-compose.yml, not layered on top of it — compose
# overrides can add and modify services but cannot remove one, so there is no
# way to switch off the base `yas` service from an overlay.
#
#   docker compose -f docker-compose.split.yml up -d
#
# Prefer the default single-container layout unless you specifically want
# independent crash domains or to scale the worker separately.
#
# Uses a named volume rather than ./data on purpose: this is the layout with
# concurrent api <-> worker writes, which is what trips Docker Desktop's
# VirtioFS SQLite locking on macOS.

x-image: &yas-image
  image: ghcr.io/owine/youth-activity-scheduler:latest

services:
  yas-worker:
    <<: *yas-image
    command: ["python", "-m", "yas", "worker"]
    env_file: .env
    volumes:
      - yas-data:/data
    restart: unless-stopped
    # This container runs no HTTP server, so the image's curl /healthz probe
    # would fail forever. Disable it rather than let it flap.
    healthcheck:
      disable: true

  yas-api:
    <<: *yas-image
    command: ["python", "-m", "yas", "api"]
    env_file: .env
    ports:
      - "8080:8080"
    volumes:
      - yas-data:/data
    depends_on:
      yas-worker:
        condition: service_started
    restart: unless-stopped

volumes:
  yas-data:
```

- [ ] **Step 2: Verify it resolves standalone**

```bash
docker compose -f docker-compose.split.yml config --services
```

Expected: `yas-api` and `yas-worker`.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.split.yml
git commit -m "feat(compose): add standalone docker-compose.split.yml"
```

---

## Task 5: Update the scripts

After #333 these use `compose_cmd` and `assert_local_build "$COMPOSE" yas-worker yas-api`. Only the service names change — the chain construction is already centralized.

**Files:**
- Modify: `scripts/lib.sh`, `scripts/e2e_phase5a.sh`, `scripts/smoke_phase3.sh`, `scripts/smoke_phase3_5.sh`, `scripts/smoke_phase4.sh`

- [ ] **Step 1: Update the `assert_local_build` docstring example in `scripts/lib.sh`**

Change `#   assert_local_build "$COMPOSE" yas-worker yas-api` to `#   assert_local_build "$COMPOSE" yas`.

- [ ] **Step 2: Rewrite the service references in all four scripts**

```bash
cd /Users/owine/Git/youth-activity-scheduler
python3 - <<'PYEOF'
import pathlib
for name in ["e2e_phase5a.sh", "smoke_phase3.sh", "smoke_phase3_5.sh", "smoke_phase4.sh"]:
    p = pathlib.Path("scripts") / name
    s = p.read_text()
    s = s.replace('assert_local_build "$COMPOSE" yas-worker yas-api',
                  'assert_local_build "$COMPOSE" yas')
    s = s.replace("$COMPOSE up -d --build yas-worker yas-api", "$COMPOSE up -d --build yas")
    s = s.replace("$COMPOSE up -d yas-worker yas-api", "$COMPOSE up -d yas")
    s = s.replace("$COMPOSE build yas-api yas-worker", "$COMPOSE build yas")
    s = s.replace("exec -T yas-api ", "exec -T yas ")
    p.write_text(s)
    print(f"rewrote {name}")
PYEOF
```

- [ ] **Step 3: Verify no stale references survive**

```bash
grep -rn "yas-api\|yas-worker" scripts/ && echo "STALE REFERENCES ABOVE" || echo "clean"
for f in scripts/*.sh; do bash -n "$f" || echo "SYNTAX FAIL $f"; done; echo "all parse"
```

Expected: `clean`, then `all parse`.

- [ ] **Step 4: Verify the guard accepts the new service**

```bash
bash -c '. scripts/lib.sh; assert_local_build "$(compose_cmd)" yas && echo "GUARD OK"'
```

Expected: `GUARD OK`. Run under **bash**, not zsh — zsh does not word-split unquoted expansions, so `$compose` would arrive as a single argument and the helper would appear to fail.

- [ ] **Step 5: Commit**

```bash
git add scripts/
git commit -m "feat(scripts): point smoke and e2e scripts at the single yas service"
```

---

## Task 6: Documentation, including the upgrade hazard

The sharpest edge in this change is not runtime, it is upgrade. An existing deployment runs `youth-activity-scheduler-yas-api-1` and `-yas-worker-1`. After pulling this, `docker compose up -d` creates the new `yas` container and **leaves both old ones running** — compose only reconciles services it still knows about. Three processes then write one SQLite file. It is silent, data-adjacent, and hits every existing user exactly once.

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: Add an upgrade callout to `README.md`**

Immediately after the Quickstart block, replace the existing `To upgrade later:` line with:

```markdown
> **Upgrading from a version before the single-container layout?** Earlier
> releases ran two containers (`yas-api` + `yas-worker`). Compose will not
> remove them on its own, so you must pass `--remove-orphans` once — otherwise
> the old pair keeps running alongside the new `yas` container and three
> processes write the same SQLite file.
>
> ```bash
> docker compose pull
> docker compose up -d --remove-orphans
> ```

To upgrade later: `docker compose pull && docker compose up -d`.
```

- [ ] **Step 2: Update the rest of `README.md`**

- macOS section: `exec yas-api sqlite3 …` → `exec yas sqlite3 …`
- Add a short subsection documenting `docker compose -f docker-compose.split.yml up -d`, stating it replaces rather than layers onto the base file.
- Check line ~272 (`docker compose up -d  # or: python -m yas api`) still reads correctly.

- [ ] **Step 3: Update `CLAUDE.md`**

- "Process model" section: note that the shipped compose runs one container in `all` mode, and that `api`/`worker` remain for CI and the split layout.
- The `docker-compose.dev.yml` gotcha added in #333: service name is now `yas`.
- macOS overlay paragraph: service name.

- [ ] **Step 4: Verify no stale service names remain in docs**

```bash
grep -rn "yas-api\|yas-worker" README.md CLAUDE.md
```

Expected: only mentions inside the split-layout section and the upgrade callout, both of which intentionally name the old containers.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: single-container layout, split opt-in, --remove-orphans upgrade note"
```

---

## Task 7: End-to-end verification

**Files:** none modified.

- [ ] **Step 1: Full backend suite**

```bash
uv run pytest && uv run ruff check . && uv run mypy src
```

- [ ] **Step 2: Full docker e2e**

```bash
./scripts/e2e_phase5a.sh
```

Expected: a real local build, then 4/4 Playwright specs. This is the regression net for migrations, the API, seeding, and the SPA against a live single container.

- [ ] **Step 3: Prove the supervision change end-to-end**

The unit tests cover `_supervise` in isolation; this confirms the wiring.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
docker compose exec -T yas pkill -f "yas all" || true
sleep 15
docker compose ps          # expect the container restarted, not sitting dead
docker compose logs --tail 20 yas
docker compose down -v
```

Expected: the container exits and is restarted by `restart: unless-stopped`.

- [ ] **Step 4: Rehearse the orphan hazard**

This is the one users will hit. Verify both the failure and the fix.

```bash
git stash                                    # back to the two-container layout
docker compose up -d                         # old yas-api + yas-worker
git stash pop                                # new single-service layout
docker compose up -d                         # WITHOUT --remove-orphans
docker ps --format '{{.Names}}' | grep yas   # expect THREE containers — the hazard
docker compose up -d --remove-orphans
docker ps --format '{{.Names}}' | grep yas   # expect ONE
docker compose down -v
```

If the middle step does not show three containers, the README callout is describing a hazard that does not exist — re-check before shipping the warning.

- [ ] **Step 5: Verify the split layout boots**

```bash
docker compose -f docker-compose.split.yml up -d
curl -fsS http://localhost:8080/healthz
curl -fsS http://localhost:8080/readyz     # heartbeat_fresh proves the worker container runs
docker compose -f docker-compose.split.yml down -v
```

- [ ] **Step 6: Open the PR**

Do not use auto-close keywords (`Closes #N`) — issue #1 is the Renovate dependency dashboard. Follow the repo PR SOP: open, wait for the Sourcery review, address actionable feedback, then enable auto-merge.

---

## Out of scope

**Deleting `docker-compose.macos.yml`.** It exists because Docker Desktop's VirtioFS does not fully honor SQLite's locking primitives under "concurrent api ↔ worker access". One container removes cross-*process* contention, which is suggestive — but SQLAlchemy's async engine keeps a **connection pool**, so one process still holds several connections to the same file. That may be enough to keep triggering the bug. The overlay stays, retargeted. Whether it can go is a separate question needing an actual reproduction on a bind mount, not an inference from architecture.
