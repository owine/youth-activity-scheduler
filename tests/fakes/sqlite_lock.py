"""Probe whether another connection holds SQLite's write lock.

Worker loops must not make a network call (notifier send, LLM, geocoder) while
their session holds uncommitted writes: the write lock blocks every other writer,
and once a call outlasts the 5s busy_timeout the heartbeat and API writes fail
with `database is locked`. Tests call this from inside a fake's network method to
assert the lock is free at that moment, which is deterministic where reproducing
the timeout itself would take seconds per test.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def write_lock_held(db_path: Path | str) -> bool:
    """True if some other connection holds the database's write lock right now."""
    con = sqlite3.connect(str(db_path), timeout=0)
    try:
        con.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc):
            return True
        raise
    else:
        con.rollback()
        return False
    finally:
        con.close()
