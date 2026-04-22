from datetime import date, time

import pytest
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import Enrollment, Kid, Offering, Page, Site, UnavailabilityBlock
from yas.db.models._types import EnrollmentStatus, UnavailabilitySource
from yas.db.session import create_engine_for, session_scope
from yas.unavailability.enrollment_materializer import apply_enrollment_block


async def _setup(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/e.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        site = Site(id=1, name="X", base_url="https://x")
        s.add(site)
        await s.flush()
        page = Page(id=1, site_id=1, url="https://x/p")
        s.add(page)
        await s.flush()
        s.add(
            Offering(
                id=1,
                site_id=1,
                page_id=1,
                name="Sat Soccer",
                normalized_name="sat soccer",
                start_date=date(2026, 5, 1),
                end_date=date(2026, 6, 30),
                days_of_week=["sat"],
                time_start=time(9, 0),
                time_end=time(10, 0),
            )
        )
        await s.flush()
        s.add(Enrollment(id=1, kid_id=1, offering_id=1, status=EnrollmentStatus.interested.value))
    return engine


@pytest.mark.asyncio
async def test_interested_does_not_create_block(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        await apply_enrollment_block(s, enrollment_id=1)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert rows == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_enrolled_creates_block(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        e = (await s.execute(select(Enrollment))).scalar_one()
        e.status = EnrollmentStatus.enrolled.value
    async with session_scope(engine) as s:
        await apply_enrollment_block(s, enrollment_id=1)
    async with session_scope(engine) as s:
        blocks = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert len(blocks) == 1
        b = blocks[0]
        assert b.source == UnavailabilitySource.enrollment.value
        assert b.source_enrollment_id == 1
        assert b.days_of_week == ["sat"]
        assert b.time_start == time(9, 0)
        assert b.date_start == date(2026, 5, 1)
    await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_deletes_block(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        e = (await s.execute(select(Enrollment))).scalar_one()
        e.status = EnrollmentStatus.enrolled.value
    async with session_scope(engine) as s:
        await apply_enrollment_block(s, enrollment_id=1)
    async with session_scope(engine) as s:
        e = (await s.execute(select(Enrollment))).scalar_one()
        e.status = EnrollmentStatus.cancelled.value
    async with session_scope(engine) as s:
        await apply_enrollment_block(s, enrollment_id=1)
    async with session_scope(engine) as s:
        blocks = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert blocks == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_on_second_call(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        e = (await s.execute(select(Enrollment))).scalar_one()
        e.status = EnrollmentStatus.enrolled.value
    async with session_scope(engine) as s:
        await apply_enrollment_block(s, enrollment_id=1)
    async with session_scope(engine) as s:
        await apply_enrollment_block(s, enrollment_id=1)
    async with session_scope(engine) as s:
        blocks = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert len(blocks) == 1
    await engine.dispose()
