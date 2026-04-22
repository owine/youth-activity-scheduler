from datetime import date, time

import pytest
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import Kid, UnavailabilityBlock
from yas.db.models._types import UnavailabilitySource
from yas.db.session import create_engine_for, session_scope
from yas.unavailability.school_materializer import materialize_school_blocks


async def _setup(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/s.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
    return engine


@pytest.mark.asyncio
async def test_no_school_info_produces_zero_blocks(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await materialize_school_blocks(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(
            select(UnavailabilityBlock).where(UnavailabilityBlock.source == UnavailabilitySource.school.value)
        )).scalars().all()
        assert rows == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_materializes_one_block_per_year_range(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = (await s.execute(select(Kid))).scalar_one()
        kid.school_time_start = time(8, 0)
        kid.school_time_end = time(15, 0)
        kid.school_year_ranges = [
            {"start": "2026-09-02", "end": "2027-06-14"},
            {"start": "2027-09-01", "end": "2028-06-13"},
        ]
    async with session_scope(engine) as s:
        await materialize_school_blocks(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(
            select(UnavailabilityBlock).where(UnavailabilityBlock.source == UnavailabilitySource.school.value)
        )).scalars().all()
        assert len(rows) == 2
        for r in rows:
            assert r.time_start == time(8, 0)
            assert r.time_end == time(15, 0)
            assert r.days_of_week == ["mon", "tue", "wed", "thu", "fri"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_rewrites_on_second_call(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = (await s.execute(select(Kid))).scalar_one()
        kid.school_time_start = time(8, 0)
        kid.school_time_end = time(15, 0)
        kid.school_year_ranges = [{"start": "2026-09-02", "end": "2027-06-14"}]
    async with session_scope(engine) as s:
        await materialize_school_blocks(s, kid_id=1)
    # change the schedule
    async with session_scope(engine) as s:
        kid = (await s.execute(select(Kid))).scalar_one()
        kid.school_time_start = time(9, 0)
        kid.school_time_end = time(16, 0)
    async with session_scope(engine) as s:
        await materialize_school_blocks(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(
            select(UnavailabilityBlock).where(UnavailabilityBlock.source == UnavailabilitySource.school.value)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].time_start == time(9, 0)
        assert rows[0].time_end == time(16, 0)
    await engine.dispose()


@pytest.mark.asyncio
async def test_partial_school_info_produces_zero_blocks(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        kid = (await s.execute(select(Kid))).scalar_one()
        kid.school_time_start = time(8, 0)
        # school_time_end left null
        kid.school_year_ranges = [{"start": "2026-09-02", "end": "2027-06-14"}]
    async with session_scope(engine) as s:
        await materialize_school_blocks(s, kid_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(
            select(UnavailabilityBlock).where(UnavailabilityBlock.source == UnavailabilitySource.school.value)
        )).scalars().all()
        assert rows == []
    await engine.dispose()
