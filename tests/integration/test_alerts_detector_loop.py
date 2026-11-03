"""Integration tests for daily_detector_loop.

All tests use an in-memory SQLite database.  The loop is exercised by
setting alert_detector_time_utc="00:00" (fires on any UTC reading) and
cancelling after the first sleep.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import structlog.testing
from sqlalchemy import select

from tests.fakes.clock import StopLoop, scripted_clock
from yas.config import Settings
from yas.db.models import Alert, Kid, Offering, Site
from yas.db.models._types import AlertType
from yas.db.models.page import Page
from yas.db.session import session_scope
from yas.worker.detector_loop import daily_detector_loop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**kwargs: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        anthropic_api_key="test-key",
        alert_detector_time_utc="00:00",
        alert_stagnant_site_days=30,
        alert_no_matches_kid_days=7,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


async def _run_one_tick(engine: Any, settings: Settings) -> None:
    """Run the detector loop until it finishes its first sleep (then cancel)."""

    async def _capturing_sleep(seconds: float) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(
            daily_detector_loop(engine, settings, sleep=_capturing_sleep), timeout=10.0
        )


def _stagnant_site(
    site_id: int = 1,
    name: str = "Old Site",
    days_stale: int = 60,
) -> tuple[Site, Page, Offering]:
    """Return a Site + Page + Offering triple whose last offering is stale."""
    now = datetime.now(UTC)
    site = Site(id=site_id, name=name, base_url=f"https://example.com/{site_id}", active=True)
    page = Page(id=site_id * 100, site_id=site_id, url=f"https://example.com/{site_id}/schedule")
    stale_ts = now - timedelta(days=days_stale)
    offering = Offering(
        id=site_id * 1000,
        site_id=site_id,
        page_id=site_id * 100,
        name="Old Camp",
        normalized_name="old camp",
        first_seen=stale_ts,
        last_seen=stale_ts,
    )
    return site, page, offering


# ---------------------------------------------------------------------------
# Named must-have tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detector_loop_enqueues_site_stagnant_alerts(engine):  # type: ignore[no-untyped-def]
    """Stagnant site → site_stagnant Alert row inserted."""
    async with session_scope(engine) as s:
        site, page, offering = _stagnant_site(site_id=1, days_stale=60)
        s.add(site)
        await s.flush()
        s.add(page)
        await s.flush()
        s.add(offering)

    settings = _settings(alert_stagnant_site_days=30)
    await _run_one_tick(engine, settings)

    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.site_stagnant.value)))
            .scalars()
            .all()
        )
    assert len(alerts) == 1
    assert alerts[0].site_id == 1


@pytest.mark.asyncio
async def test_detector_loop_enqueues_no_matches_kid_alerts(engine):  # type: ignore[no-untyped-def]
    """Kid beyond threshold with no matches → no_matches_for_kid Alert row inserted."""
    async with session_scope(engine) as s:
        kid = Kid(
            id=1,
            name="Alice",
            dob=date(2015, 6, 1),
            active=True,
            # Created 10 days ago — past the 7-day threshold.
            created_at=datetime.now(UTC) - timedelta(days=10),
        )
        s.add(kid)

    settings = _settings(alert_no_matches_kid_days=7)
    await _run_one_tick(engine, settings)

    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.no_matches_for_kid.value)))
            .scalars()
            .all()
        )
    assert len(alerts) == 1
    assert alerts[0].kid_id == 1


@pytest.mark.asyncio
async def test_detector_loop_only_fires_once_per_day(engine):  # type: ignore[no-untyped-def]
    """Running the loop twice results in exactly one Alert row per hit (dedup)."""
    async with session_scope(engine) as s:
        site, page, offering = _stagnant_site(site_id=1, days_stale=60)
        s.add(site)
        await s.flush()
        s.add(page)
        await s.flush()
        s.add(offering)

    settings = _settings(alert_stagnant_site_days=30)

    await _run_one_tick(engine, settings)
    await _run_one_tick(engine, settings)

    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.site_stagnant.value)))
            .scalars()
            .all()
        )
    # Dedup upsert merges duplicate unsent rows into one.
    assert len(alerts) == 1, "Duplicate detector runs must collapse to one Alert row"


@pytest.mark.asyncio
async def test_detector_loop_last_run_guard_skips_a_second_tick_the_same_day(  # type: ignore[no-untyped-def]
    engine, monkeypatch
):
    """Two ticks on one day run once; a tick the next day runs again.

    The once-per-day test above starts a fresh coroutine per tick, so
    ``last_run`` is always None there and only the enqueuer's dedup is
    exercised. This drives several ticks through one invocation.
    """
    import yas.worker.detector_loop as detector_mod

    async with session_scope(engine) as s:
        site, page, offering = _stagnant_site(site_id=1, days_stale=60)
        s.add(site)
        await s.flush()
        s.add(page)
        await s.flush()
        s.add(offering)

    day1 = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    day2 = day1 + timedelta(days=1)
    sleep = scripted_clock(monkeypatch, detector_mod, [day1, day1 + timedelta(minutes=1), day2])

    with structlog.testing.capture_logs() as logs, pytest.raises(StopLoop):
        await asyncio.wait_for(
            daily_detector_loop(engine, _settings(alert_stagnant_site_days=30), sleep=sleep),
            timeout=10.0,
        )

    runs = [e["for_date"] for e in logs if e.get("event") == "detector.ran"]
    assert runs == [day1.date().isoformat(), day2.date().isoformat()]


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detector_loop_no_alerts_when_no_anomalies(engine):  # type: ignore[no-untyped-def]
    """Fresh site and no kid anomalies → no alerts inserted."""
    async with session_scope(engine) as s:
        site, page, offering = _stagnant_site(site_id=1, days_stale=5)
        s.add(site)
        await s.flush()
        s.add(page)
        await s.flush()
        s.add(offering)

    settings = _settings(alert_stagnant_site_days=30)
    await _run_one_tick(engine, settings)

    async with session_scope(engine) as s:
        alerts = (await s.execute(select(Alert))).scalars().all()
    assert alerts == [], "Fresh site and no kid anomalies must produce no alerts"
