from datetime import date

import pytest
from sqlalchemy import select

from yas.crawl.reconciler import reconcile
from yas.db.base import Base
from yas.db.models import Offering, Page, Site
from yas.db.models._types import OfferingStatus, ProgramType
from yas.db.session import create_engine_for, session_scope
from yas.llm.schemas import ExtractedOffering


async def _setup(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/r.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        site = Site(name="Test", base_url="https://t")
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="https://t/p")
        s.add(page)
        await s.flush()
        site_id, page_id = site.id, page.id
    return engine, site_id, page_id


def _offering(name, program_type=ProgramType.soccer, start_date=None, **extra):
    return ExtractedOffering(name=name, program_type=program_type, start_date=start_date, **extra)


@pytest.mark.asyncio
async def test_empty_to_some_inserts(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [_offering("Kickers", start_date=date(2026, 5, 1))])
    assert len(result.new) == 1 and not result.updated and not result.withdrawn
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Offering))).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == OfferingStatus.active
    await engine.dispose()


@pytest.mark.asyncio
async def test_same_key_same_fields_is_unchanged(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    o = _offering("Kickers", age_min=6, age_max=8, start_date=date(2026, 5, 1))
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [o])
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [o])
    assert result.new == [] and result.updated == [] and result.withdrawn == []
    assert len(result.unchanged) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_same_key_different_price_triggers_update(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    key_args = dict(name="Kickers", start_date=date(2026, 5, 1))
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [_offering(price_cents=8500, **key_args)])
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [_offering(price_cents=9500, **key_args)])
    assert len(result.updated) == 1 and result.new == []
    async with session_scope(engine) as s:
        row = (await s.execute(select(Offering))).scalars().one()
        assert row.price_cents == 9500
    await engine.dispose()


@pytest.mark.asyncio
async def test_missing_key_withdraws(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [_offering("Kickers", start_date=date(2026, 5, 1))])
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [])
    assert len(result.withdrawn) == 1
    async with session_scope(engine) as s:
        row = (await s.execute(select(Offering))).scalars().one()
        assert row.status == OfferingStatus.withdrawn
    await engine.dispose()


@pytest.mark.asyncio
async def test_different_start_dates_are_different_keys(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    o1 = _offering("Kickers", start_date=date(2026, 5, 1))
    o2 = _offering("Kickers", start_date=date(2026, 6, 1))
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [o1])
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [o2])
    assert len(result.new) == 1 and len(result.withdrawn) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_null_start_date_matches_across_runs(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    o = _offering("Kickers", start_date=None, age_min=5, age_max=7)
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [o])
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [o])
    assert result.new == [] and result.updated == []
    assert len(result.unchanged) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_withdrawn_reappearance_inserts_new_row(tmp_path):
    engine, _, page_id = await _setup(tmp_path)
    o = _offering("Kickers", start_date=date(2026, 5, 1))
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [o])
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [])  # withdraw
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        result = await reconcile(s, page, [o])  # reappear
    assert len(result.new) == 1
    async with session_scope(engine) as s:
        rows = (await s.execute(select(Offering))).scalars().all()
        assert len(rows) == 2  # old withdrawn + new active
    await engine.dispose()


@pytest.mark.asyncio
async def test_location_name_creates_or_reuses_location(tmp_path):
    engine, _site_id, page_id = await _setup(tmp_path)
    o = _offering(
        "Kickers",
        start_date=date(2026, 5, 1),
        location_name="Lincoln Park Rec",
        location_address="123 N Clark St",
    )
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [o])
    # second reconcile, same location name — should NOT create a duplicate.
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        await reconcile(s, page, [o])
    async with session_scope(engine) as s:
        from yas.db.models import Location

        rows = (await s.execute(select(Location))).scalars().all()
        assert len(rows) == 1
        assert rows[0].name == "Lincoln Park Rec"
    await engine.dispose()
