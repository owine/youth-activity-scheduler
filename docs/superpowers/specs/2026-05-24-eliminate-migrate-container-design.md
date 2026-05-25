# Eliminate the `yas-migrate` Container

**Date:** 2026-05-24
**Status:** Approved (pending spec review)

## Problem

The `docker-compose.yml` topology currently includes three services:

- `yas-migrate` — one-shot container that runs `alembic upgrade head` and exits
- `yas-worker` — long-running crawl + alert worker, `depends_on: yas-migrate`
- `yas-api` — FastAPI server, `depends_on: yas-migrate` and `yas-worker`

`yas-migrate` exists only to apply schema changes before either long-running
process opens the database. It adds a service to the topology and a dependency
edge to two others, but has no runtime responsibility once it exits.

The goal of this change is to **remove `yas-migrate`** and have every yas
process apply pending migrations on its own startup.

## Non-goals

- Switching off SQLite.
- Migration rollback / auto-downgrade tooling.
- A `--skip-migrations` flag.
- Changing the topology beyond removing one service and its `depends_on` edges.

## Constraints

- **Database:** SQLite at `/data/activities.db` on a shared bind mount. File-level
  OS locking serializes concurrent writers.
- **Topology:** api and worker run as separate containers on the same host,
  sharing the SQLite volume.
- **Image:** `alembic.ini` and the `alembic/` directory are already baked into
  the image and used today by `yas-migrate`'s `uv run alembic upgrade head`
  command.

## Design

### Architecture

Every yas process — `api`, `worker`, `all`, and a new `migrate` mode — calls
`alembic upgrade head` programmatically at the top of `main()`, after
`configure_logging` and **before** the SQLAlchemy engine is created.

Concurrency between processes is handled by SQLite's OS-level file lock:
whichever process acquires the lock first applies the pending revisions; the
loser sees no pending revisions and is a no-op.

If migrations fail, the process exits non-zero before opening the engine or
starting uvicorn. Same blast radius as a failed `yas-migrate` container today,
just located in the api/worker process.

### Components

**New code**

- `src/yas/db/migrations.py` — single function:

  ```python
  def upgrade_to_head(database_url: str) -> None:
      """Apply pending Alembic migrations against `database_url`.

      Idempotent — a no-op when the DB is already at head.
      """
  ```

  Implementation: builds an `alembic.config.Config` pointing at the bundled
  `alembic.ini`, overrides `sqlalchemy.url` via `cfg.set_main_option`, calls
  `alembic.command.upgrade(cfg, "head")`. Logs the resolved revision before
  and after so dev/prod logs are diagnosable.

**Modified code**

- `src/yas/__main__.py`:
  - Add `"migrate"` to the `mode` `choices`.
  - After `configure_logging(...)` and before `create_engine_for(...)`, call
    `upgrade_to_head(settings.database_url)`.
  - If `mode == "migrate"`, return 0 after migrations apply (no engine, no
    uvicorn, no worker).

**Removed / changed infra**

- `docker-compose.yml` — delete the `yas-migrate` service. Remove the
  `depends_on: yas-migrate` from `yas-worker` and `yas-api`. The
  `yas-worker → yas-migrate` and `yas-api → yas-migrate` edges go away;
  `yas-api → yas-worker` stays as-is (api still waits for worker to start).
- `docker-compose.dev.yml`, `docker-compose.macos.yml`,
  `docker-compose.smoke.yml` — audit and apply the same removal if they
  reference `yas-migrate`.
- `Dockerfile` — no change.

### Why every mode, not just api?

A "single designated owner" design (only `api` migrates; worker waits on
`/healthz`) was considered and rejected:

- Couples worker boot to api availability, which doesn't reflect the actual
  data dependency (worker needs the schema, not the API process).
- A developer running `python -m yas worker` directly during local
  development would skip migrations.
- The SQLite file lock already makes "everyone migrates" safe, so the extra
  ordering constraint buys nothing.

### Why programmatic Alembic, not a shell wrapper?

A `entrypoint.sh` that runs `alembic upgrade head && exec python -m yas $mode`
was considered. Rejected because it adds a shell layer and a second place
where the migration step lives, without any benefit over calling Alembic from
Python.

## Testing

- **Unit:** `upgrade_to_head` against a fresh tmp SQLite URL — assert tables
  created. Call it again on the same URL — assert no-op (idempotency).
- **Smoke:** existing `docker-compose.smoke.yml` boot flow should pass with
  `yas-migrate` removed.
- **Skipped:** no concurrent-upgrade test. SQLite lock behavior is a
  library-level guarantee; testing it here would be theater.

## Rollout

Single PR. Backward compatible for any operator pulling the new image with
their existing compose file — the old `yas-migrate` service still works
(its command becomes redundant, not broken).

Update `README.md` deployment section if it references `yas-migrate`
(needs a grep to confirm).
