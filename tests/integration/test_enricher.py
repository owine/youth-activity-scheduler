import pytest
from sqlalchemy import select

from tests.fakes.geocoder import FakeGeocoder
from yas.db.base import Base
from yas.db.models import GeocodeAttempt, Location
from yas.db.session import create_engine_for, session_scope
from yas.geo.client import GeocodeResult
from yas.geo.enricher import enrich_ungeocoded_locations


async def _setup(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/e.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_enricher_populates_coords(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="Lincoln Park Rec", address="2045 N Lincoln Park W, Chicago, IL"))
    geocoder = FakeGeocoder(fixtures={
        "2045 n lincoln park w, chicago, il": GeocodeResult(
            lat=41.9214, lon=-87.6351, display_name="Lincoln Park", provider="fake",
        )
    })
    async with session_scope(engine) as s:
        result = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert result.updated == 1
    async with session_scope(engine) as s:
        loc = (await s.execute(select(Location))).scalar_one()
        assert loc.lat == pytest.approx(41.9214)
        assert loc.lon == pytest.approx(-87.6351)
    await engine.dispose()


@pytest.mark.asyncio
async def test_enricher_records_not_found_and_skips_on_retry(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="X", address="Nowheresville, XX"))
    geocoder = FakeGeocoder(misses={"nowheresville, xx"})
    async with session_scope(engine) as s:
        r1 = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert r1.not_found == 1
    async with session_scope(engine) as s:
        r2 = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert r2.skipped == 1   # skipped due to prior not_found
    async with session_scope(engine) as s:
        rows = (await s.execute(select(GeocodeAttempt))).scalars().all()
        assert len(rows) == 1
        assert rows[0].result == "not_found"
    assert geocoder.call_count == 1   # second call skipped
    await engine.dispose()


@pytest.mark.asyncio
async def test_enricher_records_error(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="X", address="error-please"))
    geocoder = FakeGeocoder(errors={"error-please"})
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert r.errored == 1
    async with session_scope(engine) as s:
        rows = (await s.execute(select(GeocodeAttempt))).scalars().all()
        assert len(rows) == 1
        assert rows[0].result == "error"
    await engine.dispose()
