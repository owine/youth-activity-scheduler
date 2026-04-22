import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.fakes.geocoder import FakeGeocoder
from yas.db.base import Base
from yas.db.models import Location
from yas.db.session import create_engine_for, session_scope
from yas.geo.client import GeocodeResult
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/h.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    geocoder = FakeGeocoder(
        fixtures={
            "123 main st, chicago, il": GeocodeResult(
                lat=41.88,
                lon=-87.63,
                display_name="Chicago",
                provider="fake",
            )
        }
    )
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=geocoder)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine, geocoder
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_household_creates_default_row(client):
    c, _, _ = client
    r = await c.get("/api/household")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 1
    assert body["default_max_distance_mi"] is None
    assert body["home_location_id"] is None


@pytest.mark.asyncio
async def test_patch_default_max_distance(client):
    c, _, _ = client
    r = await c.patch("/api/household", json={"default_max_distance_mi": 15.0})
    assert r.status_code == 200
    assert r.json()["default_max_distance_mi"] == 15.0


@pytest.mark.asyncio
async def test_patch_home_address_triggers_immediate_geocode(client):
    c, engine, geocoder = client
    r = await c.patch(
        "/api/household",
        json={"home_address": "123 Main St, Chicago, IL", "home_location_name": "Home"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["home_location_id"] is not None
    assert geocoder.call_count >= 1
    async with session_scope(engine) as s:
        loc = (
            await s.execute(select(Location).where(Location.id == body["home_location_id"]))
        ).scalar_one()
        assert loc.lat == 41.88
        assert loc.lon == -87.63


@pytest.mark.asyncio
async def test_patch_home_address_geocode_miss_still_saves(client):
    c, engine, geocoder = client
    geocoder.misses.add("nowhereville, xx")
    r = await c.patch(
        "/api/household",
        json={"home_address": "Nowhereville, XX", "home_location_name": "Home"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["home_location_id"] is not None  # location created
    async with session_scope(engine) as s:
        loc = (
            await s.execute(select(Location).where(Location.id == body["home_location_id"]))
        ).scalar_one()
        assert loc.lat is None  # miss — enricher will retry never (negative-cached)
