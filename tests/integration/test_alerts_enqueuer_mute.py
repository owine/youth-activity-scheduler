"""Mute gate tests for src/yas/alerts/enqueuer.py."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from yas.alerts.enqueuer import (
    enqueue_crawl_failed,
    enqueue_new_match,
    enqueue_registration_countdowns,
    enqueue_schedule_posted,
    enqueue_site_stagnant,
    enqueue_watchlist_hit,
)
from yas.db.base import Base
from yas.db.models import Alert, Kid, Offering, Page, Site, WatchlistEntry
from yas.db.models._types import AlertType, OfferingStatus
from yas.db.session import session_scope


async def _make_engine(tmp_path: Any) -> Any:
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _seed(
    engine: Any,
    *,
    site_muted_until: datetime | None = None,
    offering_muted_until: datetime | None = None,
) -> None:
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        s.add(Site(id=1, name="X", base_url="https://x", muted_until=site_muted_until))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        s.add(
            Offering(
                id=1,
                site_id=1,
                page_id=1,
                name="T-Ball",
                normalized_name="t-ball",
                days_of_week=["tue"],
                time_start=time(16, 0),
                time_end=time(17, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
                muted_until=offering_muted_until,
            )
        )


@pytest.mark.asyncio
async def test_new_match_skipped_when_offering_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, offering_muted_until=future)
    async with session_scope(engine) as s:
        result = await enqueue_new_match(s, kid_id=1, offering_id=1, score=0.9, reasons={})
    assert result is None
    async with session_scope(engine) as s:
        alerts = (await s.execute(select(Alert))).scalars().all()
    assert alerts == []


@pytest.mark.asyncio
async def test_new_match_skipped_when_site_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, site_muted_until=future)
    async with session_scope(engine) as s:
        result = await enqueue_new_match(s, kid_id=1, offering_id=1, score=0.9, reasons={})
    assert result is None


@pytest.mark.asyncio
async def test_new_match_enqueues_when_both_unmuted(tmp_path):
    engine = await _make_engine(tmp_path)
    await _seed(engine)
    async with session_scope(engine) as s:
        result = await enqueue_new_match(s, kid_id=1, offering_id=1, score=0.9, reasons={})
    assert result is not None


@pytest.mark.asyncio
async def test_new_match_enqueues_when_mute_in_past(tmp_path):
    engine = await _make_engine(tmp_path)
    past = datetime.now(UTC) - timedelta(days=1)
    await _seed(engine, offering_muted_until=past)
    async with session_scope(engine) as s:
        result = await enqueue_new_match(s, kid_id=1, offering_id=1, score=0.9, reasons={})
    assert result is not None


@pytest.mark.asyncio
async def test_watchlist_hit_skipped_when_offering_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, offering_muted_until=future)
    async with session_scope(engine) as s:
        s.add(WatchlistEntry(id=99, kid_id=1, pattern="t-ball", active=True))
    async with session_scope(engine) as s:
        result = await enqueue_watchlist_hit(
            s, kid_id=1, offering_id=1, watchlist_entry_id=99, reasons={}
        )
    assert result is None
    async with session_scope(engine) as s:
        alerts = (
            (await s.execute(select(Alert).where(Alert.type == AlertType.watchlist_hit.value)))
            .scalars()
            .all()
        )
    assert alerts == []


@pytest.mark.asyncio
async def test_watchlist_hit_skipped_when_site_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, site_muted_until=future)
    async with session_scope(engine) as s:
        s.add(WatchlistEntry(id=99, kid_id=1, pattern="t-ball", active=True))
    async with session_scope(engine) as s:
        result = await enqueue_watchlist_hit(
            s, kid_id=1, offering_id=1, watchlist_entry_id=99, reasons={}
        )
    assert result is None


@pytest.mark.asyncio
async def test_schedule_posted_skipped_when_site_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, site_muted_until=future)
    async with session_scope(engine) as s:
        result = await enqueue_schedule_posted(s, page_id=1, site_id=1, summary="3 new offerings")
    assert result is None


@pytest.mark.asyncio
async def test_crawl_failed_skipped_when_site_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, site_muted_until=future)
    async with session_scope(engine) as s:
        result = await enqueue_crawl_failed(
            s, site_id=1, consecutive_failures=3, last_error="timeout"
        )
    assert result is None


@pytest.mark.asyncio
async def test_site_stagnant_skipped_when_site_muted(tmp_path):
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, site_muted_until=future)
    async with session_scope(engine) as s:
        result = await enqueue_site_stagnant(s, site_id=1, days_silent=15)
    assert result is None


@pytest.mark.asyncio
async def test_reg_opens_countdowns_skipped_when_offering_muted(tmp_path):
    """All three reg-opens variants are gated by a single mute check."""
    engine = await _make_engine(tmp_path)
    future = datetime.now(UTC) + timedelta(days=30)
    await _seed(engine, offering_muted_until=future)
    async with session_scope(engine) as s:
        offering = (await s.execute(select(Offering).where(Offering.id == 1))).scalar_one()
        offering.registration_opens_at = datetime.now(UTC) + timedelta(hours=2)
    async with session_scope(engine) as s:
        result = await enqueue_registration_countdowns(s, kid_id=1, offering_id=1)
    assert result == []
    async with session_scope(engine) as s:
        alerts = (await s.execute(select(Alert))).scalars().all()
    assert alerts == []
