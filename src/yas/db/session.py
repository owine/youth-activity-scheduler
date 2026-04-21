"""Async engine + session helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# WAL + busy_timeout is the standard combo for one-writer / many-readers SQLite:
# WAL lets readers proceed while a write is in flight, and busy_timeout lets a
# would-be writer wait instead of failing with SQLITE_BUSY when another
# connection briefly holds the write lock.
_SQLITE_BUSY_TIMEOUT_MS = 5000


def create_engine_for(url: str) -> AsyncEngine:
    """Create an async engine. For SQLite URLs, installs WAL + busy-timeout pragmas."""
    is_sqlite = url.startswith("sqlite")
    engine = create_async_engine(
        url,
        # pre-ping is valuable for TCP pools (the other end may have closed),
        # but useless on a local SQLite file and adds a SELECT 1 per checkout.
        pool_pre_ping=not is_sqlite,
    )

    if is_sqlite:
        sync_engine: Engine = engine.sync_engine

        @event.listens_for(sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
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
