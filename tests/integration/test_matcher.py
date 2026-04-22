from datetime import date, time

import pytest
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import (
    Enrollment,
    HouseholdSettings,
    Kid,
    Match,
    Offering,
    Page,
    Site,
    UnavailabilityBlock,
    WatchlistEntry,
)
from yas.db.models._types import (
    EnrollmentStatus,
    OfferingStatus,
    ProgramType,
    UnavailabilitySource,
    WatchlistPriority,
)
from yas.db.session import create_engine_for, session_scope
from yas.matching.matcher import rematch_kid, rematch_offering


async def _setup(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/m.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(HouseholdSettings(id=1, default_max_distance_mi=20.0))
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
    return engine


async def _kid(session, **kwargs):
    defaults = dict(name="Sam", dob=date(2019, 5, 1), interests=["soccer"], active=True)
    defaults.update(kwargs)
    k = Kid(**defaults)
    session.add(k)
    await session.flush()
    return k


async def _offering(session, **kwargs):
    defaults = dict(
        site_id=1,
        page_id=1,
        name="Spring Soccer",
        normalized_name="spring soccer",
        program_type=ProgramType.soccer.value,
        age_min=6,
        age_max=8,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 6, 30),
        days_of_week=["sat"],
        time_start=time(9, 0),
        time_end=time(10, 0),
        status=OfferingStatus.active.value,
    )
    defaults.update(kwargs)
    o = Offering(**defaults)
    session.add(o)
    await session.flush()
    return o


@pytest.mark.asyncio
async def test_rematch_kid_writes_matching_row(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await _kid(s)
        await _offering(s)
    async with session_scope(engine) as s:
        result = await rematch_kid(s, kid_id=1)
    assert len(result.new) == 1
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Match))).scalars().all()
        assert len(rows) == 1
        assert rows[0].kid_id == 1
        assert 0.0 <= rows[0].score <= 1.0
        assert "gates" in rows[0].reasons
        assert "score_breakdown" in rows[0].reasons
    await engine.dispose()


@pytest.mark.asyncio
async def test_age_gate_uses_start_date(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        # kid is 4 today but turns 5 on 2026-05-01
        await _kid(s, dob=date(2021, 5, 1), interests=["soccer"])
        await _offering(s, age_min=5, start_date=date(2026, 5, 15))
    async with session_scope(engine) as s:
        await rematch_kid(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Match))).scalars().all()
        assert len(rows) == 1  # matched despite today's age = 4


@pytest.mark.asyncio
async def test_summer_offering_passes_school_year_gate(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = await _kid(s, interests=["soccer"])
        # school block covers 2026-09..2027-06
        s.add(
            UnavailabilityBlock(
                kid_id=kid.id,
                source=UnavailabilitySource.school.value,
                days_of_week=["mon", "tue", "wed", "thu", "fri"],
                time_start=time(8, 0),
                time_end=time(15, 0),
                date_start=date(2026, 9, 2),
                date_end=date(2027, 6, 14),
            )
        )
        await _offering(
            s,
            start_date=date(2026, 6, 15),
            end_date=date(2026, 8, 15),
            days_of_week=["mon", "wed"],
            time_start=time(9, 0),
            time_end=time(12, 0),
        )
    async with session_scope(engine) as s:
        await rematch_kid(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Match))).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_watchlist_bypasses_all_hard_gates(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = await _kid(s, interests=["swim"], max_distance_mi=1.0)  # not soccer; tiny distance
        # location with unavailable coords so distance stays unknown = fail-open on distance
        s.add(
            WatchlistEntry(
                id=1,
                kid_id=kid.id,
                pattern="spring soccer",
                priority=WatchlistPriority.high.value,
                active=True,
                ignore_hard_gates=False,
            )
        )
        await _offering(s)  # program_type soccer, age 6-8 (kid is 6 on 2026-05-01)
    async with session_scope(engine) as s:
        await rematch_kid(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Match))).scalars().all()
        assert len(rows) == 1
        assert rows[0].reasons.get("watchlist_hit") is not None


@pytest.mark.asyncio
async def test_enrollment_block_prevents_sibling_match(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid_a = await _kid(s, interests=["soccer"])
        kid_b = await _kid(s, name="Kid B", dob=date(2019, 5, 1), interests=["soccer"])
        sat_9 = await _offering(s, name="Sat 9am Soccer")
        sat_9_other = await _offering(s, name="Sat 9am Other Soccer")
        s.add(
            Enrollment(
                id=1,
                kid_id=kid_a.id,
                offering_id=sat_9.id,
                status=EnrollmentStatus.enrolled.value,
            )
        )
        await s.flush()
        # materialize the enrollment block manually (avoiding materializer coupling here)
        s.add(
            UnavailabilityBlock(
                kid_id=kid_a.id,
                source=UnavailabilitySource.enrollment.value,
                source_enrollment_id=1,
                days_of_week=["sat"],
                time_start=time(9, 0),
                time_end=time(10, 0),
                date_start=date(2026, 5, 1),
                date_end=date(2026, 6, 30),
            )
        )
    async with session_scope(engine) as s:
        await rematch_kid(s, kid_id=kid_a.id)
        await rematch_kid(s, kid_id=kid_b.id)
    async with session_scope(engine) as s:
        # Kid A matches the enrolled offering (obviously) but not the conflicting sibling
        rows_a = (await s.execute(select(Match).where(Match.kid_id == kid_a.id))).scalars().all()
        assert {m.offering_id for m in rows_a} == {sat_9.id}  # conflicting sibling filtered
        # Kid B is unaffected and matches both soccer offerings
        rows_b = (await s.execute(select(Match).where(Match.kid_id == kid_b.id))).scalars().all()
        assert {m.offering_id for m in rows_b} == {sat_9.id, sat_9_other.id}


@pytest.mark.asyncio
async def test_failed_gate_removes_existing_match(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = await _kid(s, interests=["soccer"])
        await _offering(s)
    async with session_scope(engine) as s:
        await rematch_kid(s, kid_id=1)
    async with session_scope(engine) as s:
        # change the kid to a different age so the match should drop
        kid = (await s.execute(select(Kid))).scalar_one()
        kid.dob = date(2010, 1, 1)  # kid is ~16
    async with session_scope(engine) as s:
        await rematch_kid(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Match))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_rematch_offering_touches_all_kids(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await _kid(s)
        await _kid(s, name="Sib", interests=["soccer"])
        await _offering(s)
    async with session_scope(engine) as s:
        await rematch_offering(s, offering_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Match))).scalars().all()
        assert len(rows) == 2
