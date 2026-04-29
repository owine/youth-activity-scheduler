"""Integration tests for daily_digest_loop.

All tests use an in-memory SQLite database and a FakeLLMClient.  The loop is
exercised by setting alert_digest_time_utc="00:00" (so it fires on any clock
reading) and cancelling after the first sleep completes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from tests.fakes.llm import FakeLLMClient
from yas.config import Settings
from yas.db.base import Base
from yas.db.models import Alert, HouseholdSettings, Kid
from yas.db.models._types import AlertType
from yas.db.session import create_engine_for, session_scope
from yas.worker.digest_loop import daily_digest_loop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**kwargs: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        anthropic_api_key="test-key",
        # 00:00 fires on any clock reading ≥ midnight (always true in UTC).
        alert_digest_time_utc="00:00",
        alert_digest_empty_skip=True,
        alert_no_matches_kid_days=7,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


async def _make_engine(tmp_path):  # type: ignore[no-untyped-def]
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/digest.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


def _active_kid(
    kid_id: int = 1,
    name: str = "Alice",
    active: bool = True,
    days_old: int = 30,
) -> Kid:
    return Kid(
        id=kid_id,
        name=name,
        dob=date(2015, 6, 1),
        active=active,
        created_at=datetime.now(UTC) - timedelta(days=days_old),
    )


async def _run_one_tick(engine: Any, settings: Settings, llm: Any = None) -> None:
    """Run the digest loop until it finishes its first sleep (then cancel)."""

    async def _capturing_sleep(seconds: float) -> None:
        # Immediately raise so the loop exits after exactly one tick.
        raise asyncio.CancelledError

    task = asyncio.create_task(_patched_digest_loop(engine, settings, llm, _capturing_sleep))
    try:
        await asyncio.wait_for(task, timeout=10.0)
    except TimeoutError, asyncio.CancelledError:
        pass
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def _patched_digest_loop(engine: Any, settings: Settings, llm: Any, fake_sleep: Any) -> None:
    """Wrap daily_digest_loop with a patched asyncio.sleep."""
    import yas.worker.digest_loop as _mod

    original = _mod.asyncio.sleep  # type: ignore[attr-defined]
    _mod.asyncio.sleep = fake_sleep  # type: ignore[attr-defined]
    try:
        await daily_digest_loop(engine, settings, llm)
    except asyncio.CancelledError:
        pass
    finally:
        _mod.asyncio.sleep = original  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Named must-have tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_digest_empty_day_skipped_but_logs_debug(tmp_path, capsys):  # type: ignore[no-untyped-def]
    """Empty-day kid: no Alert inserted and DEBUG log contains digest.skipped.empty.

    structlog uses PrintLoggerFactory (writes to stderr) rather than the stdlib
    logging module, so we capture with capsys rather than caplog.
    """
    engine = await _make_engine(tmp_path)

    async with session_scope(engine) as s:
        # Kid created long ago but no matches → not under_no_matches_threshold.
        s.add(_active_kid(kid_id=1, days_old=30))
        s.add(HouseholdSettings(id=1))

    settings = _settings(alert_digest_empty_skip=True, alert_no_matches_kid_days=7)

    await _run_one_tick(engine, settings, FakeLLMClient())

    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.digest.value)))
            .scalars()
            .all()
        )
    assert alerts == [], "Empty-day digest must NOT be enqueued"

    captured = capsys.readouterr()
    # structlog is configured with PrintLoggerFactory (writes to stdout in tests).
    combined = captured.out + captured.err
    assert "digest.skipped.empty" in combined, (
        "Expected a log line containing 'digest.skipped.empty'; "
        f"got stdout={captured.out!r} stderr={captured.err!r}"
    )


@pytest.mark.asyncio
async def test_digest_no_matches_kid_under_threshold_sends(tmp_path):  # type: ignore[no-untyped-def]
    """Kid with no matches but under the no-matches threshold always gets a digest.

    under_no_matches_threshold=True bypasses the empty-day skip.
    """
    engine = await _make_engine(tmp_path)

    async with session_scope(engine) as s:
        # Kid created only 1 day ago — within the 7-day threshold.
        s.add(_active_kid(kid_id=1, days_old=1))
        s.add(HouseholdSettings(id=1))

    settings = _settings(
        alert_digest_empty_skip=True,
        alert_no_matches_kid_days=7,
    )

    await _run_one_tick(engine, settings, FakeLLMClient())

    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.digest.value)))
            .scalars()
            .all()
        )
    assert len(alerts) == 1, "Kid under no-matches threshold must get a digest"


# ---------------------------------------------------------------------------
# Additional integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_digest_loop_enqueues_for_each_active_kid(tmp_path):  # type: ignore[no-untyped-def]
    """One digest alert per active kid when at least one has content."""
    engine = await _make_engine(tmp_path)

    async with session_scope(engine) as s:
        for i in (1, 2):
            # Both kids created recently → under_no_matches_threshold triggers content.
            s.add(_active_kid(kid_id=i, name=f"Kid{i}", days_old=1))
        s.add(HouseholdSettings(id=1))

    settings = _settings(alert_digest_empty_skip=True, alert_no_matches_kid_days=7)

    await _run_one_tick(engine, settings, FakeLLMClient())

    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.digest.value)))
            .scalars()
            .all()
        )
    kid_ids = {a.kid_id for a in alerts}
    assert kid_ids == {1, 2}, "Must enqueue one digest per active kid"


@pytest.mark.asyncio
async def test_digest_loop_skips_inactive_kids(tmp_path):  # type: ignore[no-untyped-def]
    """Inactive kids are excluded from the digest run."""
    engine = await _make_engine(tmp_path)

    async with session_scope(engine) as s:
        s.add(_active_kid(kid_id=1, active=False, days_old=1))
        s.add(HouseholdSettings(id=1))

    settings = _settings(alert_digest_empty_skip=True, alert_no_matches_kid_days=7)

    await _run_one_tick(engine, settings, FakeLLMClient())

    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.digest.value)))
            .scalars()
            .all()
        )
    assert alerts == [], "Inactive kids must not receive a digest"


@pytest.mark.asyncio
async def test_digest_loop_only_fires_once_per_day(tmp_path):  # type: ignore[no-untyped-def]
    """Running the loop twice produces at most one digest alert per kid.

    Because last_run is coroutine-local state, two separate invocations both
    fire, but the enqueuer dedup_key collapses duplicate unsent rows into one.
    """
    engine = await _make_engine(tmp_path)

    async with session_scope(engine) as s:
        s.add(_active_kid(kid_id=1, days_old=1))
        s.add(HouseholdSettings(id=1))

    settings = _settings(alert_no_matches_kid_days=7)

    await _run_one_tick(engine, settings, FakeLLMClient())
    await _run_one_tick(engine, settings, FakeLLMClient())

    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.digest.value)))
            .scalars()
            .all()
        )
    # Dedup upsert merges duplicate unsent rows into one.
    assert len(alerts) == 1, "Duplicate digest runs must be collapsed to one row"


@pytest.mark.asyncio
async def test_digest_empty_skip_false_always_enqueues(tmp_path):  # type: ignore[no-untyped-def]
    """When alert_digest_empty_skip=False, even empty days get a digest."""
    engine = await _make_engine(tmp_path)

    async with session_scope(engine) as s:
        # Kid old enough so under_no_matches_threshold=False.
        s.add(_active_kid(kid_id=1, days_old=30))
        s.add(HouseholdSettings(id=1))

    settings = _settings(
        alert_digest_empty_skip=False,
        alert_no_matches_kid_days=7,
    )

    await _run_one_tick(engine, settings, FakeLLMClient())

    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.digest.value)))
            .scalars()
            .all()
        )
    assert len(alerts) == 1, "Empty-skip=False must still enqueue on empty days"
