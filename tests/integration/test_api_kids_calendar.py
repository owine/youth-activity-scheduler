"""Integration tests for GET /api/kids/{kid_id}/calendar."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import (
    Enrollment,
    Kid,
    Match,
    Offering,
    Page,
    Site,
    UnavailabilityBlock,
)
from yas.db.models._types import (
    EnrollmentStatus,
    OfferingStatus,
    UnavailabilitySource,
)
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/c.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


async def _seed_kid_with_enrollment(engine, *, kid_id=1, offering_id=1):
    async with session_scope(engine) as s:
        s.add(Kid(id=kid_id, name="Sam", dob=date(2019, 5, 1)))
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        s.add(
            Offering(
                id=offering_id,
                site_id=1,
                page_id=1,
                name="T-Ball",
                normalized_name="t-ball",
                days_of_week=["tue", "thu"],
                time_start=time(16, 0),
                time_end=time(17, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
            )
        )
        await s.flush()
        s.add(
            Enrollment(
                id=10,
                kid_id=kid_id,
                offering_id=offering_id,
                status=EnrollmentStatus.enrolled.value,
                enrolled_at=datetime.now(UTC),
            )
        )


@pytest.mark.asyncio
async def test_returns_404_for_unknown_kid(client):
    c, _ = client
    r = await c.get("/api/kids/9999/calendar?from=2026-04-27&to=2026-05-04")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_returns_422_when_from_not_before_to(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    r = await c.get("/api/kids/1/calendar?from=2026-05-04&to=2026-04-27")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_returns_422_when_range_exceeds_90_days(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    r = await c.get("/api/kids/1/calendar?from=2026-01-01&to=2026-04-15")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_returns_enrolled_offering_occurrences(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    assert r.status_code == 200
    body = r.json()
    assert body["kid_id"] == 1
    assert body["from"] == "2026-04-27"
    assert body["to"] == "2026-05-04"
    enrollment_events = [e for e in body["events"] if e["kind"] == "enrollment"]
    # Tue 2026-04-28 + Thu 2026-04-30; offering's date range is broader.
    assert len(enrollment_events) == 2
    dates = sorted(e["date"] for e in enrollment_events)
    assert dates == ["2026-04-28", "2026-04-30"]
    e = enrollment_events[0]
    assert e["enrollment_id"] == 10
    assert e["offering_id"] == 1
    assert e["status"] == "enrolled"
    assert e["title"] == "T-Ball"
    assert e["time_start"] == "16:00:00"
    assert e["all_day"] is False


@pytest.mark.asyncio
async def test_excludes_cancelled_enrollments(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    async with session_scope(engine) as s:
        e = (await s.execute(select(Enrollment).where(Enrollment.id == 10))).scalar_one()
        e.status = EnrollmentStatus.cancelled.value
    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    body = r.json()
    assert [e for e in body["events"] if e["kind"] == "enrollment"] == []


@pytest.mark.asyncio
async def test_returns_unavailability_blocks_with_from_enrollment_id(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    async with session_scope(engine) as s:
        s.add(
            UnavailabilityBlock(
                id=20,
                kid_id=1,
                source=UnavailabilitySource.school.value,
                label="School",
                days_of_week=["mon", "tue", "wed", "thu", "fri"],
                time_start=time(8, 30),
                time_end=time(15, 0),
                date_start=date(2026, 1, 1),
                date_end=date(2026, 6, 30),
                active=True,
            )
        )
        s.add(
            UnavailabilityBlock(
                id=21,
                kid_id=1,
                source=UnavailabilitySource.enrollment.value,
                label="T-Ball",
                days_of_week=["tue", "thu"],
                time_start=time(16, 0),
                time_end=time(17, 0),
                date_start=date(2026, 4, 1),
                date_end=date(2026, 6, 30),
                active=True,
                source_enrollment_id=10,
            )
        )
    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    body = r.json()
    school = [e for e in body["events"] if e["kind"] == "unavailability" and e["block_id"] == 20]
    assert len(school) == 5  # Mon..Fri
    assert school[0]["from_enrollment_id"] is None
    enrollment_block = [
        e for e in body["events"] if e["kind"] == "unavailability" and e["block_id"] == 21
    ]
    assert len(enrollment_block) == 2  # Tue, Thu
    assert enrollment_block[0]["from_enrollment_id"] == 10


@pytest.mark.asyncio
async def test_excludes_inactive_blocks(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    async with session_scope(engine) as s:
        s.add(
            UnavailabilityBlock(
                id=22,
                kid_id=1,
                source=UnavailabilitySource.manual.value,
                days_of_week=["wed"],
                time_start=time(13, 0),
                time_end=time(14, 0),
                date_start=date(2026, 4, 1),
                date_end=date(2026, 6, 30),
                active=False,
            )
        )
    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    body = r.json()
    assert all(e.get("block_id") != 22 for e in body["events"])


@pytest.mark.asyncio
async def test_excludes_other_kids_events(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    async with session_scope(engine) as s:
        s.add(Kid(id=2, name="Riley", dob=date(2017, 3, 1)))
        await s.flush()
        s.add(
            Enrollment(
                id=11,
                kid_id=2,
                offering_id=1,
                status=EnrollmentStatus.enrolled.value,
            )
        )
    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    body = r.json()
    assert all(e.get("enrollment_id") != 11 for e in body["events"])


@pytest.mark.asyncio
async def test_sort_handles_all_day_and_timed_events_on_same_date(client):
    """Regression: sort key must not mix `time` and `str` (or `None`).

    All-day events have time_start == None. Timed events have time_start
    set. If both fall on the same date, the sort key fires a tuple
    comparison that crashes if we don't coerce to a single comparable type.
    """
    c, engine = client
    await _seed_kid_with_enrollment(engine)
    async with session_scope(engine) as s:
        # All-day manual block on 2026-04-28 (Tuesday — same date as the T-Ball enrollment).
        s.add(
            UnavailabilityBlock(
                id=30,
                kid_id=1,
                source=UnavailabilitySource.manual.value,
                label="Day off",
                days_of_week=["tue"],
                time_start=None,
                time_end=None,
                date_start=date(2026, 4, 1),
                date_end=date(2026, 6, 30),
                active=True,
            )
        )
    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    assert r.status_code == 200
    body = r.json()
    same_date = [e for e in body["events"] if e["date"] == "2026-04-28"]
    # One enrollment (timed) + one all-day block on Tuesday.
    assert len(same_date) == 2
    assert any(e["all_day"] is True for e in same_date)
    assert any(e["all_day"] is False for e in same_date)


async def _seed_match(engine, *, kid_id: int, offering_id: int, score: float) -> None:
    async with session_scope(engine) as s:
        s.add(
            Match(
                kid_id=kid_id,
                offering_id=offering_id,
                score=score,
                reasons={},
                computed_at=datetime.now(UTC),
            )
        )


@pytest.mark.asyncio
async def test_match_overlay_flag_off_returns_no_match_events(client):
    """Default include_matches=false: behavior unchanged from 5c-1."""
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    async with session_scope(engine) as s:
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                days_of_week=["wed"],
                time_start=time(17, 0),
                time_end=time(18, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.85)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    assert r.status_code == 200
    body = r.json()
    assert all(e["kind"] != "match" for e in body["events"])


@pytest.mark.asyncio
async def test_match_overlay_returns_high_score_matches(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    async with session_scope(engine) as s:
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                days_of_week=["wed"],
                time_start=time(17, 0),
                time_end=time(18, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
                registration_url="https://example.com/register/soccer",
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.85)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    matches = [e for e in body["events"] if e["kind"] == "match"]
    assert len(matches) == 1
    m = matches[0]
    assert m["offering_id"] == 2
    assert m["score"] == 0.85
    assert m["registration_url"] == "https://example.com/register/soccer"
    assert m["title"] == "Soccer"
    assert m["date"] == "2026-04-29"
    assert m["id"] == "match:2:2026-04-29"


@pytest.mark.asyncio
async def test_match_overlay_score_threshold_boundary(client):
    """Threshold is >=0.6: 0.59 excluded, 0.60 included, 0.61 included."""
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    cases = [(2, 0.59), (3, 0.60), (4, 0.61)]
    async with session_scope(engine) as s:
        for off_id, _ in cases:
            s.add(
                Offering(
                    id=off_id,
                    site_id=1,
                    page_id=1,
                    name=f"Off-{off_id}",
                    normalized_name=f"off-{off_id}",
                    days_of_week=["wed"],
                    time_start=time(17, 0),
                    time_end=time(18, 0),
                    start_date=date(2026, 4, 1),
                    end_date=date(2026, 6, 30),
                    status=OfferingStatus.active.value,
                )
            )
    for off_id, score in cases:
        await _seed_match(engine, kid_id=1, offering_id=off_id, score=score)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    match_offering_ids = {e["offering_id"] for e in body["events"] if e["kind"] == "match"}
    assert match_offering_ids == {3, 4}


@pytest.mark.asyncio
async def test_match_overlay_excludes_already_enrolled(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    await _seed_match(engine, kid_id=1, offering_id=1, score=0.95)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    assert all(e["kind"] != "match" for e in body["events"])


@pytest.mark.asyncio
async def test_match_overlay_excludes_interested_and_waitlisted(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    async with session_scope(engine) as s:
        for off_id in (2, 3):
            s.add(
                Offering(
                    id=off_id,
                    site_id=1,
                    page_id=1,
                    name=f"Off-{off_id}",
                    normalized_name=f"off-{off_id}",
                    days_of_week=["wed"],
                    time_start=time(17, 0),
                    time_end=time(18, 0),
                    start_date=date(2026, 4, 1),
                    end_date=date(2026, 6, 30),
                    status=OfferingStatus.active.value,
                )
            )
        await s.flush()
        s.add(
            Enrollment(
                id=20,
                kid_id=1,
                offering_id=2,
                status=EnrollmentStatus.interested.value,
            )
        )
        s.add(
            Enrollment(
                id=21,
                kid_id=1,
                offering_id=3,
                status=EnrollmentStatus.waitlisted.value,
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.9)
    await _seed_match(engine, kid_id=1, offering_id=3, score=0.9)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    assert all(e["kind"] != "match" for e in body["events"])


@pytest.mark.asyncio
async def test_match_overlay_includes_offerings_with_only_cancelled_enrollment(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    async with session_scope(engine) as s:
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                days_of_week=["wed"],
                time_start=time(17, 0),
                time_end=time(18, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
            )
        )
        await s.flush()
        s.add(
            Enrollment(
                id=22,
                kid_id=1,
                offering_id=2,
                status=EnrollmentStatus.cancelled.value,
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.85)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    matches = [e for e in body["events"] if e["kind"] == "match"]
    assert len(matches) == 1
    assert matches[0]["offering_id"] == 2


@pytest.mark.asyncio
async def test_match_overlay_excludes_muted_offerings(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    future = datetime.now(UTC) + timedelta(days=30)
    async with session_scope(engine) as s:
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                days_of_week=["wed"],
                time_start=time(17, 0),
                time_end=time(18, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
                muted_until=future,
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.9)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    assert all(e["kind"] != "match" for e in body["events"])


@pytest.mark.asyncio
async def test_match_overlay_excludes_offering_whose_site_is_muted(client):
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    future = datetime.now(UTC) + timedelta(days=30)
    async with session_scope(engine) as s:
        site = (await s.execute(select(Site).where(Site.id == 1))).scalar_one()
        site.muted_until = future
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                days_of_week=["wed"],
                time_start=time(17, 0),
                time_end=time(18, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.9)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    assert all(e["kind"] != "match" for e in body["events"])


@pytest.mark.asyncio
async def test_match_overlay_includes_offering_whose_mute_expired(client):
    """A muted_until in the past doesn't suppress the match."""
    c, engine = client
    await _seed_kid_with_enrollment(engine, kid_id=1, offering_id=1)
    past = datetime.now(UTC) - timedelta(days=1)
    async with session_scope(engine) as s:
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                days_of_week=["wed"],
                time_start=time(17, 0),
                time_end=time(18, 0),
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                status=OfferingStatus.active.value,
                muted_until=past,
            )
        )
    await _seed_match(engine, kid_id=1, offering_id=2, score=0.9)

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04&include_matches=true")
    body = r.json()
    matches = [e for e in body["events"] if e["kind"] == "match"]
    assert len(matches) == 1


# Phase 8-2 holiday / school-year integration


async def _seed_kid_with_school(
    engine,
    *,
    kid_id: int = 1,
    holidays: list[str] | None = None,
    year_ranges: list[dict[str, str]] | None = None,
    school_block: bool = True,
) -> None:
    async with session_scope(engine) as s:
        s.add(
            Kid(
                id=kid_id,
                name="Sam",
                dob=date(2019, 5, 1),
                school_weekdays=["mon", "tue", "wed", "thu", "fri"],
                school_time_start=time(8, 0),
                school_time_end=time(15, 0),
                school_year_ranges=year_ranges or [{"start": "2026-04-01", "end": "2026-06-30"}],
                school_holidays=holidays or [],
            )
        )
        if school_block:
            s.add(
                UnavailabilityBlock(
                    kid_id=kid_id,
                    source=UnavailabilitySource.school.value,
                    label="School",
                    days_of_week=["mon", "tue", "wed", "thu", "fri"],
                    time_start=time(8, 0),
                    time_end=time(15, 0),
                    date_start=date(2026, 4, 1),
                    date_end=date(2026, 6, 30),
                    active=True,
                )
            )


@pytest.mark.asyncio
async def test_holiday_skips_school_block_render(client):
    """A holiday on a school weekday hides the school occurrence."""
    c, engine = client
    # Wed 2026-04-29 is a school weekday.
    await _seed_kid_with_school(engine, holidays=["2026-04-29"])

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    body = r.json()
    school_on_holiday = [
        e for e in body["events"] if e["kind"] == "unavailability" and e["date"] == "2026-04-29"
    ]
    assert school_on_holiday == []


@pytest.mark.asyncio
async def test_holiday_event_emitted_in_range_and_school_year(client):
    """Holidays within range and inside a school_year_range get a holiday event."""
    c, engine = client
    await _seed_kid_with_school(engine, holidays=["2026-04-29"])

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    body = r.json()
    holidays = [e for e in body["events"] if e["kind"] == "holiday"]
    assert len(holidays) == 1
    assert holidays[0]["date"] == "2026-04-29"
    assert holidays[0]["all_day"] is True
    assert holidays[0]["title"] == "Holiday"


@pytest.mark.asyncio
async def test_holiday_outside_school_year_not_emitted(client):
    """A holiday date outside any school_year_range is not rendered."""
    c, engine = client
    # July 4 falls outside 2026-04-01..2026-06-30.
    await _seed_kid_with_school(engine, holidays=["2026-07-04"])

    r = await c.get("/api/kids/1/calendar?from=2026-07-01&to=2026-07-08")
    body = r.json()
    holidays = [e for e in body["events"] if e["kind"] == "holiday"]
    assert holidays == []


@pytest.mark.asyncio
async def test_holiday_outside_request_range_not_emitted(client):
    """A holiday date outside the from/to window is not rendered."""
    c, engine = client
    await _seed_kid_with_school(engine, holidays=["2026-04-29"])

    r = await c.get("/api/kids/1/calendar?from=2026-05-04&to=2026-05-11")
    body = r.json()
    holidays = [e for e in body["events"] if e["kind"] == "holiday"]
    assert holidays == []


@pytest.mark.asyncio
async def test_non_school_block_unaffected_by_holidays(client):
    """A manual unavailability block on a holiday date still renders."""
    c, engine = client
    await _seed_kid_with_school(engine, holidays=["2026-04-29"], school_block=False)
    async with session_scope(engine) as s:
        s.add(
            UnavailabilityBlock(
                kid_id=1,
                source=UnavailabilitySource.manual.value,
                label="Doctor",
                days_of_week=["wed"],
                time_start=time(10, 0),
                time_end=time(11, 0),
                date_start=date(2026, 4, 29),
                date_end=date(2026, 4, 29),
                active=True,
            )
        )

    r = await c.get("/api/kids/1/calendar?from=2026-04-27&to=2026-05-04")
    body = r.json()
    manual = [
        e
        for e in body["events"]
        if e["kind"] == "unavailability" and e["source"] == "manual" and e["date"] == "2026-04-29"
    ]
    assert len(manual) == 1
