"""Quick sanity that the new worker loops can be started and cancelled cleanly."""

from __future__ import annotations

import asyncio

import pytest

from yas.config import Settings
from yas.db.base import Base
from yas.db.session import create_engine_for
from yas.worker.sweep import daily_sweep_loop


@pytest.mark.asyncio
async def test_daily_sweep_cancels_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/s.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # target time in the future so the loop just waits.
    settings = Settings(_env_file=None, sweep_time_utc="23:59")  # type: ignore[call-arg]
    task = asyncio.create_task(daily_sweep_loop(engine, settings))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await engine.dispose()
