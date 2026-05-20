"""Per-kind builder tests: real DB joins, payload-shape assertions, failure modes."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from yas.db.base import Base
from yas.db.models import Alert, Kid, Match, Offering, Page, Site
from yas.db.models._types import AlertType, CrawlStatus, PageKind
from yas.db.models.crawl_run import CrawlRun
from yas.db.session import create_engine_for, session_scope
from yas.email import EmailRenderError
from yas.email.builders import (
    build_crawl_failed,
    build_new_match,
    build_reg_opens_1h,
    build_reg_opens_24h,
    build_reg_opens_now,
    build_schedule_posted,
    build_watchlist_hit,
)
from yas.email.payloads import (
    CrawlFailedPayload,
    NewMatchPayload,
    RegOpens1hPayload,
    RegOpens24hPayload,
    RegOpensNowPayload,
    SchedulePostedPayload,
    WatchlistHitPayload,
)

NOW = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)


async def _engine(tmp_path: Any):
    eng = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/b.db")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    return eng


@pytest.mark.asyncio
async def test_build_new_match_single(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        site = Site(name="Park", base_url="https://p.example.com", active=True)
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule)
        s.add(page)
        await s.flush()
        kid = Kid(name="Ada", dob=date(2019, 5, 1), created_at=NOW - timedelta(days=30))
        s.add(kid)
        await s.flush()
        off = Offering(
            site_id=site.id,
            page_id=page.id,
            name="Soccer Camp",
            normalized_name="soccer camp",
            start_date=date(2026, 6, 1),
            price_cents=15000,
            registration_url="https://p.example.com/r/10",
        )
        s.add(off)
        await s.flush()
        m = Match(kid_id=kid.id, offering_id=off.id, score=0.9, computed_at=NOW)
        s.add(m)
        await s.flush()
        a = Alert(
            type=AlertType.new_match.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="x",
            payload_json={"offering_id": off.id},
            skipped=False,
        )
        s.add(a)
        await s.flush()

        payload = await build_new_match(s, a, [a])

    assert isinstance(payload, NewMatchPayload)
    assert payload.kid_name == "Ada"
    assert len(payload.matches) == 1
    assert payload.matches[0]["offering_name"] == "Soccer Camp"
    assert payload.matches[0]["price_cents"] == 15000
    assert payload.matches[0]["registration_url"] == "https://p.example.com/r/10"


@pytest.mark.asyncio
async def test_build_new_match_coalesced(tmp_path: Any) -> None:
    """Two member alerts -> both offerings in payload.matches, ordered by score desc."""
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        site = Site(name="Park", base_url="https://p.example.com", active=True)
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule)
        s.add(page)
        await s.flush()
        kid = Kid(name="Ada", dob=date(2019, 5, 1), created_at=NOW - timedelta(days=30))
        s.add(kid)
        await s.flush()
        off1 = Offering(
            site_id=site.id,
            page_id=page.id,
            name="Soccer Camp",
            normalized_name="soccer camp",
            start_date=date(2026, 6, 1),
            price_cents=15000,
            registration_url="https://p.example.com/r/10",
        )
        s.add(off1)
        await s.flush()
        off2 = Offering(
            site_id=site.id,
            page_id=page.id,
            name="Tennis Camp",
            normalized_name="tennis camp",
            start_date=date(2026, 6, 15),
            price_cents=12000,
            registration_url="https://p.example.com/r/20",
        )
        s.add(off2)
        await s.flush()
        m1 = Match(kid_id=kid.id, offering_id=off1.id, score=0.7, computed_at=NOW)
        s.add(m1)
        m2 = Match(kid_id=kid.id, offering_id=off2.id, score=0.9, computed_at=NOW)
        s.add(m2)
        await s.flush()
        a1 = Alert(
            type=AlertType.new_match.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="x1",
            payload_json={"offering_id": off1.id},
            skipped=False,
        )
        a2 = Alert(
            type=AlertType.new_match.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="x2",
            payload_json={"offering_id": off2.id},
            skipped=False,
        )
        s.add(a1)
        s.add(a2)
        await s.flush()

        payload = await build_new_match(s, a1, [a1, a2])

    assert len(payload.matches) == 2
    # Ordered by score desc
    assert payload.matches[0]["offering_name"] == "Tennis Camp"
    assert payload.matches[1]["offering_name"] == "Soccer Camp"


@pytest.mark.asyncio
async def test_build_new_match_missing_offering(tmp_path: Any) -> None:
    """payload_json points at a non-existent offering -> EmailRenderError."""
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        kid = Kid(name="Ada", dob=date(2019, 5, 1), created_at=NOW)
        s.add(kid)
        await s.flush()
        a = Alert(
            type=AlertType.new_match.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="x",
            payload_json={"offering_id": 999999},
            skipped=False,
        )
        s.add(a)
        await s.flush()
        with pytest.raises(EmailRenderError):
            await build_new_match(s, a, [a])


@pytest.mark.asyncio
async def test_build_new_match_no_kid(tmp_path: Any) -> None:
    """Lead alert without kid_id -> EmailRenderError."""
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        a = Alert(
            type=AlertType.new_match.value,
            kid_id=None,
            channels=[],
            scheduled_for=NOW,
            dedup_key="x",
            payload_json={"offering_id": 1},
            skipped=False,
        )
        s.add(a)
        await s.flush()
        with pytest.raises(EmailRenderError):
            await build_new_match(s, a, [a])


# ---------------------------------------------------------------------------
# build_reg_opens_now
# ---------------------------------------------------------------------------


async def _seed_reg_opens_now_minimal(
    s: Any,
    *,
    with_match: bool = True,
    registration_url: str | None = "https://p.example.com/r/20",
) -> tuple[Alert, Offering, Kid]:
    site = Site(name="Park", base_url="https://p.example.com", active=True)
    s.add(site)
    await s.flush()
    page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule)
    s.add(page)
    await s.flush()
    kid = Kid(name="Bo", dob=date(2019, 5, 1), created_at=NOW - timedelta(days=30))
    s.add(kid)
    await s.flush()
    off = Offering(
        site_id=site.id,
        page_id=page.id,
        name="Tennis Camp",
        normalized_name="tennis camp",
        start_date=date(2026, 7, 1),
        price_cents=12000,
        registration_url=registration_url,
        registration_opens_at=NOW,
    )
    s.add(off)
    await s.flush()
    if with_match:
        m = Match(kid_id=kid.id, offering_id=off.id, score=0.85, computed_at=NOW)
        s.add(m)
        await s.flush()
    a = Alert(
        type=AlertType.reg_opens_now.value,
        kid_id=kid.id,
        offering_id=off.id,
        channels=[],
        scheduled_for=NOW,
        dedup_key="r1",
        payload_json={"offering_id": off.id},
        skipped=False,
    )
    s.add(a)
    await s.flush()
    return a, off, kid


@pytest.mark.asyncio
async def test_build_reg_opens_now_happy_path(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        a, _off, _kid = await _seed_reg_opens_now_minimal(s)
        payload = await build_reg_opens_now(s, a, [a])

    assert isinstance(payload, RegOpensNowPayload)
    assert payload.kid_name == "Bo"
    assert payload.offering["offering_name"] == "Tennis Camp"
    assert payload.offering["score"] == 0.85
    assert payload.offering["site_name"] == "Park"
    assert payload.registration_url == "https://p.example.com/r/20"
    assert payload.opens_at is not None


@pytest.mark.asyncio
async def test_build_reg_opens_now_no_kid_raises(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        a = Alert(
            type=AlertType.reg_opens_now.value,
            kid_id=None,
            channels=[],
            scheduled_for=NOW,
            dedup_key="r-nokid",
            payload_json={"offering_id": 1},
            skipped=False,
        )
        s.add(a)
        await s.flush()
        with pytest.raises(EmailRenderError):
            await build_reg_opens_now(s, a, [a])


@pytest.mark.asyncio
async def test_build_reg_opens_now_missing_offering_raises(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        kid = Kid(name="Bo", dob=date(2019, 5, 1), created_at=NOW)
        s.add(kid)
        await s.flush()
        a = Alert(
            type=AlertType.reg_opens_now.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="r-noff",
            payload_json={"offering_id": 999999},
            skipped=False,
        )
        s.add(a)
        await s.flush()
        with pytest.raises(EmailRenderError):
            await build_reg_opens_now(s, a, [a])


@pytest.mark.asyncio
async def test_build_reg_opens_now_no_url_raises(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        a, _, _ = await _seed_reg_opens_now_minimal(s, registration_url=None)
        with pytest.raises(EmailRenderError):
            await build_reg_opens_now(s, a, [a])


@pytest.mark.asyncio
async def test_build_reg_opens_now_no_match_omits_score(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        a, _, _ = await _seed_reg_opens_now_minimal(s, with_match=False)
        payload = await build_reg_opens_now(s, a, [a])

    assert "score" not in payload.offering


# ---------------------------------------------------------------------------
# build_reg_opens_1h
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_reg_opens_1h_happy_path(tmp_path: Any) -> None:
    """Explicit ``now`` is preserved on the payload for determinism."""
    eng = await _engine(tmp_path)
    fixed_now = NOW - timedelta(hours=1)
    async with session_scope(eng) as s:
        a, _off, _kid = await _seed_reg_opens_now_minimal(s)
        payload = await build_reg_opens_1h(s, a, [a], now=fixed_now)

    assert isinstance(payload, RegOpens1hPayload)
    assert payload.kid_name == "Bo"
    assert payload.offering["offering_name"] == "Tennis Camp"
    assert payload.registration_url == "https://p.example.com/r/20"
    assert payload.now == fixed_now
    assert payload.opens_at is not None


@pytest.mark.asyncio
async def test_build_reg_opens_1h_no_kid_raises(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        a = Alert(
            type=AlertType.reg_opens_1h.value,
            kid_id=None,
            channels=[],
            scheduled_for=NOW,
            dedup_key="r1h-nokid",
            payload_json={"offering_id": 1},
            skipped=False,
        )
        s.add(a)
        await s.flush()
        with pytest.raises(EmailRenderError):
            await build_reg_opens_1h(s, a, [a])


@pytest.mark.asyncio
async def test_build_reg_opens_1h_missing_offering_raises(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        kid = Kid(name="Bo", dob=date(2019, 5, 1), created_at=NOW)
        s.add(kid)
        await s.flush()
        a = Alert(
            type=AlertType.reg_opens_1h.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="r1h-noff",
            payload_json={"offering_id": 999999},
            skipped=False,
        )
        s.add(a)
        await s.flush()
        with pytest.raises(EmailRenderError):
            await build_reg_opens_1h(s, a, [a])


@pytest.mark.asyncio
async def test_build_reg_opens_1h_no_url_raises(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        a, _, _ = await _seed_reg_opens_now_minimal(s, registration_url=None)
        with pytest.raises(EmailRenderError):
            await build_reg_opens_1h(s, a, [a])


# ---------------------------------------------------------------------------
# build_reg_opens_24h
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_reg_opens_24h_happy_path(tmp_path: Any) -> None:
    """Explicit ``now`` is preserved on the payload for determinism."""
    eng = await _engine(tmp_path)
    fixed_now = NOW - timedelta(hours=24)
    async with session_scope(eng) as s:
        a, _off, _kid = await _seed_reg_opens_now_minimal(s)
        payload = await build_reg_opens_24h(s, a, [a], now=fixed_now)

    assert isinstance(payload, RegOpens24hPayload)
    assert payload.kid_name == "Bo"
    assert payload.offering["offering_name"] == "Tennis Camp"
    assert payload.registration_url == "https://p.example.com/r/20"
    assert payload.now == fixed_now
    assert payload.opens_at is not None


@pytest.mark.asyncio
async def test_build_reg_opens_24h_missing_offering_raises(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        kid = Kid(name="Bo", dob=date(2019, 5, 1), created_at=NOW)
        s.add(kid)
        await s.flush()
        a = Alert(
            type=AlertType.reg_opens_24h.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="r24h-noff",
            payload_json={"offering_id": 999999},
            skipped=False,
        )
        s.add(a)
        await s.flush()
        with pytest.raises(EmailRenderError):
            await build_reg_opens_24h(s, a, [a])


# ---------------------------------------------------------------------------
# build_watchlist_hit
# ---------------------------------------------------------------------------


async def _seed_watchlist_kid_and_offering(
    s: Any,
    *,
    name: str = "Robotics Camp",
    normalized: str = "robotics camp",
    score: float = 0.88,
    registration_url: str = "https://p.example.com/r/50",
) -> tuple[Kid, Offering]:
    site = Site(name="Park", base_url="https://p.example.com", active=True)
    s.add(site)
    await s.flush()
    page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule)
    s.add(page)
    await s.flush()
    kid = Kid(name="Eli", dob=date(2019, 5, 1), created_at=NOW - timedelta(days=30))
    s.add(kid)
    await s.flush()
    off = Offering(
        site_id=site.id,
        page_id=page.id,
        name=name,
        normalized_name=normalized,
        start_date=date(2026, 7, 15),
        price_cents=22000,
        registration_url=registration_url,
    )
    s.add(off)
    await s.flush()
    m = Match(kid_id=kid.id, offering_id=off.id, score=score, computed_at=NOW)
    s.add(m)
    await s.flush()
    return kid, off


@pytest.mark.asyncio
async def test_build_watchlist_hit_single_with_label(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        kid, off = await _seed_watchlist_kid_and_offering(s)
        a = Alert(
            type=AlertType.watchlist_hit.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="wh1",
            payload_json={"offering_id": off.id, "watchlist_label": "robotics camps"},
            skipped=False,
        )
        s.add(a)
        await s.flush()

        payload = await build_watchlist_hit(s, a, [a])

    assert isinstance(payload, WatchlistHitPayload)
    assert payload.kid_name == "Eli"
    assert payload.watchlist_label == "robotics camps"
    assert len(payload.matches) == 1
    assert payload.matches[0]["offering_name"] == "Robotics Camp"


@pytest.mark.asyncio
async def test_build_watchlist_hit_single_no_label(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        kid, off = await _seed_watchlist_kid_and_offering(s)
        a = Alert(
            type=AlertType.watchlist_hit.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="wh2",
            payload_json={"offering_id": off.id},
            skipped=False,
        )
        s.add(a)
        await s.flush()

        payload = await build_watchlist_hit(s, a, [a])

    assert payload.watchlist_label is None
    assert len(payload.matches) == 1


@pytest.mark.asyncio
async def test_build_watchlist_hit_coalesced(tmp_path: Any) -> None:
    """Two offerings -> ordered by score desc."""
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        kid, off1 = await _seed_watchlist_kid_and_offering(
            s,
            name="Robotics Camp",
            normalized="robotics camp",
            score=0.7,
            registration_url="https://p.example.com/r/50",
        )
        # Second offering on same kid
        site_id = off1.site_id
        page_id = off1.page_id
        off2 = Offering(
            site_id=site_id,
            page_id=page_id,
            name="LEGO Lab",
            normalized_name="lego lab",
            start_date=date(2026, 7, 20),
            price_cents=18000,
            registration_url="https://p.example.com/r/51",
        )
        s.add(off2)
        await s.flush()
        m2 = Match(kid_id=kid.id, offering_id=off2.id, score=0.95, computed_at=NOW)
        s.add(m2)
        await s.flush()
        a1 = Alert(
            type=AlertType.watchlist_hit.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="wh-c1",
            payload_json={"offering_id": off1.id, "watchlist_label": "build stuff"},
            skipped=False,
        )
        a2 = Alert(
            type=AlertType.watchlist_hit.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="wh-c2",
            payload_json={"offering_id": off2.id},
            skipped=False,
        )
        s.add(a1)
        s.add(a2)
        await s.flush()

        payload = await build_watchlist_hit(s, a1, [a1, a2])

    assert len(payload.matches) == 2
    assert payload.matches[0]["offering_name"] == "LEGO Lab"
    assert payload.matches[1]["offering_name"] == "Robotics Camp"
    assert payload.watchlist_label == "build stuff"


# ---------------------------------------------------------------------------
# build_schedule_posted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_schedule_posted_happy_path(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        site = Site(name="Lakeshore Rec", base_url="https://l.example.com", active=True)
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="https://l.example.com/s", kind=PageKind.schedule)
        s.add(page)
        await s.flush()
        off1 = Offering(
            site_id=site.id,
            page_id=page.id,
            name="Summer Swim Sessions",
            normalized_name="summer swim sessions",
            start_date=date(2026, 6, 15),
            price_cents=14000,
            registration_url="https://l.example.com/r/100",
        )
        s.add(off1)
        off2 = Offering(
            site_id=site.id,
            page_id=page.id,
            name="Sailing 101",
            normalized_name="sailing 101",
            start_date=date(2026, 7, 1),
            price_cents=24000,
            registration_url="https://l.example.com/r/101",
        )
        s.add(off2)
        await s.flush()
        a = Alert(
            type=AlertType.schedule_posted.value,
            kid_id=None,
            site_id=site.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="sp-happy",
            payload_json={
                "offering_ids": [off1.id, off2.id],
                "notes": "fall schedule",
            },
            skipped=False,
        )
        s.add(a)
        await s.flush()

        payload = await build_schedule_posted(s, a, [a])

    assert isinstance(payload, SchedulePostedPayload)
    assert payload.site_name == "Lakeshore Rec"
    assert len(payload.new_offerings) == 2
    assert payload.notes == "fall schedule"
    # score key omitted (not match-driven)
    assert "score" not in payload.new_offerings[0]
    assert "score" not in payload.new_offerings[1]


@pytest.mark.asyncio
async def test_build_schedule_posted_no_site_raises(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        a = Alert(
            type=AlertType.schedule_posted.value,
            kid_id=None,
            site_id=None,
            channels=[],
            scheduled_for=NOW,
            dedup_key="sp-nosite",
            payload_json={"offering_ids": [1]},
            skipped=False,
        )
        s.add(a)
        await s.flush()
        with pytest.raises(EmailRenderError):
            await build_schedule_posted(s, a, [a])


@pytest.mark.asyncio
async def test_build_schedule_posted_no_offerings_raises(tmp_path: Any) -> None:
    """No offering_ids in payload AND fallback window yields nothing -> raise."""
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        site = Site(name="Empty Rec", base_url="https://e.example.com", active=True)
        s.add(site)
        await s.flush()
        a = Alert(
            type=AlertType.schedule_posted.value,
            kid_id=None,
            site_id=site.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="sp-empty",
            payload_json={"summary": None},  # no offering_ids
            skipped=False,
        )
        s.add(a)
        await s.flush()
        with pytest.raises(EmailRenderError):
            await build_schedule_posted(s, a, [a])


# ---------------------------------------------------------------------------
# build_crawl_failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_crawl_failed_happy_path(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        site = Site(name="Northshore Athletics", base_url="https://n.example.com", active=True)
        s.add(site)
        await s.flush()
        last_ok = NOW - timedelta(days=2)
        run = CrawlRun(
            site_id=site.id,
            started_at=last_ok - timedelta(minutes=5),
            finished_at=last_ok,
            status=CrawlStatus.ok.value,
            pages_fetched=4,
        )
        s.add(run)
        await s.flush()
        a = Alert(
            type=AlertType.crawl_failed.value,
            kid_id=None,
            site_id=site.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="cf-happy",
            payload_json={
                "consecutive_failures": 3,
                "last_error": "HTTPError 503: Service Unavailable",
            },
            skipped=False,
        )
        s.add(a)
        await s.flush()

        payload = await build_crawl_failed(s, a, [a])

    assert isinstance(payload, CrawlFailedPayload)
    assert payload.site_name == "Northshore Athletics"
    assert payload.failure_count == 3
    assert payload.error_summary == "HTTPError 503: Service Unavailable"
    assert payload.last_success_at is not None
    # CrawlRun.finished_at round-trips through SQLite; we normalize to UTC.
    assert payload.last_success_at.replace(tzinfo=None) == last_ok.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_build_crawl_failed_no_site_raises(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        a = Alert(
            type=AlertType.crawl_failed.value,
            kid_id=None,
            site_id=None,
            channels=[],
            scheduled_for=NOW,
            dedup_key="cf-nosite",
            payload_json={"consecutive_failures": 1, "last_error": "boom"},
            skipped=False,
        )
        s.add(a)
        await s.flush()
        with pytest.raises(EmailRenderError):
            await build_crawl_failed(s, a, [a])


@pytest.mark.asyncio
async def test_build_crawl_failed_truncates_long_error(tmp_path: Any) -> None:
    """Errors longer than 200 chars are truncated with an ellipsis marker."""
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        site = Site(name="Talky Site", base_url="https://t.example.com", active=True)
        s.add(site)
        await s.flush()
        long_err = "ERR: " + ("x" * 500)
        a = Alert(
            type=AlertType.crawl_failed.value,
            kid_id=None,
            site_id=site.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="cf-long",
            payload_json={"consecutive_failures": 7, "last_error": long_err},
            skipped=False,
        )
        s.add(a)
        await s.flush()
        payload = await build_crawl_failed(s, a, [a])

    # Truncation cap is ~200 chars including the ellipsis marker.
    assert len(payload.error_summary) == 200
    assert payload.error_summary.endswith("…")
    assert payload.last_success_at is None  # no successful CrawlRun seeded
    assert payload.failure_count == 7
