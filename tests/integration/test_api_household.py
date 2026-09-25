import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.fakes.geocoder import FakeGeocoder
from yas.db.base import Base
from yas.db.models import GeocodeAttempt, HouseholdSettings, Location
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
        assert loc.lat is None  # miss — negative-cached; the enricher won't retry it


@pytest.mark.asyncio
async def test_patch_notifier_configs_persist(client):
    c, engine, _ = client
    r = await c.patch(
        "/api/household",
        json={
            "smtp_config_json": {
                "transport": "smtp",
                "host": "mailpit",
                "port": 1025,
                "secure": False,
            },
            "ntfy_config_json": {"topic": "yas-alerts", "server": "https://ntfy.sh"},
            "pushover_config_json": {"user_key_env": "YAS_PUSHOVER_USER_KEY"},
            "ha_config_json": {"base_url": "http://homeassistant.local:8123"},
        },
    )
    assert r.status_code == 200
    async with session_scope(engine) as s:
        hh = (await s.execute(select(HouseholdSettings))).scalars().one()
        assert hh.smtp_config_json == {
            "transport": "smtp",
            "host": "mailpit",
            "port": 1025,
            "secure": False,
        }
        assert hh.ntfy_config_json == {"topic": "yas-alerts", "server": "https://ntfy.sh"}
        assert hh.pushover_config_json == {"user_key_env": "YAS_PUSHOVER_USER_KEY"}
        assert hh.ha_config_json == {"base_url": "http://homeassistant.local:8123"}


@pytest.mark.asyncio
async def test_get_household_returns_address_and_name_when_set(client):
    c, _, _ = client
    await c.patch(
        "/api/household",
        json={"home_address": "123 Main St, Chicago, IL", "home_location_name": "Home"},
    )
    r = await c.get("/api/household")
    assert r.status_code == 200
    body = r.json()
    assert body["home_address"] == "123 Main St, Chicago, IL"
    assert body["home_location_name"] == "Home"


@pytest.mark.asyncio
async def test_get_household_returns_null_address_when_unset(client):
    c, _, _ = client
    r = await c.get("/api/household")
    assert r.status_code == 200
    body = r.json()
    assert body["home_address"] is None
    assert body["home_location_name"] is None


@pytest.mark.asyncio
async def test_patch_home_address_reports_geocoder_errors(client, sentry_events):
    c, engine, geocoder = client
    geocoder.errors.add("error-please")

    r = await c.patch("/api/household", json={"home_address": "error-please"})

    # The save still succeeds; the failure is recorded as `error` (not a
    # permanent not_found), and reported because a raise here is a bug.
    assert r.status_code == 200
    [event] = sentry_events
    assert event["exception"]["values"][-1]["type"] == "RuntimeError"
    async with session_scope(engine) as s:
        row = (await s.execute(select(GeocodeAttempt))).scalar_one()
        assert row.result == "error"


@pytest.mark.asyncio
async def test_patch_home_address_geocoder_unavailable_is_retryable(client, sentry_events):
    """An outage during save must not permanently negative-cache the home address (#456)."""
    c, engine, geocoder = client
    geocoder.unavailable.add("123 main st, chicago, il")

    r = await c.patch("/api/household", json={"home_address": "123 Main St, Chicago, IL"})

    assert r.status_code == 200
    assert sentry_events == []
    async with session_scope(engine) as s:
        row = (await s.execute(select(GeocodeAttempt))).scalar_one()
        assert row.result == "unavailable"
        loc = (await s.execute(select(Location))).scalar_one()
        assert loc.lat is None  # the enricher picks it up after the retry window


async def _home(engine) -> Location:
    async with session_scope(engine) as s:
        hh = (await s.execute(select(HouseholdSettings))).scalar_one()
        return (
            await s.execute(select(Location).where(Location.id == hh.home_location_id))
        ).scalar_one()


@pytest.mark.asyncio
async def test_resaving_unchanged_address_keeps_coords_during_outage(client):
    """The settings form re-sends home_address on every save. An unrelated save must
    not wipe home coordinates, or an outage at that moment leaves the distance gate
    at distance_unknown (passing everything) until the enricher retries."""
    c, engine, geocoder = client
    await c.patch("/api/household", json={"home_address": "123 Main St, Chicago, IL"})
    assert geocoder.call_count == 1

    geocoder.unavailable.add("123 main st, chicago, il")
    r = await c.patch(
        "/api/household",
        json={"home_address": "123 Main St, Chicago, IL", "digest_time": "08:00"},
    )

    assert r.status_code == 200
    assert geocoder.call_count == 1  # not asked again
    loc = await _home(engine)
    assert (loc.lat, loc.lon) == (41.88, -87.63)


@pytest.mark.asyncio
async def test_resaving_reformatted_address_keeps_coords_and_new_text(client):
    c, engine, geocoder = client
    await c.patch("/api/household", json={"home_address": "123 Main St, Chicago, IL"})

    await c.patch(
        "/api/household",
        json={"home_address": "123 main st chicago il", "home_location_name": "House"},
    )

    assert geocoder.call_count == 1
    loc = await _home(engine)
    assert loc.lat == 41.88
    assert loc.address == "123 main st chicago il"
    assert loc.name == "House"


@pytest.mark.asyncio
async def test_changing_address_regeocodes(client):
    c, engine, geocoder = client
    geocoder.fixtures["1 elm st, evanston, il"] = GeocodeResult(
        lat=42.04, lon=-87.69, display_name="Evanston", provider="fake"
    )
    await c.patch("/api/household", json={"home_address": "123 Main St, Chicago, IL"})

    await c.patch("/api/household", json={"home_address": "1 Elm St, Evanston, IL"})

    assert geocoder.call_count == 2
    loc = await _home(engine)
    assert (loc.lat, loc.lon) == (42.04, -87.69)


@pytest.mark.asyncio
async def test_resaving_ungeocoded_address_tries_again(client):
    """An explicit save is a fine moment to retry an address that has no coordinates."""
    c, engine, geocoder = client
    geocoder.unavailable.add("123 main st, chicago, il")
    await c.patch("/api/household", json={"home_address": "123 Main St, Chicago, IL"})
    assert (await _home(engine)).lat is None

    geocoder.unavailable.clear()
    await c.patch("/api/household", json={"home_address": "123 Main St, Chicago, IL"})

    assert geocoder.call_count == 2
    assert (await _home(engine)).lat == 41.88
