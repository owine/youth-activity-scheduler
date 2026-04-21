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
