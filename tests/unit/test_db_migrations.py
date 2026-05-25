"""Tests for yas.db.migrations.upgrade_to_head."""

from __future__ import annotations

import sqlite3

from yas.db.migrations import upgrade_to_head


def test_upgrade_to_head_creates_tables(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_path}"

    upgrade_to_head(url)

    # Sanity-check that at least one expected table exists. We don't enumerate
    # all of them — that's coupling the test to the current schema. Pick a
    # table that has existed since the very first migration.
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "select name from sqlite_master where type='table' and name='sites'"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("sites",)]


def test_upgrade_to_head_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_path}"

    upgrade_to_head(url)
    upgrade_to_head(url)  # second call should be a no-op, not raise


def test_upgrade_to_head_uses_fallback_ini(tmp_path, monkeypatch) -> None:
    # Exercise the parents-walk fallback in _find_alembic_ini. With CWD set
    # to a directory that has no alembic.ini, the helper must still locate
    # the repo's alembic.ini by walking up from its own __file__.
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "test.db"
    upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "select name from sqlite_master where type='table' and name='sites'"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("sites",)]
