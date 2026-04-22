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
