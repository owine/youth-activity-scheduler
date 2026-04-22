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
