"""Integration tests for the alert delivery orchestrator.

All tests use a real SQLite database (in-memory via tmp_path) and the
FakeNotifier from tests/fakes/notifier.py.  HouseholdSettings and routing
rows are seeded explicitly so every test is fully self-contained.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from tests.fakes.notifier import FakeNotifier
from yas.alerts.channels.base import NotifierCapability
from yas.alerts.delivery import _apply_grace_window, send_alert_group
from yas.alerts.rate_limit import coalesce
from yas.alerts.routing import seed_default_routing
from yas.config import Settings
from yas.db.base import Base
from yas.db.models import Alert, AlertRouting, HouseholdSettings, Kid
from yas.db.models._types import AlertType
from yas.db.session import create_engine_for, session_scope
from yas.worker.delivery_loop import alert_delivery_loop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**kwargs: Any) -> Settings:
    return Settings(
        anthropic_api_key="test-key",
        **kwargs,
    )


def _alert(
    alert_type: str = AlertType.new_match.value,
    kid_id: int | None = 1,
    scheduled_for: datetime | None = None,
    payload: dict[str, Any] | None = None,
) -> Alert:
    return Alert(
        type=alert_type,
        kid_id=kid_id,
        channels=[],
        scheduled_for=scheduled_for or datetime.now(UTC),
        dedup_key=f"{alert_type}:{kid_id}:{datetime.now(UTC).isoformat()}",
        payload_json=payload or {"offering_name": "Soccer Camp", "kid_name": "Alice"},
        skipped=False,
    )


def _push_notifier(name: str = "ntfy") -> FakeNotifier:
    return FakeNotifier(
        name=name,
        capabilities={NotifierCapability.push},
    )


def _email_notifier(name: str = "email") -> FakeNotifier:
    return FakeNotifier(
        name=name,
        capabilities={NotifierCapability.email},
    )


async def _make_engine(tmp_path):  # type: ignore[no-untyped-def]
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/delivery.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Seed a kid so FK constraints on alerts.kid_id pass.
    async with session_scope(engine) as s:
        from datetime import date
        s.add(Kid(
            id=1,
            name="Alice",
            dob=date(2015, 6, 1),
        ))
    return engine


async def _seed_household(
    session,  # type: ignore[no-untyped-def]
    quiet_start: str | None = None,
    quiet_end: str | None = None,
) -> HouseholdSettings:
    h = HouseholdSettings(
        id=1,
        quiet_hours_start=quiet_start,
        quiet_hours_end=quiet_end,
    )
    session.add(h)
    await session.flush()
    return h


# ---------------------------------------------------------------------------
# Named must-have tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reg_opens_now_bypasses_quiet_hours(tmp_path):  # type: ignore[no-untyped-def]
    """reg_opens_now always fires on push channels even within quiet hours."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        await seed_default_routing(s)
        # Force push routing for reg_opens_now
        row = (await s.execute(
            select(AlertRouting).where(AlertRouting.type == AlertType.reg_opens_now.value)
        )).scalar_one()
        row.channels = ["ntfy"]

    async with session_scope(engine) as s:
        household = await _seed_household(s, quiet_start="00:00", quiet_end="23:59")
        a = _alert(
            alert_type=AlertType.reg_opens_now.value,
            payload={"offering_name": "Soccer Camp", "registration_url": "http://example.com"},
        )
        s.add(a)
        await s.flush()

        notifier = _push_notifier("ntfy")
        notifiers: dict[str, FakeNotifier] = {"ntfy": notifier}
        groups = coalesce([a], window_s=600)
        assert len(groups) == 1

        await send_alert_group(s, groups[0], notifiers, _settings(), household)

    async with session_scope(engine) as s:
        sent = (await s.execute(select(Alert))).scalars().all()
        assert len(sent) == 1
        assert sent[0].sent_at is not None, "reg_opens_now must fire despite quiet hours"
        assert notifier.call_count == 1


@pytest.mark.asyncio
async def test_push_rate_cap_coalesces_excess_to_single_message(tmp_path):  # type: ignore[no-untyped-def]
    """After max_pushes_per_hour alerts are sent, the next group triggers push_cap."""
    engine = await _make_engine(tmp_path)
    settings = _settings(alert_max_pushes_per_hour=5)

    async with session_scope(engine) as s:
        await seed_default_routing(s)
        # Use email routing for new_match so we can pre-seed sent alerts manually.
        row = (await s.execute(
            select(AlertRouting).where(AlertRouting.type == AlertType.new_match.value)
        )).scalar_one()
        row.channels = ["ntfy"]

    now = datetime.now(UTC)
    # Seed 5 already-sent alerts so the cap is hit.
    async with session_scope(engine) as s:
        for i in range(5):
            a = Alert(
                type=AlertType.new_match.value,
                kid_id=1,
                channels=["ntfy"],
                scheduled_for=now - timedelta(minutes=30),
                sent_at=now - timedelta(minutes=30 - i),
                dedup_key=f"new_match:1:sent:{i}",
                payload_json={"offering_name": f"Camp {i}"},
                skipped=False,
            )
            s.add(a)

        # One more alert that should be rate-capped.
        capped = _alert(
            alert_type=AlertType.new_match.value,
            kid_id=1,
            scheduled_for=now,
        )
        s.add(capped)
        await s.flush()

        notifier = _push_notifier("ntfy")
        groups = coalesce([capped], window_s=600)
        assert len(groups) == 1

        await send_alert_group(s, groups[0], {"ntfy": notifier}, settings, None)

    async with session_scope(engine) as s:
        alerts = (await s.execute(select(Alert))).scalars().all()
        # The capped alert must be marked skipped with "rate capped".
        capped_alerts = [a for a in alerts if a.payload_json.get("_skipped_reason") == "rate capped"]
        push_cap_alerts = [a for a in alerts if a.type == AlertType.push_cap.value]

        assert capped_alerts, "The rate-capped alert should be marked skipped with 'rate capped'"
        assert push_cap_alerts, "A push_cap alert should have been enqueued"
    # Push notifier must NOT have been called for the 6th alert.
    assert notifier.call_count == 0


@pytest.mark.asyncio
async def test_coalesce_merges_within_window_but_not_across_types(tmp_path):  # type: ignore[no-untyped-def]
    """Same-type alerts for the same kid within coalesce window → one group.
    Different-type alerts → separate groups."""
    engine = await _make_engine(tmp_path)
    now = datetime.now(UTC)

    async with session_scope(engine) as s:
        await seed_default_routing(s)
        a1 = _alert(
            alert_type=AlertType.new_match.value,
            kid_id=1,
            scheduled_for=now,
        )
        a2 = _alert(
            alert_type=AlertType.new_match.value,
            kid_id=1,
            scheduled_for=now + timedelta(seconds=10),
        )
        a3 = _alert(
            alert_type=AlertType.watchlist_hit.value,
            kid_id=1,
            scheduled_for=now + timedelta(seconds=5),
        )
        s.add_all([a1, a2, a3])
        await s.flush()

        groups = coalesce([a1, a2, a3], window_s=600)

    # Two different types → two groups; same-type pair → one group.
    assert len(groups) == 2
    type_set = {g.alert_type for g in groups}
    assert AlertType.new_match.value in type_set
    assert AlertType.watchlist_hit.value in type_set
    new_match_group = next(g for g in groups if g.alert_type == AlertType.new_match.value)
    assert len(new_match_group.members) == 2


@pytest.mark.asyncio
async def test_startup_grace_window_fires_recent_past_due_countdown_once(tmp_path):  # type: ignore[no-untyped-def]
    """Countdown alert past-due within grace window → fires.
    Countdown alert past-due beyond grace window → skipped."""
    now = datetime.now(UTC)
    grace_s = 86400  # 24 hours

    # Recent: scheduled 30 min ago — within 24h grace, should fire.
    recent = Alert(
        type=AlertType.reg_opens_1h.value,
        kid_id=1,
        channels=[],
        scheduled_for=now - timedelta(minutes=30),
        dedup_key="test:recent",
        payload_json={"offering_name": "Camp A"},
        skipped=False,
    )
    # Stale: scheduled 2 days ago — beyond 24h grace, should be skipped.
    stale = Alert(
        type=AlertType.reg_opens_1h.value,
        kid_id=1,
        channels=[],
        scheduled_for=now - timedelta(days=2),
        dedup_key="test:stale",
        payload_json={"offering_name": "Camp B"},
        skipped=False,
    )

    kept = _apply_grace_window([recent, stale], now, grace_s)

    assert recent in kept, "Alert within grace window should be kept"
    assert stale not in kept, "Alert beyond grace window should be removed"
    assert stale.skipped is True
    assert stale.payload_json.get("_skipped_reason") == "past grace"
    assert not recent.skipped


# ---------------------------------------------------------------------------
# Additional integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delivery_loop_sends_to_configured_channels(tmp_path):  # type: ignore[no-untyped-def]
    """Happy path: one alert, routed to email channel → sent."""
    engine = await _make_engine(tmp_path)
    now = datetime.now(UTC)

    async with session_scope(engine) as s:
        await seed_default_routing(s)
        # new_match routes to ["email"] by default.
        a = _alert(alert_type=AlertType.new_match.value, scheduled_for=now - timedelta(seconds=1))
        s.add(a)
        await s.flush()

    email_notifier = _email_notifier("email")
    notifiers: dict[str, FakeNotifier] = {"email": email_notifier}
    settings = _settings(
        alert_delivery_tick_s=1,
        alert_coalesce_normal_s=600,
    )

    task = asyncio.create_task(alert_delivery_loop(engine, settings, notifiers))
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=2.5)
    except (TimeoutError, asyncio.CancelledError):
        pass
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async with session_scope(engine) as s:
        alerts = (await s.execute(select(Alert))).scalars().all()
    assert len(alerts) == 1
    assert alerts[0].sent_at is not None
    assert "email" in (alerts[0].channels or [])


@pytest.mark.asyncio
async def test_transient_failure_retries_with_backoff(tmp_path):  # type: ignore[no-untyped-def]
    """FakeNotifier queued with transient failure → scheduled_for advances by 60s."""
    engine = await _make_engine(tmp_path)
    now = datetime.now(UTC)

    async with session_scope(engine) as s:
        await seed_default_routing(s)
        a = _alert(
            alert_type=AlertType.new_match.value,
            scheduled_for=now - timedelta(seconds=1),
        )
        s.add(a)
        await s.flush()
        alert_id = a.id

        email_notifier = _email_notifier("email")
        email_notifier.queue_transient_failure("temporary outage")

        groups = coalesce([a], window_s=600)
        assert len(groups) == 1
        await send_alert_group(s, groups[0], {"email": email_notifier}, _settings(), None)

    async with session_scope(engine) as s:
        updated = (await s.execute(select(Alert).where(Alert.id == alert_id))).scalar_one()
        assert updated.sent_at is None, "Should not be marked sent after transient failure"
        assert updated.skipped is False, "Should not be skipped after first transient failure"
        sched = updated.scheduled_for.replace(tzinfo=None) if updated.scheduled_for.tzinfo else updated.scheduled_for
        now_naive = now.replace(tzinfo=None)
        # Should be rescheduled ~60s in the future (attempt 1).
        assert sched > now_naive, "scheduled_for should be in the future"
        assert updated.payload_json.get("_attempts") == 1


@pytest.mark.asyncio
async def test_non_transient_failure_marks_skipped(tmp_path):  # type: ignore[no-untyped-def]
    """FakeNotifier queued with permanent failure → alert marked skipped."""
    engine = await _make_engine(tmp_path)
    now = datetime.now(UTC)

    async with session_scope(engine) as s:
        await seed_default_routing(s)
        a = _alert(
            alert_type=AlertType.new_match.value,
            scheduled_for=now - timedelta(seconds=1),
        )
        s.add(a)
        await s.flush()
        alert_id = a.id

        email_notifier = _email_notifier("email")
        email_notifier.queue_permanent_failure("401 unauthorized")

        groups = coalesce([a], window_s=600)
        await send_alert_group(s, groups[0], {"email": email_notifier}, _settings(), None)

    async with session_scope(engine) as s:
        updated = (await s.execute(select(Alert).where(Alert.id == alert_id))).scalar_one()
        assert updated.skipped is True
        assert updated.sent_at is None


@pytest.mark.asyncio
async def test_quiet_hours_suppresses_push_but_not_email(tmp_path):  # type: ignore[no-untyped-def]
    """Push channel skipped in quiet hours; email channel still sends."""
    engine = await _make_engine(tmp_path)
    now = datetime.now(UTC)

    async with session_scope(engine) as s:
        await seed_default_routing(s)
        # Override routing for watchlist_hit to include both push and email.
        row = (await s.execute(
            select(AlertRouting).where(AlertRouting.type == AlertType.watchlist_hit.value)
        )).scalar_one()
        row.channels = ["ntfy", "email"]
        row.enabled = True

    async with session_scope(engine) as s:
        household = await _seed_household(s, quiet_start="00:00", quiet_end="23:59")
        a = _alert(
            alert_type=AlertType.watchlist_hit.value,
            scheduled_for=now - timedelta(seconds=1),
            payload={"offering_name": "Tennis Camp"},
        )
        s.add(a)
        await s.flush()
        alert_id = a.id

        push_notifier = _push_notifier("ntfy")
        email_notifier = _email_notifier("email")
        notifiers: dict[str, FakeNotifier] = {"ntfy": push_notifier, "email": email_notifier}

        groups = coalesce([a], window_s=600)
        assert len(groups) == 1
        await send_alert_group(s, groups[0], notifiers, _settings(), household)

    async with session_scope(engine) as s:
        updated = (await s.execute(select(Alert).where(Alert.id == alert_id))).scalar_one()
        assert updated.sent_at is not None, "email should have sent despite quiet hours"
        assert "email" in (updated.channels or [])
        assert "ntfy" not in (updated.channels or [])

    assert push_notifier.call_count == 0, "push notifier must not be called in quiet hours"
    assert email_notifier.call_count == 1


@pytest.mark.asyncio
async def test_routing_disabled_skips_alert(tmp_path):  # type: ignore[no-untyped-def]
    """alert_routing row with enabled=False → all group members marked skipped."""
    engine = await _make_engine(tmp_path)
    now = datetime.now(UTC)

    async with session_scope(engine) as s:
        await seed_default_routing(s)
        row = (await s.execute(
            select(AlertRouting).where(AlertRouting.type == AlertType.new_match.value)
        )).scalar_one()
        row.enabled = False

    async with session_scope(engine) as s:
        a = _alert(
            alert_type=AlertType.new_match.value,
            scheduled_for=now - timedelta(seconds=1),
        )
        s.add(a)
        await s.flush()
        alert_id = a.id

        email_notifier = _email_notifier("email")
        groups = coalesce([a], window_s=600)
        await send_alert_group(s, groups[0], {"email": email_notifier}, _settings(), None)

    async with session_scope(engine) as s:
        updated = (await s.execute(select(Alert).where(Alert.id == alert_id))).scalar_one()
        assert updated.skipped is True
        assert updated.payload_json.get("_skipped_reason") == "routing disabled"

    assert email_notifier.call_count == 0


@pytest.mark.asyncio
async def test_mixed_transient_and_permanent_failures_retries(tmp_path):  # type: ignore[no-untyped-def]
    """Transient failure on one channel + permanent failure on another → group retried.

    Precedence: ok > transient > permanent.  A single transient failure beats
    all-permanent and schedules a retry with incremented _attempts.
    """
    engine = await _make_engine(tmp_path)
    now = datetime.now(UTC)

    async with session_scope(engine) as s:
        await seed_default_routing(s)
        # Route watchlist_hit through both push and email so we can inject
        # different failure modes on each channel.
        row = (await s.execute(
            select(AlertRouting).where(AlertRouting.type == AlertType.watchlist_hit.value)
        )).scalar_one()
        row.channels = ["ntfy", "email"]
        row.enabled = True

    async with session_scope(engine) as s:
        a = _alert(
            alert_type=AlertType.watchlist_hit.value,
            scheduled_for=now - timedelta(seconds=1),
            payload={"offering_name": "Tennis Camp"},
        )
        s.add(a)
        await s.flush()
        alert_id = a.id

        push_notifier = _push_notifier("ntfy")
        push_notifier.queue_permanent_failure("device token expired")

        email_notifier = _email_notifier("email")
        email_notifier.queue_transient_failure("SMTP timeout")

        notifiers: dict[str, FakeNotifier] = {"ntfy": push_notifier, "email": email_notifier}

        groups = coalesce([a], window_s=600)
        assert len(groups) == 1
        await send_alert_group(s, groups[0], notifiers, _settings(), None)

    async with session_scope(engine) as s:
        updated = (await s.execute(select(Alert).where(Alert.id == alert_id))).scalar_one()
        # Transient wins: alert must NOT be sent or skipped — it should be retried.
        assert updated.sent_at is None, "Should not be marked sent"
        assert updated.skipped is False, "Should not be skipped when transient failure present"
        sched = updated.scheduled_for.replace(tzinfo=None) if updated.scheduled_for.tzinfo else updated.scheduled_for
        now_naive = now.replace(tzinfo=None)
        assert sched > now_naive, "scheduled_for should advance for retry"
        assert updated.payload_json.get("_attempts") == 1, "_attempts must be incremented"
