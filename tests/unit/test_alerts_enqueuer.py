from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from yas.alerts.enqueuer import (
    dedup_key_for,
    enqueue_crawl_failed,
    enqueue_digest,
    enqueue_new_match,
    enqueue_no_matches_for_kid,
    enqueue_push_cap,
    enqueue_registration_countdowns,
    enqueue_site_stagnant,
    enqueue_watchlist_hit,
)
from yas.db.base import Base
from yas.db.models import Alert, Kid, Offering, Page, Site
from yas.db.models._types import AlertType, ProgramType
from yas.db.session import create_engine_for, session_scope


async def _setup(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/a.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1),
                  alert_on={"new_match": True, "reg_opens": True}))
        s.add(Kid(id=2, name="Alex", dob=date(2018, 1, 1),
                  alert_on={"new_match": False, "reg_opens": True}))
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        s.add(
            Offering(
                id=1, site_id=1, page_id=1,
                name="Spring Soccer", normalized_name="spring soccer",
                program_type=ProgramType.soccer.value,
            )
        )
    return engine


# --- dedup_key -----------------------------------------------------------------

def test_dedup_key_new_match_has_kid_and_offering():
    key = dedup_key_for(AlertType.new_match, kid_id=1, offering_id=42)
    assert key == "new_match:1:42"


def test_dedup_key_site_stagnant_no_kid():
    key = dedup_key_for(AlertType.site_stagnant, site_id=9)
    assert key == "site_stagnant:-:9"


def test_dedup_key_countdown_includes_scheduled_for():
    when = datetime(2026, 5, 5, 9, 0, tzinfo=UTC)
    key = dedup_key_for(AlertType.reg_opens_24h, kid_id=1, offering_id=42, scheduled_for=when)
    assert key == "reg_opens_24h:1:42:2026-05-05T09:00"


def test_dedup_key_digest_includes_for_date():
    key = dedup_key_for(AlertType.digest, kid_id=1, for_date=date(2026, 5, 5))
    assert key == "digest:1:2026-05-05"


def test_dedup_key_no_matches_for_kid():
    assert dedup_key_for(AlertType.no_matches_for_kid, kid_id=1) == "no_matches_for_kid:1:-"


# --- enqueue_new_match ---------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_new_match_inserts_first_time(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        aid = await enqueue_new_match(
            s, kid_id=1, offering_id=1, score=0.9, reasons={"k": "v"},
        )
    assert aid is not None
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1
        assert rows[0].type == AlertType.new_match.value
        assert rows[0].kid_id == 1
        assert rows[0].offering_id == 1


@pytest.mark.asyncio
async def test_enqueue_new_match_updates_on_dedup_hit(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await enqueue_new_match(s, kid_id=1, offering_id=1, score=0.5, reasons={"v": 1})
    async with session_scope(engine) as s:
        await enqueue_new_match(s, kid_id=1, offering_id=1, score=0.9, reasons={"v": 2})
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1                              # no duplicate
        assert rows[0].payload_json["score"] == 0.9         # updated


@pytest.mark.asyncio
async def test_enqueue_new_match_respects_kid_alert_on_toggle(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        # Kid 2 has alert_on.new_match=False
        aid = await enqueue_new_match(s, kid_id=2, offering_id=1, score=0.9, reasons={})
    assert aid is None
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert rows == []


# --- enqueue_watchlist_hit -----------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_watchlist_hit_always_inserts(tmp_path):
    engine = await _setup(tmp_path)
    # Even a kid with new_match=False should still get watchlist alerts.
    async with session_scope(engine) as s:
        aid = await enqueue_watchlist_hit(
            s, kid_id=2, offering_id=1, watchlist_entry_id=7, reasons={"pattern": "soccer"},
        )
    assert aid is not None


# --- enqueue_registration_countdowns ------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_registration_countdowns_inserts_three_rows(tmp_path):
    engine = await _setup(tmp_path)
    opens_at = datetime.now(UTC) + timedelta(days=3)
    async with session_scope(engine) as s:
        ids = await enqueue_registration_countdowns(
            s, offering_id=1, kid_id=1, opens_at=opens_at,
        )
    assert len(ids) == 3
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert).order_by(Alert.scheduled_for))).scalars().all()
        types = [r.type for r in rows]
        assert types == [
            AlertType.reg_opens_24h.value,
            AlertType.reg_opens_1h.value,
            AlertType.reg_opens_now.value,
        ]


@pytest.mark.asyncio
async def test_enqueue_registration_countdowns_skips_past_due(tmp_path):
    engine = await _setup(tmp_path)
    # opens_at is 30 minutes from now. T-24h is in the past; T-1h is in the past;
    # only T-0 (now+30min) gets scheduled.
    opens_at = datetime.now(UTC) + timedelta(minutes=30)
    async with session_scope(engine) as s:
        ids = await enqueue_registration_countdowns(
            s, offering_id=1, kid_id=1, opens_at=opens_at,
        )
    assert len(ids) == 1
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1
        assert rows[0].type == AlertType.reg_opens_now.value


@pytest.mark.asyncio
async def test_enqueue_registration_countdowns_rewrites_on_date_change(tmp_path):
    engine = await _setup(tmp_path)
    original = datetime.now(UTC) + timedelta(days=3)
    shifted = original + timedelta(days=7)
    async with session_scope(engine) as s:
        await enqueue_registration_countdowns(s, offering_id=1, kid_id=1, opens_at=original)
    async with session_scope(engine) as s:
        await enqueue_registration_countdowns(s, offering_id=1, kid_id=1, opens_at=shifted)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert).order_by(Alert.scheduled_for))).scalars().all()
        # Should still be only three rows — old deleted, new inserted
        assert len(rows) == 3
        first = rows[0].scheduled_for
        # SQLite strips tzinfo; compare as naive UTC.
        original_naive = original.replace(tzinfo=None)
        if first.tzinfo is None:
            assert first > original_naive
        else:
            assert first > original


# --- enqueue_crawl_failed ------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_crawl_failed_dedups_per_site(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await enqueue_crawl_failed(s, site_id=1, consecutive_failures=3, last_error="timeout")
    async with session_scope(engine) as s:
        await enqueue_crawl_failed(s, site_id=1, consecutive_failures=4, last_error="timeout")
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload_json["consecutive_failures"] == 4


# --- enqueue_site_stagnant + enqueue_no_matches_for_kid -----------------------

@pytest.mark.asyncio
async def test_enqueue_site_stagnant_one_per_site(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await enqueue_site_stagnant(s, site_id=1, days_silent=31)
    async with session_scope(engine) as s:
        await enqueue_site_stagnant(s, site_id=1, days_silent=32)    # next day
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload_json["days_silent"] == 32


@pytest.mark.asyncio
async def test_enqueue_no_matches_for_kid_one_per_kid(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await enqueue_no_matches_for_kid(s, kid_id=1, days_since_created=7)
    async with session_scope(engine) as s:
        await enqueue_no_matches_for_kid(s, kid_id=1, days_since_created=14)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1


# --- enqueue_digest ------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_digest_dedups_per_day(tmp_path):
    engine = await _setup(tmp_path)
    today = date(2026, 5, 5)
    payload = {"subject": "...", "body_plain": "...", "body_html": "..."}
    async with session_scope(engine) as s:
        await enqueue_digest(s, kid_id=1, for_date=today, payload=payload)
    async with session_scope(engine) as s:
        await enqueue_digest(s, kid_id=1, for_date=today,
                             payload={**payload, "subject": "updated"})
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload_json["subject"] == "updated"


# --- enqueue_push_cap ----------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_push_cap_dedups_per_hour_bucket(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await enqueue_push_cap(s, kid_id=1, hour_bucket="2026-04-22T15", suppressed_count=3)
    async with session_scope(engine) as s:
        await enqueue_push_cap(s, kid_id=1, hour_bucket="2026-04-22T15", suppressed_count=7)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload_json["suppressed_count"] == 7
    # Different hour bucket → separate row
    async with session_scope(engine) as s:
        await enqueue_push_cap(s, kid_id=1, hour_bucket="2026-04-22T16", suppressed_count=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Alert))).scalars().all()
        assert len(rows) == 2
