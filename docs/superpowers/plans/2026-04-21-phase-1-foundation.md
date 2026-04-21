# Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use @superpowers:subagent-driven-development (recommended) or @superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Follow @superpowers:test-driven-development throughout. Apply @superpowers:verification-before-completion before marking any task done.

**Goal:** Stand up the project skeleton: repo scaffold, dependencies, configuration, logging, SQLAlchemy models and migrations for every table in the spec, FastAPI health endpoints, worker heartbeat, Docker Compose with two services, and CI. At the end, `docker compose up` runs both services cleanly against an empty but schema-complete SQLite database.

**Architecture:** One Python package (`yas`) with a `__main__` entrypoint that boots `api`, `worker`, or `all`. Persistence via SQLAlchemy 2.0 + SQLite WAL + Alembic. Config via pydantic-settings (env-driven). Logs structured via structlog. Two Docker Compose services (`yas-api`, `yas-worker`) share the same image and a `./data` volume.

**Tech Stack:** Python 3.12, uv, ruff, mypy (strict on `src/`), pytest + pytest-asyncio, SQLAlchemy 2.0, Alembic, pydantic + pydantic-settings, FastAPI + uvicorn, structlog, Docker Compose.

**Reference spec:** `docs/superpowers/specs/2026-04-21-youth-activity-scheduler-design.md` (sections 3, 8).

---

## Deliverables (phase exit criteria)

- `uv sync` installs deps on a clean checkout
- `uv run pytest` runs all tests green, coverage on `src/yas`
- `uv run ruff check` and `uv run mypy src` pass cleanly
- `uv run alembic upgrade head` creates a database with **every table from spec §3**
- `uv run python -m yas api` starts FastAPI on port 8080; `GET /healthz` → `200 {"status":"ok"}`; `GET /readyz` → `200` when DB reachable and worker heartbeat is fresh, `503` otherwise
- `uv run python -m yas worker` runs an async loop that writes a heartbeat row every 10s and logs structured JSON
- `docker compose up` brings both services up, they share the same `./data/activities.db`, and health checks pass
- GitHub Actions CI on push runs lint + typecheck + tests green

## Conventions

- **TDD**: write the failing test first, watch it fail, implement, watch it pass, commit. No exceptions.
- **Commits**: conventional style (`feat:`, `test:`, `chore:`, `docs:`, `refactor:`). One commit per task unless explicitly split.
- **Imports**: absolute, `from yas.x import y`. No relative imports across submodules.
- **Typing**: everything in `src/` annotated; tests may omit return annotations on test functions.
- **Models**: all SQLAlchemy 2.0 style — `Mapped[T]` + `mapped_column(...)`. No legacy `Column(...)`.
- **Timestamps**: always stored as UTC, type `datetime` (SQLite stores as ISO8601). Never naive datetimes in Python — use `datetime.now(UTC)`.
- **Table creation**: schema lives in models and is emitted by Alembic migrations. Tests use Alembic to create schema, never `Base.metadata.create_all`.

---

## Task 1 — Repo scaffold and tooling

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.python-version`
- Create: `README.md`
- Create: `src/yas/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `.python-version`**

```
3.12
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "yas"
version = "0.1.0"
description = "Youth Activity Scheduler — self-hosted crawler + alerter for youth program sites"
requires-python = ">=3.12"
readme = "README.md"
dependencies = [
  "sqlalchemy>=2.0.30",
  "alembic>=1.13.1",
  "pydantic>=2.7.0",
  "pydantic-settings>=2.2.1",
  "fastapi>=0.110.0",
  "uvicorn[standard]>=0.29.0",
  "httpx>=0.27.0",
  "structlog>=24.1.0",
  "anthropic>=0.25.0",
  "jinja2>=3.1.3",
  "python-multipart>=0.0.9",
  "aiosqlite>=0.20.0",
]

[dependency-groups]
dev = [
  "pytest>=8.1.1",
  "pytest-asyncio>=0.23.6",
  "pytest-cov>=5.0.0",
  "respx>=0.21.1",
  "ruff>=0.4.0",
  "mypy>=1.10.0",
  "types-requests",
  "pre-commit>=3.7.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/yas"]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "RUF"]
ignore = ["E501"]  # let formatter handle line length

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["B", "SIM"]

[tool.ruff.format]
quote-style = "double"

[tool.mypy]
python_version = "3.12"
strict = true
files = ["src/yas"]
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false
disallow_incomplete_defs = false

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-ra --cov=yas --cov-report=term-missing"
```

- [ ] **Step 3: Create `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.coverage
.mypy_cache/
.ruff_cache/
data/
!data/.gitkeep
.env
.DS_Store
dist/
build/
*.egg-info/
```

- [ ] **Step 4: Create minimal `src/yas/__init__.py`**

```python
"""Youth Activity Scheduler."""

__version__ = "0.1.0"
```

- [ ] **Step 5: Create `tests/__init__.py` (empty) and `tests/conftest.py`**

`tests/conftest.py`:
```python
"""Shared pytest fixtures."""
```

- [ ] **Step 6: Create minimal `README.md`**

```markdown
# Youth Activity Scheduler (yas)

Self-hosted crawler + alerter for youth activity / sports / enrichment websites.

## Quickstart

See `docs/superpowers/specs/` for the design spec.

## Dev

```bash
uv sync
uv run pytest
```
```

- [ ] **Step 7: Install and verify**

Run: `uv sync`
Expected: dependencies resolve; `.venv/` created.

Run: `uv run pytest`
Expected: `collected 0 items ... no tests ran`.

Run: `uv run ruff check .`
Expected: `All checks passed!`

Run: `uv run mypy src`
Expected: `Success: no issues found in N source files` (or similar — the only source file is `__init__.py`).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .python-version .gitignore README.md src/ tests/
git commit -m "chore: scaffold python project with uv, ruff, mypy, pytest"
```

---

## Task 2 — Config module (pydantic-settings)

**Files:**
- Create: `src/yas/config.py`
- Create: `tests/unit/test_config.py`
- Create: `.env.example`

- [ ] **Step 1: Write the failing test**

`tests/unit/__init__.py`: empty file.

`tests/unit/test_config.py`:
```python
import pytest

from yas.config import Settings


def test_settings_load_defaults(monkeypatch):
    monkeypatch.delenv("YAS_DATABASE_URL", raising=False)
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = Settings()
    assert s.database_url == "sqlite+aiosqlite:////data/activities.db"
    assert s.anthropic_api_key == "sk-test"
    assert s.log_level == "INFO"
    assert s.host == "0.0.0.0"
    assert s.port == 8080


def test_settings_override_via_env(monkeypatch):
    monkeypatch.setenv("YAS_DATABASE_URL", "sqlite+aiosqlite:///tmp/x.db")
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setenv("YAS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("YAS_PORT", "9999")
    s = Settings()
    assert s.database_url == "sqlite+aiosqlite:///tmp/x.db"
    assert s.log_level == "DEBUG"
    assert s.port == 9999


def test_settings_requires_anthropic_key(monkeypatch):
    monkeypatch.delenv("YAS_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError):
        Settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL — `ImportError: yas.config`.

- [ ] **Step 3: Implement `src/yas/config.py`**

```python
"""Application configuration loaded from environment."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Storage
    database_url: str = "sqlite+aiosqlite:////data/activities.db"
    data_dir: str = "/data"

    # LLM
    anthropic_api_key: str = Field(..., description="Anthropic API key (required)")

    # HTTP server
    host: str = "0.0.0.0"
    port: int = 8080

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Worker
    worker_heartbeat_interval_s: int = 10
    worker_heartbeat_staleness_s: int = 60


def get_settings() -> Settings:
    """Factory so callers get a fresh read when needed (tests, reload)."""
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: all three tests PASS.

- [ ] **Step 5: Create `.env.example`**

```
# Required
YAS_ANTHROPIC_API_KEY=sk-ant-...

# Optional overrides
# YAS_DATABASE_URL=sqlite+aiosqlite:////data/activities.db
# YAS_LOG_LEVEL=INFO
# YAS_PORT=8080
```

- [ ] **Step 6: Commit**

```bash
git add src/yas/config.py tests/unit/ .env.example
git commit -m "feat(config): add pydantic-settings-backed Settings"
```

---

## Task 3 — Structured logging

**Files:**
- Create: `src/yas/logging.py`
- Create: `tests/unit/test_logging.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_logging.py`:
```python
import json
import logging

from yas.logging import configure_logging, get_logger


def test_configure_logging_emits_json(capsys):
    configure_logging(level="INFO")
    log = get_logger("test")
    log.info("hello", kid_id=42)
    captured = capsys.readouterr()
    # structlog default ProcessorFormatter routes through stdlib logging → stderr
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert lines, "no log output captured"
    payload = json.loads(lines[-1])
    assert payload["event"] == "hello"
    assert payload["kid_id"] == 42
    assert payload["level"] == "info"


def test_log_level_respected(capsys):
    configure_logging(level="WARNING")
    log = get_logger("test")
    log.info("invisible")
    log.warning("visible")
    captured = capsys.readouterr()
    assert "invisible" not in captured.err
    assert "visible" in captured.err


def test_get_logger_returns_structlog():
    configure_logging(level="INFO")
    log = get_logger("x")
    # BoundLogger has .bind()
    assert hasattr(log, "bind")


def teardown_function():
    # reset logging between tests
    for name in list(logging.root.manager.loggerDict):
        logging.getLogger(name).handlers.clear()
    logging.root.handlers.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_logging.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Implement `src/yas/logging.py`**

```python
"""Structured logging via structlog → stderr JSON."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog to emit JSON to stderr at the given level."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Reset any prior handlers (idempotent for tests).
    for existing in list(logging.root.handlers):
        logging.root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(numeric_level)
    logging.root.addHandler(handler)
    logging.root.setLevel(numeric_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_logging.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yas/logging.py tests/unit/test_logging.py
git commit -m "feat(logging): add structlog JSON logging to stderr"
```

---

## Task 4 — SQLAlchemy Base + session module

**Files:**
- Create: `src/yas/db/__init__.py`
- Create: `src/yas/db/base.py`
- Create: `src/yas/db/session.py`
- Create: `tests/unit/test_db_session.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_db_session.py`:
```python
import pytest
from sqlalchemy import text

from yas.db.session import create_engine_for, session_scope


@pytest.mark.asyncio
async def test_engine_executes_trivial_query(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        result = await conn.execute(text("select 1"))
        assert result.scalar() == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_session_scope_commits_on_success(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.execute(text("create table t (id integer primary key, v text)"))
    async with session_scope(engine) as session:
        await session.execute(text("insert into t (v) values ('hi')"))
    async with engine.begin() as conn:
        rows = (await conn.execute(text("select v from t"))).all()
        assert rows == [("hi",)]
    await engine.dispose()


@pytest.mark.asyncio
async def test_session_scope_rolls_back_on_error(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.execute(text("create table t (id integer primary key, v text)"))
    with pytest.raises(RuntimeError):
        async with session_scope(engine) as session:
            await session.execute(text("insert into t (v) values ('bad')"))
            raise RuntimeError("boom")
    async with engine.begin() as conn:
        rows = (await conn.execute(text("select v from t"))).all()
        assert rows == []
    await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_db_session.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Implement `src/yas/db/base.py`**

```python
"""Declarative base for all SQLAlchemy models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata for all yas ORM models."""
```

- [ ] **Step 4: Implement `src/yas/db/session.py`**

```python
"""Async engine + session helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_for(url: str) -> AsyncEngine:
    """Create an async engine with WAL mode enabled for SQLite."""
    connect_args: dict[str, object] = {}
    engine = create_async_engine(
        url,
        future=True,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

    if url.startswith("sqlite"):
        # WAL + sane defaults for the single-writer, multi-reader case.
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        sync_engine: Engine = engine.sync_engine

        @event.listens_for(sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return engine


@asynccontextmanager
async def session_scope(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Provide a transactional session that commits on success, rolls back on error."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

- [ ] **Step 5: Create `src/yas/db/__init__.py`**

```python
from yas.db.base import Base
from yas.db.session import create_engine_for, session_scope

__all__ = ["Base", "create_engine_for", "session_scope"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_db_session.py -v`
Expected: 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add src/yas/db/ tests/unit/test_db_session.py
git commit -m "feat(db): add async engine + session scope with WAL pragma"
```

---

## Task 5 — ORM models (spec §3)

Write all tables as SQLAlchemy 2.0 models with `Mapped[T]`. One file per concern, but all inherit from the shared `Base` so Alembic sees them together.

**Files:**
- Create: `src/yas/db/models/__init__.py`
- Create: `src/yas/db/models/_types.py`
- Create: `src/yas/db/models/household.py`
- Create: `src/yas/db/models/kid.py`
- Create: `src/yas/db/models/location.py`
- Create: `src/yas/db/models/site.py`
- Create: `src/yas/db/models/page.py`
- Create: `src/yas/db/models/offering.py`
- Create: `src/yas/db/models/extraction_cache.py`
- Create: `src/yas/db/models/match.py`
- Create: `src/yas/db/models/watchlist.py`
- Create: `src/yas/db/models/alert.py`
- Create: `src/yas/db/models/alert_routing.py`
- Create: `src/yas/db/models/crawl_run.py`
- Create: `src/yas/db/models/unavailability_block.py`
- Create: `src/yas/db/models/enrollment.py`
- Create: `src/yas/db/models/worker_heartbeat.py`
- Create: `tests/unit/test_models_import.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_models_roundtrip.py`

- [ ] **Step 1: Write a failing import test**

`tests/unit/test_models_import.py`:
```python
from yas.db.models import (
    Alert,
    AlertRouting,
    CrawlRun,
    Enrollment,
    ExtractionCache,
    HouseholdSettings,
    Kid,
    Location,
    Match,
    Offering,
    Page,
    Site,
    UnavailabilityBlock,
    WatchlistEntry,
    WorkerHeartbeat,
)


def test_all_models_importable():
    # A sanity smoke — they must all be Base subclasses with a __tablename__.
    for cls in [
        Alert,
        AlertRouting,
        CrawlRun,
        Enrollment,
        ExtractionCache,
        HouseholdSettings,
        Kid,
        Location,
        Match,
        Offering,
        Page,
        Site,
        UnavailabilityBlock,
        WatchlistEntry,
        WorkerHeartbeat,
    ]:
        assert hasattr(cls, "__tablename__"), f"{cls.__name__} has no __tablename__"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_models_import.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Create shared type helpers in `src/yas/db/models/_types.py`**

```python
"""Shared column types and enums for models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.orm import mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def timestamp_column(nullable: bool = False, default_now: bool = True) -> Any:
    """Return a timezone-aware DateTime column with a UTC-now default.

    Returns `Any` because SQLAlchemy's `mapped_column()` return type narrows
    to `Mapped[T]` only once the caller annotates the attribute; this helper
    is intended to be used on the RHS of a `Mapped[datetime]` annotation.
    """
    kwargs: dict[str, Any] = {"nullable": nullable}
    if default_now:
        kwargs["server_default"] = func.current_timestamp()
        kwargs["default"] = utcnow
    return mapped_column(DateTime(timezone=True), **kwargs)


class ProgramType(StrEnum):
    soccer = "soccer"
    swim = "swim"
    martial_arts = "martial_arts"
    art = "art"
    music = "music"
    stem = "stem"
    dance = "dance"
    gym = "gym"
    multisport = "multisport"
    outdoor = "outdoor"
    academic = "academic"
    camp_general = "camp_general"
    unknown = "unknown"


class PageKind(StrEnum):
    schedule = "schedule"
    registration = "registration"
    list = "list"
    other = "other"


class OfferingStatus(StrEnum):
    active = "active"
    ended = "ended"
    withdrawn = "withdrawn"


class AlertType(StrEnum):
    watchlist_hit = "watchlist_hit"
    new_match = "new_match"
    reg_opens_24h = "reg_opens_24h"
    reg_opens_1h = "reg_opens_1h"
    reg_opens_now = "reg_opens_now"
    schedule_posted = "schedule_posted"
    crawl_failed = "crawl_failed"
    digest = "digest"


class WatchlistPriority(StrEnum):
    high = "high"
    normal = "normal"


class CrawlStatus(StrEnum):
    ok = "ok"
    failed = "failed"
    skipped = "skipped"


class UnavailabilitySource(StrEnum):
    manual = "manual"
    school = "school"
    enrollment = "enrollment"
    custom = "custom"


class EnrollmentStatus(StrEnum):
    interested = "interested"
    enrolled = "enrolled"
    waitlisted = "waitlisted"
    completed = "completed"
    cancelled = "cancelled"
```

- [ ] **Step 4: Implement `household.py`**

```python
"""Single-row household-wide settings."""

from __future__ import annotations

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base


class HouseholdSettings(Base):
    __tablename__ = "household_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    home_location_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_max_distance_mi: Mapped[float | None] = mapped_column(nullable=True)
    digest_time: Mapped[str] = mapped_column(String, default="07:00")
    quiet_hours_start: Mapped[str | None] = mapped_column(String, nullable=True)
    quiet_hours_end: Mapped[str | None] = mapped_column(String, nullable=True)
    daily_llm_cost_cap_usd: Mapped[float] = mapped_column(default=1.0)
    smtp_config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ha_config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ntfy_config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 5: Implement `location.py`**

```python
"""Physical locations — home address and offering venues."""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    lat: Mapped[float | None] = mapped_column(nullable=True)
    lon: Mapped[float | None] = mapped_column(nullable=True)
```

- [ ] **Step 6: Implement `kid.py`**

```python
"""Per-kid profile."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import JSON, Date, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import timestamp_column


class Kid(Base):
    __tablename__ = "kids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    dob: Mapped[date] = mapped_column(Date, nullable=False)
    interests: Mapped[list[str]] = mapped_column(JSON, default=list)
    availability: Mapped[dict] = mapped_column(JSON, default=dict)
    max_distance_mi: Mapped[float | None] = mapped_column(nullable=True)
    alert_score_threshold: Mapped[float] = mapped_column(default=0.6)
    alert_on: Mapped[dict] = mapped_column(JSON, default=dict)
    # School schedule — source of truth; unavailability_blocks with source=school
    # are materialized from these fields by the matcher layer (Phase 3).
    school_weekdays: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["mon", "tue", "wed", "thu", "fri"]
    )
    school_time_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    school_time_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    school_year_ranges: Mapped[list[dict]] = mapped_column(JSON, default=list)
    school_holidays: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = timestamp_column()
```

- [ ] **Step 7: Implement `site.py`**

```python
"""Crawl targets."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import timestamp_column


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    adapter: Mapped[str] = mapped_column(String, default="llm")
    needs_browser: Mapped[bool] = mapped_column(default=False)
    crawl_hints: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(default=True)
    default_cadence_s: Mapped[int] = mapped_column(Integer, default=6 * 3600)
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_column()
```

- [ ] **Step 8: Implement `page.py`**

```python
"""Per-URL tracked pages within a site."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import PageKind


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[PageKind] = mapped_column(String, default=PageKind.schedule.value)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    last_fetched: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_changed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
```

- [ ] **Step 9: Implement `offering.py`**

```python
"""Structured program offerings extracted from pages."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import OfferingStatus, ProgramType, timestamp_column


class Offering(Base):
    __tablename__ = "offerings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    age_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    program_type: Mapped[ProgramType] = mapped_column(String, default=ProgramType.unknown.value)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    days_of_week: Mapped[list[str]] = mapped_column(JSON, default=list)
    time_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    time_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registration_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registration_url: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen: Mapped[datetime] = timestamp_column()
    last_seen: Mapped[datetime] = timestamp_column()
    status: Mapped[OfferingStatus] = mapped_column(String, default=OfferingStatus.active.value)
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 10: Implement `extraction_cache.py`**

```python
"""LLM extraction cache keyed by content hash."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import timestamp_column


class ExtractionCache(Base):
    __tablename__ = "extraction_cache"

    content_hash: Mapped[str] = mapped_column(String, primary_key=True)
    extracted_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    llm_model: Mapped[str] = mapped_column(String, nullable=False)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    extracted_at: Mapped[datetime] = timestamp_column()
```

- [ ] **Step 11: Implement `match.py`**

```python
"""Precomputed kid↔offering matches."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import timestamp_column


class Match(Base):
    __tablename__ = "matches"

    kid_id: Mapped[int] = mapped_column(ForeignKey("kids.id", ondelete="CASCADE"), primary_key=True)
    offering_id: Mapped[int] = mapped_column(
        ForeignKey("offerings.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[float] = mapped_column(nullable=False)
    reasons: Mapped[dict] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = timestamp_column()
```

- [ ] **Step 12: Implement `watchlist.py`**

```python
"""Per-kid watchlist entries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import WatchlistPriority, timestamp_column


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kid_id: Mapped[int] = mapped_column(ForeignKey("kids.id", ondelete="CASCADE"))
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=True
    )
    pattern: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[WatchlistPriority] = mapped_column(
        String, default=WatchlistPriority.normal.value
    )
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    ignore_hard_gates: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = timestamp_column()
```

- [ ] **Step 12b: Implement `unavailability_block.py`**

```python
"""Per-kid unavailability: school, enrollments, manual, custom."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import JSON, Date, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import UnavailabilitySource, timestamp_column


class UnavailabilityBlock(Base):
    __tablename__ = "unavailability_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kid_id: Mapped[int] = mapped_column(ForeignKey("kids.id", ondelete="CASCADE"), index=True)
    source: Mapped[UnavailabilitySource] = mapped_column(String, default=UnavailabilitySource.manual.value)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    days_of_week: Mapped[list[str]] = mapped_column(JSON, default=list)
    time_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    time_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    date_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_enrollment_id: Mapped[int | None] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=True
    )
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = timestamp_column()
```

- [ ] **Step 12c: Implement `enrollment.py`**

```python
"""Committing to an offering: drives unavailability block materialization."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import EnrollmentStatus, timestamp_column


class Enrollment(Base):
    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kid_id: Mapped[int] = mapped_column(ForeignKey("kids.id", ondelete="CASCADE"), index=True)
    offering_id: Mapped[int] = mapped_column(
        ForeignKey("offerings.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[EnrollmentStatus] = mapped_column(
        String, default=EnrollmentStatus.interested.value
    )
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = timestamp_column()
```

- [ ] **Step 13: Implement `alert.py`**

```python
"""Outbound alert queue."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import AlertType


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[AlertType] = mapped_column(String, nullable=False, index=True)
    kid_id: Mapped[int | None] = mapped_column(
        ForeignKey("kids.id", ondelete="SET NULL"), nullable=True
    )
    offering_id: Mapped[int | None] = mapped_column(
        ForeignKey("offerings.id", ondelete="SET NULL"), nullable=True
    )
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True
    )
    channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    skipped: Mapped[bool] = mapped_column(default=False)
    dedup_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_alerts_unsent_due", "scheduled_for", "sent_at"),
    )
```

- [ ] **Step 14: Implement `alert_routing.py`**

```python
"""Editable alert routing config."""

from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import AlertType


class AlertRouting(Base):
    __tablename__ = "alert_routing"

    type: Mapped[AlertType] = mapped_column(String, primary_key=True)
    channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(default=True)
```

- [ ] **Step 15: Implement `crawl_run.py`**

```python
"""Per-crawl observability row."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import CrawlStatus


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[CrawlStatus] = mapped_column(String, default=CrawlStatus.ok.value)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    changes_detected: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    llm_cost_usd: Mapped[float] = mapped_column(default=0.0)
    error_text: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 16: Implement `worker_heartbeat.py`**

```python
"""Single-row worker liveness marker used by /readyz."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeat"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    worker_name: Mapped[str] = mapped_column(String, default="main")
    last_beat: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 17: Populate `src/yas/db/models/__init__.py`**

```python
from yas.db.models.alert import Alert
from yas.db.models.alert_routing import AlertRouting
from yas.db.models.crawl_run import CrawlRun
from yas.db.models.enrollment import Enrollment
from yas.db.models.extraction_cache import ExtractionCache
from yas.db.models.household import HouseholdSettings
from yas.db.models.kid import Kid
from yas.db.models.location import Location
from yas.db.models.match import Match
from yas.db.models.offering import Offering
from yas.db.models.page import Page
from yas.db.models.site import Site
from yas.db.models.unavailability_block import UnavailabilityBlock
from yas.db.models.watchlist import WatchlistEntry
from yas.db.models.worker_heartbeat import WorkerHeartbeat

__all__ = [
    "Alert",
    "AlertRouting",
    "CrawlRun",
    "Enrollment",
    "ExtractionCache",
    "HouseholdSettings",
    "Kid",
    "Location",
    "Match",
    "Offering",
    "Page",
    "Site",
    "UnavailabilityBlock",
    "WatchlistEntry",
    "WorkerHeartbeat",
]
```

- [ ] **Step 18: Run import test**

Run: `uv run pytest tests/unit/test_models_import.py -v`
Expected: PASS.

- [ ] **Step 19: Write an integration round-trip test (creates schema via `Base.metadata.create_all` for isolation — Alembic migration comes next task and will be the production schema source)**

`tests/integration/test_models_roundtrip.py`:
```python
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from yas.db.base import Base
from yas.db.models import Kid, Offering, Page, Site
from yas.db.session import create_engine_for, session_scope


@pytest.mark.asyncio
async def test_kid_roundtrip(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(name="Sam", dob=date(2019, 5, 1), interests=["soccer", "art"]))
    async with session_scope(engine) as s:
        result = await s.execute(text("select name, dob, interests from kids"))
        row = result.one()
        assert row.name == "Sam"
    await engine.dispose()


@pytest.mark.asyncio
async def test_site_page_offering_roundtrip(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        site = Site(name="Park District", base_url="https://example.com")
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="https://example.com/schedule")
        s.add(page)
        await s.flush()
        s.add(
            Offering(
                site_id=site.id,
                page_id=page.id,
                name="Little Kickers",
                normalized_name="little kickers",
                age_min=5,
                age_max=8,
            )
        )
    async with session_scope(engine) as s:
        rows = (await s.execute(text("select name, age_min, age_max from offerings"))).all()
        assert rows == [("Little Kickers", 5, 8)]
    await engine.dispose()
```

- [ ] **Step 20: Run integration tests**

Run: `uv run pytest tests/integration/ -v`
Expected: 2 PASS.

- [ ] **Step 21: Verify lint + types**

Run: `uv run ruff check . && uv run mypy src`
Expected: both clean.

- [ ] **Step 22: Commit**

```bash
git add src/yas/db/models/ tests/unit/test_models_import.py tests/integration/
git commit -m "feat(db): add ORM models for all tables in spec §3"
```

---

## Task 6 — Alembic initial migration

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_initial.py` (generated, then reviewed)
- Create: `tests/integration/test_migrations.py`

- [ ] **Step 1: Initialize Alembic**

Run: `uv run alembic init -t async alembic`
Expected: creates `alembic/` and `alembic.ini`.

- [ ] **Step 2: Edit `alembic.ini`** — set `sqlalchemy.url` to a placeholder and point `script_location`.

Replace `sqlalchemy.url = ...` line with:
```
sqlalchemy.url = sqlite+aiosqlite:////data/activities.db
```

And ensure `script_location = alembic` (default).

- [ ] **Step 3: Edit `alembic/env.py`** to import models and use our Settings URL.

Replace the file with:
```python
"""Alembic environment — async, reads URL from yas.config at runtime."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.engine import Connection

from yas.config import get_settings
from yas.db.base import Base
from yas.db.models import (  # noqa: F401  ensure all models register metadata
    Alert,
    AlertRouting,
    CrawlRun,
    Enrollment,
    ExtractionCache,
    HouseholdSettings,
    Kid,
    Location,
    Match,
    Offering,
    Page,
    Site,
    UnavailabilityBlock,
    WatchlistEntry,
    WorkerHeartbeat,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 4: Generate the initial migration**

Ensure `YAS_ANTHROPIC_API_KEY` is set in the shell (any value is fine for migration generation):
```bash
export YAS_ANTHROPIC_API_KEY=sk-test-nonop
mkdir -p data
```

Run: `uv run alembic revision --autogenerate -m "initial schema"`
Expected: a file `alembic/versions/<hash>_initial_schema.py` appears.

- [ ] **Step 5: Review and rename the migration**

Rename to `alembic/versions/0001_initial.py` (keeping the auto-generated filename prefix if alembic enforces it is fine — but prefer a deterministic filename). Update `revision` inside to `"0001_initial"` and `down_revision = None`. Verify all 15 tables are in `op.create_table(...)` calls.

- [ ] **Step 6: Apply migration to a scratch DB**

```bash
rm -f data/activities.db
uv run alembic upgrade head
sqlite3 data/activities.db ".tables"
```

Expected: lists all 15 tables plus `alembic_version`.

- [ ] **Step 7: Write a migration round-trip test**

`tests/integration/test_migrations.py`:
```python
import subprocess

import pytest
from sqlalchemy import text

from yas.db.session import create_engine_for


@pytest.mark.asyncio
async def test_alembic_upgrade_creates_all_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "mig.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")

    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True)

    expected = {
        "alerts",
        "alert_routing",
        "crawl_runs",
        "enrollments",
        "extraction_cache",
        "household_settings",
        "kids",
        "locations",
        "matches",
        "offerings",
        "pages",
        "sites",
        "unavailability_blocks",
        "watchlist_entries",
        "worker_heartbeat",
    }
    engine = create_engine_for(url)
    async with engine.connect() as conn:
        rows = (
            await conn.execute(text("select name from sqlite_master where type='table'"))
        ).all()
    tables = {r[0] for r in rows}
    missing = expected - tables
    assert not missing, f"missing tables after migration: {missing}"
    await engine.dispose()
```

- [ ] **Step 8: Run migration test**

Run: `uv run pytest tests/integration/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add alembic.ini alembic/ tests/integration/test_migrations.py
git commit -m "feat(db): add Alembic with initial schema migration"
```

---

## Task 7 — FastAPI app + /healthz + /readyz

**Files:**
- Create: `src/yas/web/__init__.py`
- Create: `src/yas/web/app.py`
- Create: `src/yas/web/deps.py`
- Create: `src/yas/health.py`
- Create: `tests/integration/test_health.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_health.py`:
```python
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from yas.db.base import Base
from yas.db.models import WorkerHeartbeat
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def app_with_db(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path}/h.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine)
    yield app, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_healthz_returns_ok(app_with_db):
    app, _ = app_with_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz_503_when_no_heartbeat(app_with_db):
    app, _ = app_with_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/readyz")
    assert r.status_code == 503
    assert r.json()["heartbeat_fresh"] is False


@pytest.mark.asyncio
async def test_readyz_200_when_fresh_heartbeat(app_with_db):
    app, engine = app_with_db
    async with session_scope(engine) as s:
        s.add(WorkerHeartbeat(id=1, worker_name="main", last_beat=datetime.now(UTC)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["heartbeat_fresh"] is True
    assert body["db_reachable"] is True


@pytest.mark.asyncio
async def test_readyz_503_when_stale_heartbeat(app_with_db):
    app, engine = app_with_db
    async with session_scope(engine) as s:
        s.add(
            WorkerHeartbeat(
                id=1,
                worker_name="main",
                last_beat=datetime.now(UTC) - timedelta(seconds=600),
            )
        )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/readyz")
    assert r.status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_health.py -v`
Expected: FAIL — imports missing.

- [ ] **Step 3: Implement `src/yas/health.py`**

```python
"""Readiness checks shared by API and CLI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.db.models import WorkerHeartbeat


@dataclass(frozen=True)
class Readiness:
    db_reachable: bool
    heartbeat_fresh: bool
    heartbeat_age_s: float | None

    @property
    def ready(self) -> bool:
        return self.db_reachable and self.heartbeat_fresh


async def check_readiness(engine: AsyncEngine, staleness_s: int) -> Readiness:
    db_ok = False
    hb_fresh = False
    hb_age: float | None = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
            db_ok = True
            row = (
                await conn.execute(
                    select(WorkerHeartbeat.last_beat).order_by(WorkerHeartbeat.id).limit(1)
                )
            ).first()
            if row is not None and row[0] is not None:
                last = row[0]
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                hb_age = (datetime.now(UTC) - last).total_seconds()
                hb_fresh = hb_age <= staleness_s
    except Exception:  # noqa: BLE001 — surface as not-ready
        db_ok = False
    return Readiness(db_reachable=db_ok, heartbeat_fresh=hb_fresh, heartbeat_age_s=hb_age)
```

- [ ] **Step 4: Implement `src/yas/web/deps.py`**

```python
"""Shared FastAPI dependencies."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings


class AppState:
    def __init__(self, engine: AsyncEngine, settings: Settings) -> None:
        self.engine = engine
        self.settings = settings
```

- [ ] **Step 5: Implement `src/yas/web/app.py`**

```python
"""FastAPI app factory."""

from __future__ import annotations

from fastapi import FastAPI, Response
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings, get_settings
from yas.db.session import create_engine_for
from yas.health import check_readiness
from yas.web.deps import AppState


def create_app(
    engine: AsyncEngine | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    app = FastAPI(title="yas", version="0.1.0")
    s = settings or get_settings()
    e = engine or create_engine_for(s.database_url)
    state = AppState(engine=e, settings=s)
    app.state.yas = state

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(response: Response) -> dict[str, object]:
        readiness = await check_readiness(state.engine, state.settings.worker_heartbeat_staleness_s)
        response.status_code = 200 if readiness.ready else 503
        return {
            "db_reachable": readiness.db_reachable,
            "heartbeat_fresh": readiness.heartbeat_fresh,
            "heartbeat_age_s": readiness.heartbeat_age_s,
        }

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await state.engine.dispose()

    return app
```

- [ ] **Step 6: Empty `src/yas/web/__init__.py`**

```python
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/integration/test_health.py -v`
Expected: 4 PASS.

- [ ] **Step 8: Commit**

```bash
git add src/yas/web/ src/yas/health.py tests/integration/test_health.py
git commit -m "feat(web): add FastAPI app with /healthz and /readyz"
```

---

## Task 8 — Worker heartbeat loop

**Files:**
- Create: `src/yas/worker/__init__.py`
- Create: `src/yas/worker/heartbeat.py`
- Create: `src/yas/worker/runner.py`
- Create: `tests/unit/test_heartbeat.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_heartbeat.py`:
```python
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import WorkerHeartbeat
from yas.db.session import create_engine_for, session_scope
from yas.worker.heartbeat import beat_once


@pytest.mark.asyncio
async def test_beat_once_inserts_then_updates(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/b.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    t1 = await beat_once(engine, worker_name="main")
    async with session_scope(engine) as s:
        row = (await s.execute(select(WorkerHeartbeat))).scalar_one()
        assert row.worker_name == "main"
        assert row.last_beat.replace(tzinfo=UTC) <= datetime.now(UTC)

    t2 = await beat_once(engine, worker_name="main")
    assert t2 >= t1
    async with session_scope(engine) as s:
        # still exactly one row
        n = (await s.execute(select(WorkerHeartbeat))).all()
        assert len(n) == 1
    await engine.dispose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_heartbeat.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Implement `src/yas/worker/heartbeat.py`**

```python
"""Worker-side heartbeat: upsert a single row on every tick."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.db.models import WorkerHeartbeat
from yas.db.session import session_scope


async def beat_once(engine: AsyncEngine, worker_name: str = "main") -> datetime:
    """Insert or update the single heartbeat row; return the timestamp written."""
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        existing = (await s.execute(select(WorkerHeartbeat).limit(1))).scalar_one_or_none()
        if existing is None:
            s.add(WorkerHeartbeat(id=1, worker_name=worker_name, last_beat=now))
        else:
            existing.last_beat = now
            existing.worker_name = worker_name
    return now
```

- [ ] **Step 4: Implement `src/yas/worker/runner.py`**

```python
"""Worker runner — async loop that drives heartbeat and (later) pipeline stages."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings
from yas.logging import get_logger
from yas.worker.heartbeat import beat_once

log = get_logger("yas.worker")


async def run_worker(engine: AsyncEngine, settings: Settings) -> None:
    """Main worker loop. Task 8 implements heartbeat only; later tasks add stages."""
    log.info("worker.start", interval_s=settings.worker_heartbeat_interval_s)
    try:
        while True:
            ts = await beat_once(engine)
            log.debug("worker.heartbeat", ts=ts.isoformat())
            await asyncio.sleep(settings.worker_heartbeat_interval_s)
    except asyncio.CancelledError:
        log.info("worker.stop")
        raise
```

- [ ] **Step 5: Empty `src/yas/worker/__init__.py`**

- [ ] **Step 6: Run the heartbeat test**

Run: `uv run pytest tests/unit/test_heartbeat.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/yas/worker/ tests/unit/test_heartbeat.py
git commit -m "feat(worker): add heartbeat loop and runner skeleton"
```

---

## Task 9 — `python -m yas` entrypoint

**Files:**
- Create: `src/yas/__main__.py`
- Create: `tests/unit/test_entrypoint.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_entrypoint.py`:
```python
import os
import subprocess
import sys


def test_main_prints_usage_when_no_mode():
    r = subprocess.run(
        [sys.executable, "-m", "yas"],
        capture_output=True,
        text=True,
        env={**os.environ, "YAS_ANTHROPIC_API_KEY": "sk-test"},
    )
    assert r.returncode != 0
    assert "usage" in (r.stderr + r.stdout).lower()


def test_main_accepts_known_modes():
    # We don't actually run api/worker here (they block). Just check arg parsing
    # by calling --help which short-circuits before booting anything.
    r = subprocess.run(
        [sys.executable, "-m", "yas", "--help"],
        capture_output=True,
        text=True,
        env={**os.environ, "YAS_ANTHROPIC_API_KEY": "sk-test"},
    )
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    for mode in ("api", "worker", "all"):
        assert mode in combined
```

- [ ] **Step 2: Run to verify fails**

Run: `uv run pytest tests/unit/test_entrypoint.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `src/yas/__main__.py`**

```python
"""CLI entrypoint: `python -m yas {api|worker|all}`."""

from __future__ import annotations

import argparse
import asyncio
import sys

import uvicorn

from yas.config import get_settings
from yas.db.session import create_engine_for
from yas.logging import configure_logging, get_logger
from yas.web.app import create_app
from yas.worker.runner import run_worker


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="yas", description="Youth Activity Scheduler")
    p.add_argument(
        "mode",
        choices=["api", "worker", "all"],
        help="which process to run: api (FastAPI), worker (crawler+alerts), all (both)",
    )
    return p


async def _run_all(settings, engine) -> None:  # type: ignore[no-untyped-def]
    """Run worker in a task alongside uvicorn in-process."""
    config = uvicorn.Config(
        create_app(engine=engine, settings=settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
    )
    server = uvicorn.Server(config)
    worker_task = asyncio.create_task(run_worker(engine, settings))
    try:
        await server.serve()
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(level=settings.log_level)
    log = get_logger("yas.main")
    engine = create_engine_for(settings.database_url)

    if args.mode == "api":
        log.info("mode.api", host=settings.host, port=settings.port)
        uvicorn.run(
            create_app(engine=engine, settings=settings),
            host=settings.host,
            port=settings.port,
            log_config=None,
        )
    elif args.mode == "worker":
        log.info("mode.worker")
        asyncio.run(run_worker(engine, settings))
    elif args.mode == "all":
        log.info("mode.all")
        asyncio.run(_run_all(settings, engine))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run entrypoint tests**

Run: `uv run pytest tests/unit/test_entrypoint.py -v`
Expected: PASS.

- [ ] **Step 5: Smoke-test API mode manually (cleanup after)**

```bash
export YAS_ANTHROPIC_API_KEY=sk-test
export YAS_DATABASE_URL=sqlite+aiosqlite:///data/activities.db
uv run alembic upgrade head
uv run python -m yas api &
sleep 2
curl -s localhost:8080/healthz
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/readyz
kill %1
```
Expected: `{"status":"ok"}` from `/healthz`, `503` from `/readyz` (no worker yet).

- [ ] **Step 6: Commit**

```bash
git add src/yas/__main__.py tests/unit/test_entrypoint.py
git commit -m "feat: add python -m yas {api|worker|all} entrypoint"
```

---

## Task 10 — Dockerfile

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Create `.dockerignore`**

```
.venv
.git
.github
__pycache__
.pytest_cache
.mypy_cache
.ruff_cache
tests
docs
data
.env
.DS_Store
dist
build
*.egg-info
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.4.18 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev || uv sync --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN mkdir -p /data

ENV YAS_DATABASE_URL=sqlite+aiosqlite:////data/activities.db \
    YAS_DATA_DIR=/data \
    PYTHONPATH=/app/src

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD curl -fsS http://localhost:8080/healthz || exit 1

CMD ["python", "-m", "yas", "all"]
```

- [ ] **Step 3: Build the image**

Run: `docker build -t yas:dev .`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "chore: add Dockerfile"
```

---

## Task 11 — docker-compose.yml

**Files:**
- Create: `docker-compose.yml`
- Create: `data/.gitkeep`

- [ ] **Step 1: Create `data/.gitkeep`**

Empty file.

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
services:
  yas-migrate:
    build: .
    command: ["uv", "run", "alembic", "upgrade", "head"]
    env_file: .env
    volumes:
      - ./data:/data
    restart: "no"

  yas-worker:
    build: .
    command: ["python", "-m", "yas", "worker"]
    env_file: .env
    volumes:
      - ./data:/data
    depends_on:
      yas-migrate:
        condition: service_completed_successfully
    restart: unless-stopped

  yas-api:
    build: .
    command: ["python", "-m", "yas", "api"]
    env_file: .env
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    depends_on:
      yas-migrate:
        condition: service_completed_successfully
      yas-worker:
        condition: service_started
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 3s
      retries: 3
```

- [ ] **Step 3: End-to-end smoke test**

```bash
cp .env.example .env
echo "YAS_ANTHROPIC_API_KEY=sk-test-nonop" >> .env
docker compose build
docker compose up -d yas-migrate
docker compose logs yas-migrate   # should show "INFO [alembic.runtime.migration] Running upgrade"
docker compose up -d yas-worker yas-api
sleep 15
curl -s localhost:8080/healthz
curl -s localhost:8080/readyz
docker compose down
```

Expected: `/healthz` returns `{"status":"ok"}`; `/readyz` returns `200` with `heartbeat_fresh: true`.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml data/.gitkeep
git commit -m "chore: add docker-compose with migrate+worker+api services"
```

---

## Task 12 — Pre-commit and CI

**Files:**
- Create: `.pre-commit-config.yaml`
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        args: [--config-file=pyproject.toml]
        additional_dependencies:
          - pydantic>=2.7
          - pydantic-settings>=2.2
          - sqlalchemy>=2.0
          - fastapi
          - structlog
```

- [ ] **Step 2: Create `.github/workflows/ci.yml`**

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:
jobs:
  check:
    runs-on: ubuntu-latest
    env:
      YAS_ANTHROPIC_API_KEY: sk-test-nonop
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - name: Set up Python
        run: uv python install 3.12
      - name: Install deps
        run: uv sync --all-extras --dev
      - name: Lint
        run: uv run ruff check .
      - name: Format check
        run: uv run ruff format --check .
      - name: Typecheck
        run: uv run mypy src
      - name: Migrations apply cleanly
        run: |
          mkdir -p data
          uv run alembic upgrade head
      - name: Tests
        run: uv run pytest -v
```

- [ ] **Step 3: Local verification**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add .pre-commit-config.yaml .github/
git commit -m "chore(ci): add pre-commit and GitHub Actions workflow"
```

---

## Task 13 — README quickstart & finalize

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update `README.md`**

Replace contents with:
```markdown
# Youth Activity Scheduler (yas)

Self-hosted crawler + alerter for youth activity / sports / enrichment websites.
See `docs/superpowers/specs/` for the design spec.

## Quickstart (Docker)

```bash
cp .env.example .env
echo "YAS_ANTHROPIC_API_KEY=sk-ant-…" >> .env
docker compose up -d
curl http://localhost:8080/healthz
```

## Quickstart (local)

```bash
uv sync
cp .env.example .env
echo "YAS_ANTHROPIC_API_KEY=sk-ant-…" >> .env
mkdir -p data
uv run alembic upgrade head
uv run python -m yas all
```

## Development

```bash
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy src        # typecheck
```

## Project layout

```
src/yas/
  config.py        pydantic-settings
  logging.py       structlog setup
  __main__.py      CLI entrypoint (api|worker|all)
  db/              SQLAlchemy models + session
  web/             FastAPI app
  worker/          background loop
alembic/           DB migrations
tests/             pytest suite
```
```

- [ ] **Step 2: Final full verification**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -v
```
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add quickstart and layout to README"
```

---

## Phase 1 exit checklist

Apply @superpowers:verification-before-completion before declaring this phase done. Every box below must be verified with an actual command, not asserted.

- [ ] `uv sync` clean on fresh clone
- [ ] `uv run pytest` all green, no skips beyond known (none expected)
- [ ] `uv run ruff check .` clean
- [ ] `uv run ruff format --check .` clean
- [ ] `uv run mypy src` clean
- [ ] `uv run alembic upgrade head` produces a DB with all 15 tables
- [ ] `docker compose up -d` brings up both services; `/healthz` = 200; `/readyz` = 200 within 60s
- [ ] GitHub Actions CI passes on the PR or main
- [ ] Spec §3 every table exists in models and in the initial migration
- [ ] No TODOs/FIXMEs left in `src/`

When all boxes check, Phase 1 is complete. Proceed to **Phase 2 — Crawl pipeline MVP**, which will be written as its own plan document against this foundation.

### What Phase 1 deliberately does NOT include

- **School-block materialization.** `Kid.school_*` fields exist and are stored, but the logic that derives `unavailability_blocks` rows with `source=school` is Phase 3 (matching). Phase 1 only establishes the schema.
- **Enrollment → unavailability auto-linking.** Same — data model exists, trigger logic lands in Phase 3.
- **No-conflict hard gate.** Implemented in Phase 3 alongside the rest of the matcher.
- **Calendar UI page.** Phase 5.

This split keeps Phase 1 strictly about schema + process skeleton and avoids tangling matching logic into the foundation plan.
