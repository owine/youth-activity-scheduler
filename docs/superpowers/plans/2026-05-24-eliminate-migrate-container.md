# Eliminate `yas-migrate` Container — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the `yas-migrate` one-shot service from compose by having every yas process apply Alembic migrations on startup.

**Architecture:** A new `yas.db.migrations.upgrade_to_head(database_url)` helper invokes `alembic.command.upgrade` programmatically. It's called from `src/yas/__main__.py` after logging is configured and before the SQLAlchemy engine is created, for every CLI mode (`api`, `worker`, `all`, plus a new `migrate` mode). SQLite's OS-level file lock serializes the rare race between api and worker booting in parallel.

**Tech Stack:** Python 3.14, Alembic, SQLAlchemy + aiosqlite, FastAPI, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-05-24-eliminate-migrate-container-design.md`

---

## File Structure

**New files:**
- `src/yas/db/migrations.py` — `upgrade_to_head(database_url)` helper
- `tests/unit/test_db_migrations.py` — unit tests for the helper

**Modified files:**
- `alembic/env.py` — respect a pre-set `sqlalchemy.url` instead of always overwriting from settings (so the helper can pass a tmp URL during tests)
- `src/yas/__main__.py` — add `"migrate"` mode, call `upgrade_to_head` at the top of `main()`
- `docker-compose.yml` — delete `yas-migrate` service, drop `depends_on` edges
- `docker-compose.dev.yml` — drop `yas-migrate` override block
- `docker-compose.macos.yml` — drop `yas-migrate` volume override block
- `scripts/smoke_phase2.sh` — replace `up -d yas-migrate` with comment+drop
- `scripts/smoke_phase3.sh` — same
- `scripts/smoke_phase3_5.sh` — same
- `scripts/smoke_phase4.sh` — same
- `scripts/e2e_phase5a.sh` — same, and drop from `build` line
- `README.md` — remove `uv run alembic upgrade head` from Quickstart

**Untouched:**
- `Dockerfile` (alembic.ini and alembic/ already copied in)
- `alembic.ini`, `alembic/versions/*` (no migration content changes)
- `docker-compose.smoke.yml` (verified: no `yas-migrate` reference)

---

## Task 1: Add `alembic/env.py` URL-override gate

This is a prerequisite. Today `env.py` unconditionally sets `sqlalchemy.url` from `get_settings()`, which would clobber any URL a programmatic caller (the new helper) tries to pass in. We make the assignment conditional: if the caller has already set a URL on the Config, use it; otherwise fall back to settings (preserves today's `alembic` CLI behavior).

**Files:**
- Modify: `alembic/env.py:34-37`

- [ ] **Step 1: Read current `alembic/env.py`**

Just read it. No edit yet.

- [ ] **Step 2: Replace the settings-URL assignment with a conditional**

Find:

```python
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
```

Replace with:

```python
# Prefer a URL set by a programmatic caller (e.g. yas.db.migrations);
# fall back to settings for `alembic …` CLI invocations.
if not config.get_main_option("sqlalchemy.url"):
    settings = get_settings()
    config.set_main_option("sqlalchemy.url", settings.database_url)
```

- [ ] **Step 3: Verify the CLI path still works**

Run from repo root with a throwaway DB:

```bash
YAS_DATABASE_URL=sqlite+aiosqlite:///$(mktemp -u --suffix=.db) uv run alembic upgrade head
```

Expected: alembic runs the migrations to head and exits 0. (You can ignore the "no such file" warning if the temp path is unwritable; just point at `data/test.db`.)

- [ ] **Step 4: Commit**

```bash
git add alembic/env.py
git commit -m "refactor(alembic): respect pre-set sqlalchemy.url in env.py

Allows programmatic callers to pass a URL via Config.set_main_option
without it being overwritten by settings."
```

---

## Task 2: Add `upgrade_to_head` helper with tests

**Files:**
- Create: `src/yas/db/migrations.py`
- Create: `tests/unit/test_db_migrations.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_db_migrations.py`:

```python
"""Tests for yas.db.migrations.upgrade_to_head."""

from __future__ import annotations

import sqlite3

from yas.db.migrations import upgrade_to_head


def test_upgrade_to_head_creates_tables(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_path}"

    upgrade_to_head(url)

    # Sanity-check that at least one expected table exists. We don't enumerate
    # all of them — that's coupling the test to the current schema. Pick a
    # table that has existed since the very first migration.
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "select name from sqlite_master where type='table' and name='sites'"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("sites",)]


def test_upgrade_to_head_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_path}"

    upgrade_to_head(url)
    upgrade_to_head(url)  # second call should be a no-op, not raise
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/unit/test_db_migrations.py -v
```

Expected: `ModuleNotFoundError: No module named 'yas.db.migrations'`

- [ ] **Step 3: Implement `upgrade_to_head`**

Create `src/yas/db/migrations.py`:

```python
"""Programmatic Alembic runner used at process startup.

Every yas process calls `upgrade_to_head` before opening the SQLAlchemy
engine, replacing the dedicated `yas-migrate` compose service.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from yas.logging import get_logger

log = get_logger(__name__)


def _find_alembic_ini() -> Path:
    """Locate alembic.ini.

    The package can be installed editable (file lives under src/yas/db/) or
    non-editable into site-packages (file lives under .venv/.../yas/db/).
    Repo-root layout and image layout both put alembic.ini next to a top-level
    directory we can find by walking up from CWD. Prefer CWD because the image
    sets WORKDIR /app and the repo's pytest runs from the repo root.
    """
    cwd_candidate = Path.cwd() / "alembic.ini"
    if cwd_candidate.is_file():
        return cwd_candidate
    # Fallback: walk up from this file looking for alembic.ini. Handles the
    # less common case where CWD doesn't contain it.
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "alembic.ini"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("alembic.ini not found from CWD or via parent walk")


def upgrade_to_head(database_url: str) -> None:
    """Apply pending Alembic migrations against `database_url`.

    Idempotent: a no-op when the database is already at head.
    """
    cfg = Config(str(_find_alembic_ini()))
    cfg.set_main_option("sqlalchemy.url", database_url)
    log.info("migrations.start", url=database_url)
    command.upgrade(cfg, "head")
    log.info("migrations.done")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_db_migrations.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yas/db/migrations.py tests/unit/test_db_migrations.py
git commit -m "feat(db): add upgrade_to_head helper

Programmatic Alembic runner that every yas process will call on
startup, removing the need for a dedicated migrate container."
```

---

## Task 3: Wire migrations into the CLI entrypoint

Add `"migrate"` as a CLI mode and call `upgrade_to_head` at the top of `main()` so every mode applies migrations before doing real work.

**Files:**
- Modify: `src/yas/__main__.py`

- [ ] **Step 1: Add `"migrate"` to the mode choices**

In `build_parser()`, change the `choices` list from:

```python
choices=["api", "worker", "all"],
```

to:

```python
choices=["api", "worker", "all", "migrate"],
```

Update the `help` string to mention `migrate` (e.g. `"migrate (apply schema only and exit)"`).

- [ ] **Step 2: Call `upgrade_to_head` in `main()`**

In `main()`, **after** the `log = get_logger("yas.main")` line (so `log` is bound) and **before** the `engine = create_engine_for(...)` line, add:

```python
from yas.db.migrations import upgrade_to_head

upgrade_to_head(settings.database_url)

if args.mode == "migrate":
    log.info("mode.migrate.done")
    return 0
```

The early-return for `"migrate"` short-circuits before the engine is created or any mode branch runs.

- [ ] **Step 3: Smoke-test the new mode locally**

```bash
rm -f /tmp/yas-test.db
YAS_DATABASE_URL=sqlite+aiosqlite:////tmp/yas-test.db \
  YAS_ANTHROPIC_API_KEY=sk-test \
  uv run python -m yas migrate
```

Expected: process exits 0, logs show `migrations.start` then `migrations.done` then `mode.migrate.done`. The file `/tmp/yas-test.db` exists and contains the schema.

Verify with:

```bash
sqlite3 /tmp/yas-test.db '.tables'
```

Expected: lists the schema tables (sites, offerings, kids, etc.).

- [ ] **Step 4: Run the full test suite to catch regressions**

```bash
uv run pytest -x
```

Expected: all tests pass. (No existing tests exercise `__main__`'s mode branches; the new migration call is gated behind the CLI entry, so unit tests are unaffected.)

- [ ] **Step 5: Commit**

```bash
git add src/yas/__main__.py
git commit -m "feat(cli): run migrations on every startup; add migrate mode

Every yas process now applies pending Alembic migrations before
opening the engine. The new 'migrate' mode applies and exits.
This is the prerequisite for removing the yas-migrate compose
service in the next commit."
```

---

## Task 4: Remove `yas-migrate` from compose files

**Files:**
- Modify: `docker-compose.yml` — delete `yas-migrate` service block (lines ~4-15) and the two `yas-migrate: condition: service_completed_successfully` entries in `yas-worker` and `yas-api` `depends_on`.
- Modify: `docker-compose.dev.yml` — delete the `yas-migrate: <<: *yas-build` line.
- Modify: `docker-compose.macos.yml` — delete the `yas-migrate:` volume override block.

- [ ] **Step 1: Edit `docker-compose.yml`**

Delete the entire `yas-migrate:` service block (the first service under `services:`).

In `yas-worker`, change:

```yaml
    depends_on:
      yas-migrate:
        condition: service_completed_successfully
```

to: delete those lines entirely. `yas-worker` should have no `depends_on:` key after this edit.

In `yas-api`, change:

```yaml
    depends_on:
      yas-migrate:
        condition: service_completed_successfully
      yas-worker:
        condition: service_started
```

to:

```yaml
    depends_on:
      yas-worker:
        condition: service_started
```

(Keep the `yas-api → yas-worker` edge — the spec preserves it.)

Also remove the stale comment in `yas-worker` that begins `# Same reason as yas-migrate:` and rewrite it to stand on its own (or delete it — the disabled healthcheck no longer needs justification by analogy).

- [ ] **Step 2: Edit `docker-compose.dev.yml`**

Delete the two lines:

```yaml
  yas-migrate:
    <<: *yas-build
```

- [ ] **Step 3: Edit `docker-compose.macos.yml`**

Delete the block:

```yaml
  yas-migrate:
    volumes:
      - yas-data:/data
```

- [ ] **Step 4: Validate compose syntax**

```bash
docker compose -f docker-compose.yml config > /dev/null
docker compose -f docker-compose.yml -f docker-compose.dev.yml config > /dev/null
docker compose -f docker-compose.yml -f docker-compose.macos.yml config > /dev/null
```

Expected: all three commands exit 0 with no output. (They print the resolved compose and discard it.)

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml docker-compose.dev.yml docker-compose.macos.yml
git commit -m "chore(compose): remove yas-migrate service

API and worker now apply migrations on startup themselves. The
dedicated migrate one-shot is no longer needed."
```

---

## Task 5: Update shell scripts that referenced `yas-migrate`

The smoke and e2e scripts bring `yas-migrate` up explicitly. Now that the service is gone, those lines must be removed; the api/worker services will migrate themselves on startup.

**Files:**
- Modify: `scripts/smoke_phase2.sh:17-18`
- Modify: `scripts/smoke_phase3.sh:16`
- Modify: `scripts/smoke_phase3_5.sh:16`
- Modify: `scripts/smoke_phase4.sh:17`
- Modify: `scripts/e2e_phase5a.sh:13-14`

- [ ] **Step 1: Edit `scripts/smoke_phase2.sh`**

Replace:

```bash
docker compose up -d yas-migrate
docker compose logs yas-migrate | tail -5
docker compose up -d yas-worker yas-api
```

with:

```bash
# yas-worker and yas-api apply migrations themselves on startup.
docker compose up -d yas-worker yas-api
```

- [ ] **Step 2: Edit `scripts/smoke_phase3.sh`**

Replace:

```bash
$COMPOSE up -d yas-migrate
$COMPOSE up -d yas-worker yas-api
```

with:

```bash
$COMPOSE up -d yas-worker yas-api
```

- [ ] **Step 3: Edit `scripts/smoke_phase3_5.sh`**

Same edit pattern as Step 2 — remove the `$COMPOSE up -d yas-migrate` line.

- [ ] **Step 4: Edit `scripts/smoke_phase4.sh`**

Same edit pattern as Step 2 — remove the `$COMPOSE up -d yas-migrate` line.

- [ ] **Step 5: Edit `scripts/e2e_phase5a.sh`**

Replace:

```bash
$COMPOSE build yas-api yas-worker yas-migrate
$COMPOSE up -d yas-migrate
```

with:

```bash
$COMPOSE build yas-api yas-worker
```

- [ ] **Step 6: Quick sanity-check each script for stray references**

```bash
grep -n yas-migrate scripts/*.sh
```

Expected: no output (no remaining references in scripts).

- [ ] **Step 7: Commit**

```bash
git add scripts/smoke_phase2.sh scripts/smoke_phase3.sh scripts/smoke_phase3_5.sh scripts/smoke_phase4.sh scripts/e2e_phase5a.sh
git commit -m "chore(scripts): drop yas-migrate references from smoke/e2e

Worker and api migrate themselves on startup now."
```

---

## Task 6: Update README Quickstart

The Quickstart says to run `uv run alembic upgrade head` before `python -m yas all`. That line is now redundant — `python -m yas all` will migrate.

**Files:**
- Modify: `README.md:66`

- [ ] **Step 1: Delete the `uv run alembic upgrade head` line in Quickstart**

Find the Quickstart block:

```bash
uv sync
cp .env.example .env
echo "YAS_ANTHROPIC_API_KEY=sk-ant-…" >> .env
mkdir -p data
uv run alembic upgrade head
uv run python -m yas all
```

Delete the `uv run alembic upgrade head` line.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: drop manual alembic step from Quickstart

python -m yas all now applies migrations itself on startup."
```

---

## Task 7: End-to-end verification

Confirm the assembled change actually boots and works.

- [ ] **Step 1: Run the unit suite**

```bash
uv run pytest -x
```

Expected: all pass.

- [ ] **Step 2: Boot the dev compose stack against a fresh DB**

```bash
rm -f data/activities.db data/activities.db-shm data/activities.db-wal
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
sleep 15
docker compose ps
```

Expected: `yas-api` and `yas-worker` both `running` (healthy or starting); no `yas-migrate` service listed.

- [ ] **Step 3: Confirm schema applied**

```bash
docker compose exec yas-api sqlite3 /data/activities.db '.tables'
```

Expected: lists all schema tables (sites, offerings, kids, alerts, etc.).

- [ ] **Step 4: Confirm `/healthz` returns 200**

```bash
curl -fsS localhost:8080/healthz | jq .
```

Expected: 200 OK response.

- [ ] **Step 5: Check the api logs for the migration banner**

```bash
docker compose logs yas-api | grep -E 'migrations\.(start|done)'
```

Expected: one `migrations.start` and one `migrations.done` line near the top of api startup.

- [ ] **Step 6: Bring the stack down**

```bash
docker compose down
```

- [ ] **Step 7: (No commit — this task is verification only.)**

If anything failed in steps 1-5, return to the relevant earlier task and fix before continuing.

---

## Out of Scope (do not do as part of this plan)

- Migrating off SQLite.
- Adding a `--skip-migrations` flag.
- Updating historical references to `yas-migrate` inside `docs/superpowers/plans/2026-04-*.md` and `docs/superpowers/specs/2026-04-*.md` — those are historical artifacts of completed phases and should remain accurate to the topology of their time.
- Migration rollback / `downgrade` tooling.
