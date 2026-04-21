from datetime import date

import pytest
from sqlalchemy import text

from yas.db.base import Base
from yas.db.models import Kid, Offering, Page, Site
from yas.db.session import create_engine_for, session_scope


@pytest.mark.asyncio
async def test_kid_roundtrip(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(name="Sam", dob=date(2019, 5, 1), interests=["soccer", "art"]))
    async with session_scope(engine) as s:
        result = await s.execute(text("select name, dob, interests from kids"))
        row = result.one()
        assert row.name == "Sam"
    await engine.dispose()


@pytest.mark.asyncio
async def test_site_page_offering_roundtrip(tmp_path):
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
            )
        )
    async with session_scope(engine) as s:
        rows = (await s.execute(text("select name, age_min, age_max from offerings"))).all()
        assert rows == [("Little Kickers", 5, 8)]
    await engine.dispose()
