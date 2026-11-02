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
    "geocode_attempts",
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


def test_upgrade_clears_not_found_geocodes_recorded_before_456(tmp_path, monkeypatch):
    """Before #456's fix, outages were recorded as permanent not_found. They can't be
    told apart from genuine misses, so the upgrade drops them all for one re-check;
    genuine misses are simply recorded again."""
    db_path = tmp_path / "mig.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006_kid_max_drive_minutes")

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "insert into geocode_attempts (address_norm, last_tried, result) values (?, ?, ?)",
            [
                ("outage victim", "2026-09-01 00:00:00", "not_found"),
                ("geocoded", "2026-09-01 00:00:00", "ok"),
                ("bug", "2026-09-01 00:00:00", "error"),
            ],
        )

    command.upgrade(cfg, "head")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("select address_norm, result from geocode_attempts").fetchall()
    assert sorted(rows) == [("bug", "error"), ("geocoded", "ok")]


def test_upgrade_drops_matches_of_withdrawn_offerings(tmp_path, monkeypatch):
    """Withdrawn offerings kept their match rows, which every match reader showed."""
    db_path = tmp_path / "mig.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0007_retry_not_found_geocodes")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "insert into sites (id, name, base_url, adapter, needs_browser, crawl_hints,"
            " active, default_cadence_s) values (1, 's', 'https://s', 'llm', 0, '{}', 1, 86400)"
        )
        conn.execute(
            "insert into pages (id, site_id, url, kind, consecutive_failures)"
            " values (1, 1, 'https://s/p', 'schedule', 0)"
        )
        conn.executemany(
            "insert into offerings (id, site_id, page_id, name, normalized_name, program_type,"
            " days_of_week, raw_json, status) values (?, 1, 1, ?, ?, 'soccer', '[]', '{}', ?)",
            [(1, "Live", "live", "active"), (2, "Gone", "gone", "withdrawn")],
        )
        conn.execute(
            "insert into kids (id, name, dob, interests, availability, alert_score_threshold,"
            " alert_on, school_weekdays, school_year_ranges, school_holidays, active)"
            " values (1, 'k', '2019-01-01', '[]', '{}', 0.6, '{}', '[]', '[]', '[]', 1)"
        )
        conn.executemany(
            "insert into matches (kid_id, offering_id, score, reasons) values (1, ?, 0.9, '{}')",
            [(1,), (2,)],
        )

    command.upgrade(cfg, "head")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("select offering_id from matches").fetchall()
    assert rows == [(1,)]
