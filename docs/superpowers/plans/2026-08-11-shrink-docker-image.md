# Shrink the Shipped Docker Image — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut `ghcr.io/owine/youth-activity-scheduler` from **2.61 GB to ~1.83 GB** (−30%) with no behavior change: one image, `needs_browser` sites keep working, no compose or docs changes.

**Architecture:** Four edits, all confined to `Dockerfile`. Stop `uv run` from reinstating the dev dependency group; install only Chromium's headless shell instead of headed Chromium *and* the shell; obtain `uv` via a build-time bind mount so the 46 MB binary never lands in a layer; reorder so the expensive browser layer sits above the source `COPY` and survives source-only commits.

**Tech Stack:** Docker BuildKit (dockerfile syntax 1.26), uv 0.12.3, Playwright 1.62.0, python:3.14.7-slim.

**Spec:** none — this plan is self-contained.

---

## Measured baseline

Built locally from `main` @ `0a8398e` (`linux/arm64`), `docker build -t yas:size-baseline .` → **2.61 GB**.

| Layer | Size |
| --- | --- |
| `RUN uv run playwright install --with-deps chromium` | **1.51 GB** |
| `RUN uv sync --frozen --no-dev --no-install-project` | 218 MB |
| Debian trixie base | 109 MB |
| python:3.14.7-slim build layer | 45 MB |
| `COPY /uv /usr/local/bin/uv` | 46 MB |
| `RUN apt-get ... ca-certificates curl sqlite3` | 15 MB |
| `COPY /build/dist /app/static` | 5.5 MB |

Inside the 1.51 GB Playwright layer (`du -sh` in a running container):

| Item | Size |
| --- | --- |
| `/root/.cache/ms-playwright/chromium-1234` (headed) | 641 MB |
| `/root/.cache/ms-playwright/chromium_headless_shell-1234` | 340 MB |
| apt libs pulled by `--with-deps` (`/usr/lib/aarch64-linux-gnu` growth) | ~277 MB |
| `/usr/share/fonts` | 91 MB |
| `/root/.cache/ms-playwright/ffmpeg-1011` | 3.3 MB |

---

## Defect 1: the dev dependency group ships in production

`/app/.venv` in the shipped image contains `pytest`, `ruff`, `mypy`, `mypyc` (incl. a 38 MB compiled `.so`), `pre-commit`, `virtualenv`, `coverage`, and `aiohttp` — roughly 90 MB — even though **both** `uv sync` calls pass `--no-dev`.

Cause is `Dockerfile:47`, `RUN uv run playwright install --with-deps chromium`. `uv run` re-syncs the project environment before executing, and without `--no-dev` it reinstates the default `dev` group, silently undoing `Dockerfile:44`. Reproduced in a scratch container against the built image:

```
$ uv sync --frozen --no-dev
  after --no-dev sync:  mypy present? NO
$ uv run --frozen python -c "pass"
  Downloaded ruff / Downloaded mypy / Installed 36 packages in 212ms
  after plain uv run:   mypy present? /tmp/venv/lib/python3.14/site-packages/mypy
```

Shipping a test runner and a linter in the runtime image is both size bloat and needless attack surface on an API that is unauthenticated by design.

**Fix:** drop `uv run` entirely. `Dockerfile:25` already puts `/app/.venv/bin` first on `PATH`, and `playwright` is a *main* dependency, so a bare `playwright install` resolves to the venv binary and never triggers a sync.

## Defect 2: 641 MB of headed Chromium is downloaded and never launched

`playwright install ... chromium` fetches **both** full headed Chromium (641 MB) and the headless shell (340 MB). `src/yas/crawl/fetcher.py:113` launches with `headless=True` and **no** `channel=`:

```python
self._browser = await self._playwright.chromium.launch(headless=True)
```

Playwright's docs (playwright.dev/python/docs/browsers, "Chromium: headless shell") state that when running headlessly without specifying a `channel`, download size can be reduced with `--only-shell`. `playwright install --help` in the built image confirms the flag exists in 1.62.0:

```
--only-shell   only install headless shell when installing chromium
```

**Fix:** `playwright install --with-deps --only-shell chromium`. The 641 MB headed build goes away; the shell that `fetcher.py` actually launches stays.

## Defect 3: the `uv` binary is shipped but only needed at build time

`Dockerfile:31` `COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv` commits 46 MB. Nothing at runtime invokes `uv` — `CMD` is `python -m yas all`.

A builder stage would fix this, but it would also force the venv `COPY --from` to sit *below* the source copy, busting the Playwright layer on every commit (see Defect 4). A BuildKit bind mount gets the same result without restructuring. Verified with a throwaway build:

```
#12 RUN --mount=type=bind,from=ghcr.io/astral-sh/uv:0.12.3,source=/uv,target=/usr/local/bin/uv uv --version
#12 0.109 uv usable via bind mount
#13 RUN test ! -e /usr/local/bin/uv && echo "CONFIRMED: uv binary NOT in final image"
#13 0.123 CONFIRMED: uv binary NOT in final image
```

**Fix:** replace the `COPY --from` with a `--mount=type=bind,from=...` on each of the two `uv sync` lines.

## Defect 4 (CI time, not size): the heaviest layer rebuilds on every commit

`Dockerfile:47` sits *below* `COPY src ./src`, so any source-only change invalidates a ~1.5 GB layer — on both the amd64 and arm64 matrix legs. The browser install depends only on the `playwright` version from `uv.lock`, so it can move above the source copy and then only rebuilds when the lockfile does.

**Fix:** move the `playwright install` line to sit directly after the deps-only `uv sync`.

---

## File Structure

**Modified files:**
- `Dockerfile` — all four fixes

**Untouched (verified):**
- `src/yas/crawl/fetcher.py` — `--only-shell` needs no code change precisely because the launch call passes no `channel=`
- `pyproject.toml` — `playwright==1.62.0` stays a main dependency
- `docker-compose*.yml`, `README.md` — image name, tags, ports, volumes, healthcheck all unchanged
- `.dockerignore` — build context is already lean; not a contributor
- apt packages — `sqlite3` stays: `scripts/smoke_phase3.sh:50`, `scripts/smoke_phase3_5.sh:55` and `README.md:56` run `compose exec yas-api sqlite3 /data/activities.db`. `curl` stays: it backs `HEALTHCHECK`.

**Explicitly out of scope:** hand-trimming the ~277 MB of `--with-deps` apt libraries and the 91 MB of fonts. Together worth maybe another 250 MB, but a missing shared library surfaces only when a `needs_browser` site is actually crawled — a failure mode that would reach production silently. Revisit separately with a dedicated e2e guard.

---

## Task 1: Rewrite the backend stage of the Dockerfile

**Files:**
- Modify: `Dockerfile:31-47`

- [ ] **Step 1: Read the current `Dockerfile`**

Read it in full. Note that stage 1 (`frontend-build`) and everything from `RUN mkdir -p /data` (line 49) down are unchanged by this plan.

- [ ] **Step 2: Delete the `COPY --from=...uv` line**

Remove:

```dockerfile
COPY --from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /usr/local/bin/uv
```

- [ ] **Step 3: Replace the two `uv sync` blocks and the Playwright line**

Find the block running from `# Layer 1: install deps only` through `RUN uv run playwright install --with-deps chromium`, and replace it with:

```dockerfile
# Layer 1: install deps only (not the project). README.md is required by
# hatchling metadata validation even when the project itself isn't built here.
#
# uv arrives via a build-time bind mount rather than COPY, so the 46 MB binary
# is usable during the RUN and absent from the committed layer. Nothing at
# runtime invokes uv — CMD is `python -m yas all`.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=bind,from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-install-project

# Playwright browser + OS deps. Two things matter here:
#
# 1. `--only-shell` installs just the Chromium headless shell, skipping the
#    641 MB headed build. crawl/fetcher.py launches with headless=True and no
#    channel=, which is exactly the case the headless shell serves.
# 2. Bare `playwright`, NOT `uv run playwright`. `uv run` re-syncs the project
#    environment first, and without --no-dev that reinstates the whole dev
#    group (pytest, ruff, mypy, pre-commit — ~90 MB), silently undoing the
#    --no-dev on the syncs around it. PATH already prefers /app/.venv/bin.
#
# Placed above `COPY src` on purpose: this layer depends only on the playwright
# version in uv.lock, so source-only commits reuse it instead of rebuilding
# ~1.1 GB on both matrix legs.
RUN playwright install --with-deps --only-shell chromium

# Layer 2: copy source and install the project itself.
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN --mount=type=bind,from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev
```

Note the uv image digest is duplicated across the two mounts. Renovate pins it via the existing `COPY --from` datasource; confirm in Task 3 that it still tracks the new form.

---

## Task 2: Rebuild and verify

**Files:** none modified — this task is pure verification.

- [ ] **Step 1: Build**

```bash
docker build -t yas:size-after .
```

- [ ] **Step 2: Confirm the size drop**

```bash
docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | grep yas
```

Expect `yas:size-after` at **~1.8 GB**, down from the 2.61 GB baseline. If it is above 2.0 GB, stop and re-inspect layers with `docker history yas:size-after --no-trunc` before continuing.

- [ ] **Step 3: Confirm dev deps are gone**

```bash
docker run --rm --entrypoint sh yas:size-after -c '
for p in mypy pytest ruff pre_commit virtualenv coverage; do
  ls -d /app/.venv/lib/python3.14/site-packages/$p >/dev/null 2>&1 && echo "LEAKED: $p"
done; echo "dev-dep check done"'
```

Must print `dev-dep check done` with **no** `LEAKED:` lines.

- [ ] **Step 4: Confirm headed Chromium is gone and the shell remains**

```bash
docker run --rm --entrypoint sh yas:size-after -c 'du -sh /root/.cache/ms-playwright/*'
```

Expect a `chromium_headless_shell-*` entry and **no** bare `chromium-*` entry.

- [ ] **Step 5: Confirm `uv` is not in the image**

```bash
docker run --rm --entrypoint sh yas:size-after -c 'command -v uv || echo "uv absent (expected)"'
```

- [ ] **Step 6: Confirm the browser actually launches**

This is the load-bearing check — it is the only step that proves `--only-shell` satisfies `fetcher.py`. A green build proves nothing here, because the Playwright import is lazy (`fetcher.py:110`) and never runs unless a site is flagged `needs_browser`.

```bash
docker run --rm --entrypoint python yas:size-after -c '
import asyncio
from playwright.async_api import async_playwright

async def main():
    p = await async_playwright().start()
    b = await p.chromium.launch(headless=True)   # same call as fetcher.py:113
    page = await (await b.new_context()).new_page()
    await page.set_content("<h1>ok</h1>")
    print("BROWSER OK:", await page.inner_text("h1"))
    await b.close(); await p.stop()

asyncio.run(main())'
```

Must print `BROWSER OK: ok`. If it reports a missing executable, `--only-shell` is not resolving for this launch call and Task 1 Step 3 needs `channel="chromium-headless-shell"` added to `fetcher.py:113` — reassess before proceeding.

- [ ] **Step 7: Confirm the app still boots and serves the SPA**

```bash
docker run --rm -d --name yas-verify -p 18080:8080 -e YAS_ANTHROPIC_API_KEY=sk-test-nonop yas:size-after
# wait for the container healthcheck to report healthy, then:
curl -fsS http://localhost:18080/healthz
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:18080/
docker rm -f yas-verify
```

`/healthz` must return its JSON body; `/` must return `200` (SPA fallback still serving `/app/static`).

- [ ] **Step 8: Run the full docker e2e**

```bash
./scripts/e2e_phase5a.sh
```

Must pass. This is the regression net for migrations, the API, and the Playwright specs against a real container.

---

## Task 3: Confirm CI and Renovate still work

**Files:**
- Possibly modify: `renovate.json`

- [ ] **Step 1: Check Renovate still sees the uv image pin**

The uv digest moved from `COPY --from=<image>` to `--mount=...,from=<image>`. Confirm Renovate's dockerfile manager still extracts it — if it does not, the pin goes stale silently, which is worse than the 46 MB it saves.

Run Renovate's debug extraction against the repo, or check the Dependency Dashboard after the next run for a `ghcr.io/astral-sh/uv` entry. If it is no longer tracked, either add a `customManagers` regex rule in `renovate.json` for the `--mount ... from=` form, or revert Task 1 Step 2 and accept the 46 MB.

- [ ] **Step 2: Confirm the CI build passes on both arches**

`.github/workflows/ci.yml` builds `linux/amd64` on `ubuntu-24.04` and `linux/arm64` on `ubuntu-24.04-arm`. The baseline measurements in this plan are arm64; verify amd64 lands in the same range. No workflow edits are expected — `context`, `platforms`, and the `GIT_SHA` build-arg are all untouched.

---

## Expected result

| Change | Saves |
| --- | --- |
| `--only-shell` — drop headed Chromium | ~641 MB |
| Bare `playwright` instead of `uv run` — drop dev group | ~90 MB |
| Bind-mount `uv` instead of `COPY` | ~46 MB |
| **Total** | **~777 MB (2.61 GB → ~1.83 GB)** |

Plus: source-only commits stop rebuilding a ~1.1 GB layer on both CI matrix legs.

---

## Actual result (implemented 2026-08-11, linux/arm64)

**2.61 GB → 1.49 GB (−1.12 GB, −43%)** — better than the ~1.83 GB projection.

The estimate was conservative in two places. The venv shrank 334 MB → 209 MB (−125 MB, not −90 MB: the dev group's compiled `mypyc` `.so` was larger than the site-packages listing suggested), and `--with-deps` pulls a smaller apt set for the headless shell than for headed Chromium, so the Playwright layer landed at **711 MB** rather than the ~870 MB implied by subtracting only the browser download.

| Layer | Before | After |
| --- | --- | --- |
| `playwright install ...` | 1.51 GB | **711 MB** |
| `uv sync --no-dev --no-install-project` | 218 MB | 218 MB |
| `COPY /uv /usr/local/bin/uv` | 46 MB | *gone* |
| `/app/.venv` (total) | 334 MB | 209 MB |
| `/root/.cache/ms-playwright` | 984 MB | 343 MB |

Verification results:
- Dev-dep scan: clean, no `LEAKED:` lines.
- Browsers: only `chromium_headless_shell-1234` (340 MB) + `ffmpeg-1011`; no headed `chromium-*`.
- `command -v uv` → absent.
- Headless launch via the exact `fetcher.py:113` call → `BROWSER OK: ok`. **No `channel=` change to `fetcher.py` was needed.**
- Container boot: `/healthz` ok, `/readyz` `db_reachable: true` + `heartbeat_fresh: true`, `/` → 200, `/api/nope` → 404 (SPA fallback guard intact).

### Defect this plan missed: `uv run` inside a running container

`scripts/e2e_phase5a.sh:18` ran `$COMPOSE exec -T yas-api uv run python - ... < scripts/seed_e2e.py`. Removing the `uv` binary from the image is an **API change to every `docker exec` in the repo**, not just an internal size optimization — this line would have failed with `uv: not found`.

Fixed by dropping to bare `python` (PATH already prefers `/app/.venv/bin`). Audited the rest: the only other in-container `exec` calls are `scripts/smoke_phase3.sh:50`, `scripts/smoke_phase3_5.sh:55`, and `README.md:56`, all invoking `sqlite3`, which this plan deliberately keeps. `.github/workflows/ci.yml:140`'s `uv run` executes on the host runner, not in the container, and is unaffected.

Add to the "Modified files" list: `scripts/e2e_phase5a.sh`.

### Trap hit while verifying: `e2e_phase5a.sh` does not test local changes

Task 2 Step 8's first run passed — against the **published** `ghcr.io/owine/youth-activity-scheduler:latest`, not the local build. `docker-compose.yml` declares `image:` via the `x-image` anchor with **no `build:` stanza**, so the script's `$COMPOSE build yas-api yas-worker` is a no-op:

```
$ docker compose -f docker-compose.yml build yas-api
warning: No services to build
```

`up -d` then pulled from GHCR. The run was doubly misleading: it passed in part *because* the published image still contains `uv`, masking the `e2e_phase5a.sh:18` defect above.

Workaround used to get a valid run: `docker tag yas:size-after ghcr.io/owine/youth-activity-scheduler:latest` before invoking the script (compose's default pull policy is `missing`, so a locally present tag wins), then retag back to the published digest afterward. Result: 4/4 Playwright specs pass, and this run *does* exercise the bare-`python` seed step inside the new image.

This is a pre-existing repo gap, not something this change introduced.

**Fixed (follow-up, same session).** No new compose file was needed — `docker-compose.dev.yml` already existed for exactly this ("Override that swaps the GHCR `image:` for a local `build: .`"), and simply nothing referenced it. The fix is to layer it into the `$COMPOSE` chain, last, so it overrides `image:`:

```bash
COMPOSE="$COMPOSE -f docker-compose.dev.yml"
```

Plus a regression guard in `e2e_phase5a.sh`, since the original failure was silent and passed:

```bash
if ! $COMPOSE config | grep -q '^ *build:'; then
  echo "ERROR: no 'build:' in the compose chain — refusing to e2e a pulled image" >&2
  exit 2
fi
```

The same defect was present in all three smoke scripts, fixed the same way (with `up -d` → `up -d --build`). `scripts/smoke_phase3.sh` and `scripts/smoke_phase3_5.sh` needed one extra correction first: on non-Darwin they used a bare `docker compose` with **no** `-f` and relied on auto-discovery. Passing any `-f` disables auto-discovery, so adding `-f docker-compose.dev.yml` alone would have made compose read *only* dev.yml. Both were normalized to the explicit `-f docker-compose.yml` form that `smoke_phase4.sh` already used.

Verification: `docker compose ... config --format json` resolves `yas-api` and `yas-worker` to `image=yas-local:dev build=True` across all four chains; the guard correctly passes with dev.yml and fails without it; and a clean run (`docker rmi yas-local:dev` first) shows a real build (`unpacking to docker.io/library/yas-local:dev`) producing the 1.49 GB image, with 4/4 specs passing.

`CLAUDE.md`'s "full docker e2e: build, seed, playwright, teardown" is now accurate. A gotcha entry was added there documenting the `docker-compose.dev.yml` requirement.

### Task 3 Step 1 resolved: Renovate still tracks the uv pin

No `renovate.json` change needed. Renovate's dockerfile manager documents `RUN --mount` as a supported dependency source, and the docs' own example is this exact pattern:

```dockerfile
RUN --mount=from=ghcr.io/astral-sh/uv:0.5,source=/uv,target=/bin/uv \
    uv venv
```
