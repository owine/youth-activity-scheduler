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
import structlog.testing
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
async def test_digest_empty_day_skipped_but_logs_debug(tmp_path):  # type: ignore[no-untyped-def]
    """Empty-day kid: no Alert inserted and DEBUG log contains digest.skipped.empty.

    Uses ``structlog.testing.capture_logs`` rather than ``capsys`` so the
    assertion is robust to test ordering: capsys captures stdout/stderr at
    the process level, which gets polluted by aiosqlite teardown noise from
    earlier async tests in the full suite. capture_logs swaps in a list-based
    processor for the duration of the context manager and is unaffected by
    sibling tests.
    """
    engine = await _make_engine(tmp_path)

    async with session_scope(engine) as s:
        # Kid created long ago but no matches → not under_no_matches_threshold.
        s.add(_active_kid(kid_id=1, days_old=30))
        s.add(HouseholdSettings(id=1))

    settings = _settings(alert_digest_empty_skip=True, alert_no_matches_kid_days=7)

    with structlog.testing.capture_logs() as logs:
        await _run_one_tick(engine, settings, FakeLLMClient())

    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.digest.value)))
            .scalars()
            .all()
        )
    assert alerts == [], "Empty-day digest must NOT be enqueued"

    events = [entry.get("event") for entry in logs]
    assert "digest.skipped.empty" in events, (
        f"Expected a log event 'digest.skipped.empty'; got events={events!r}"
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

    last_run is coroutine-local state, so the second invocation re-enters the
    run block — but it finds today's row already enqueued and skips the kid.
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


@pytest.mark.asyncio
@pytest.mark.parametrize("delivered", ["sent", "skipped"])
async def test_digest_loop_restart_does_not_resend_delivered_digest(  # type: ignore[no-untyped-def]
    tmp_path, delivered
):
    """A process restart after today's digest went out must not enqueue another.

    ``last_run`` resets on restart, and the enqueuer's upsert only merges into
    *unsent* rows — so the loop itself has to notice the delivered row.
    """
    engine = await _make_engine(tmp_path)

    async with session_scope(engine) as s:
        s.add(_active_kid(kid_id=1, days_old=1))
        s.add(HouseholdSettings(id=1))

    settings = _settings(alert_no_matches_kid_days=7)

    await _run_one_tick(engine, settings, FakeLLMClient())

    async with session_scope(engine) as s:
        alert = (
            await s.execute(select(Alert).where(Alert.type == AlertType.digest.value))
        ).scalar_one()
        if delivered == "sent":
            alert.sent_at = datetime.now(UTC)
        else:
            alert.skipped = True

    # Simulated restart: a fresh loop invocation with last_run=None.
    await _run_one_tick(engine, settings, FakeLLMClient())

    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.digest.value)))
            .scalars()
            .all()
        )
    assert len(alerts) == 1, "Restart must not re-enqueue an already-delivered digest"


@pytest.mark.asyncio
async def test_digest_loop_restart_with_pending_digest_does_not_duplicate(  # type: ignore[no-untyped-def]
    tmp_path,
):
    """A pending digest delivered mid-run must not be followed by a fresh insert.

    On restart, today's digest may still be unsent. If the loop rebuilt it, the
    delivery loop could send the pending row during the (slow) LLM top-line
    call, leaving the enqueuer no unsent row to merge into — so it would insert
    a duplicate. The fake LLM below performs that delivery mid-call.
    """
    engine = await _make_engine(tmp_path)

    async with session_scope(engine) as s:
        s.add(_active_kid(kid_id=1, days_old=1))
        s.add(HouseholdSettings(id=1))

    settings = _settings(alert_no_matches_kid_days=7)

    # First run leaves today's digest pending (unsent).
    await _run_one_tick(engine, settings, FakeLLMClient())

    class _DeliverDuringCall(FakeLLMClient):
        async def call_tool(self, **kwargs: Any) -> tuple[dict[str, Any], str, float]:
            async with session_scope(engine) as s2:
                pending = (
                    await s2.execute(select(Alert).where(Alert.type == AlertType.digest.value))
                ).scalar_one()
                pending.sent_at = datetime.now(UTC)
            return await super().call_tool(**kwargs)

    # Simulated restart while the digest is still pending.
    await _run_one_tick(engine, settings, _DeliverDuringCall())

    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.digest.value)))
            .scalars()
            .all()
        )
    assert len(alerts) == 1, "Pending digest delivered mid-run must not be duplicated"
