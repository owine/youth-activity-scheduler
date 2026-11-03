"""Shared pytest fixtures."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture(autouse=True)
def _restore_logging_config() -> Iterator[None]:
    """Undo any test's global logging setup when it finishes.

    ``configure_logging`` (called by ``yas.__main__.main`` and by the logging
    tests) installs a filtering structlog wrapper and replaces the root
    handlers. Both are process-global, so without this a later test that
    asserts on a debug event via ``structlog.testing.capture_logs`` fails or
    passes depending on test order.
    """
    structlog_config = structlog.get_config()
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level
    try:
        yield
    finally:
        structlog.configure(**structlog_config)
        for handler in list(root.handlers):
            if handler not in handlers:
                root.removeHandler(handler)
        for handler in handlers:
            if handler not in root.handlers:
                root.addHandler(handler)
        root.setLevel(level)


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """A fresh SQLite database with the full schema, disposed after the test.

    Disposing matters: an engine left open keeps aiosqlite worker threads alive
    past the test's event loop, which surfaces later as "Event loop is closed"
    thread warnings attributed to unrelated tests.
    """
    from yas.db.base import Base
    from yas.db.session import create_engine_for

    eng = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def sentry_events(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Initialise Sentry through the production init path with an in-memory transport.

    Yields the list events land in. Imported lazily so the rest of the suite
    doesn't depend on the observability module.
    """
    from tests.fakes.sentry import TEST_DSN, CapturingTransport, reset_sentry
    from yas.config import Settings
    from yas.observability import init_sentry

    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("SENTRY_DSN", TEST_DSN)
    transport = CapturingTransport()
    assert init_sentry(Settings(_env_file=None), transport=transport)  # type: ignore[call-arg]
    try:
        yield transport.events
    finally:
        reset_sentry()
