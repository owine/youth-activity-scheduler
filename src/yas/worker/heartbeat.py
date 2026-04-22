"""Worker-side heartbeat: upsert a single row on every tick.

Assumes a single writer. The select-then-insert is TOCTOU-racy if two workers
ever call `beat_once` against the same DB concurrently; Phase 1's Compose
topology runs exactly one `yas-worker` service, which keeps this safe. If a
second writer is ever added, switch to `INSERT ... ON CONFLICT(id) DO UPDATE`.
"""

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
