"""Alembic upgrade test — runs migrations in-process, not via subprocess.

The test itself is synchronous. Alembic's env.py uses `asyncio.run()` internally
for the online (async-engine) path, so wrapping the whole test in @pytest.mark.asyncio
would collide with that. Sync is fine — we only need to verify table creation,
which sqlite3 from stdlib handles without an engine.
"""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

EXPECTED_TABLES = {
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


def test_alembic_upgrade_creates_all_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "mig.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("select name from sqlite_master where type='table'").fetchall()
    tables = {r[0] for r in rows}
    missing = EXPECTED_TABLES - tables
    assert not missing, f"missing tables after migration: {missing}"
