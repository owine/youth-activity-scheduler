from datetime import date

import pytest
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import Kid, Offering, Page, Site
from yas.db.session import create_engine_for, session_scope


@pytest.mark.asyncio
async def test_kid_roundtrip(tmp_path):
    """Round-trip a Kid through the ORM and verify JSON + default columns survive."""
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(name="Sam", dob=date(2019, 5, 1), interests=["soccer", "art"]))
    async with session_scope(engine) as s:
        kid = (await s.execute(select(Kid))).scalar_one()
        assert kid.name == "Sam"
        assert kid.dob == date(2019, 5, 1)
        assert kid.interests == ["soccer", "art"]
        # timestamp_column default must populate on ORM insert.
        assert kid.created_at is not None
        # JSON defaults must materialize as empty containers, not None.
        assert kid.availability == {}
        assert kid.alert_on == {}
        assert kid.school_holidays == []
        assert kid.school_year_ranges == []
        # Default weekdays come from the `lambda: [...]` default.
        assert kid.school_weekdays == ["mon", "tue", "wed", "thu", "fri"]
        # Active defaults True.
        assert kid.active is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_site_page_offering_roundtrip(tmp_path):
    """Write Site → Page → Offering via FKs and read them back via the ORM."""
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        site = Site(name="Park District", base_url="https://example.com")
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="https://example.com/schedule")
        s.add(page)
        await s.flush()
        s.add(
            Offering(
                site_id=site.id,
                page_id=page.id,
                name="Little Kickers",
                normalized_name="little kickers",
                age_min=5,
                age_max=8,
                days_of_week=["sat"],
            )
        )
    async with session_scope(engine) as s:
        offering = (await s.execute(select(Offering))).scalar_one()
        assert offering.name == "Little Kickers"
        assert offering.age_min == 5
        assert offering.age_max == 8
        assert offering.days_of_week == ["sat"]
        assert offering.first_seen is not None
        assert offering.last_seen is not None
        # Enum column stored as string; default must be the active sentinel.
        assert offering.status == "active"
        # raw_json default is {}.
        assert offering.raw_json == {}
    await engine.dispose()
