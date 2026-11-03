from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.fakes.geocoder import FakeGeocoder
from yas.db.base import Base
from yas.db.models import (
    Alert,
    GeocodeAttempt,
    HouseholdSettings,
    Kid,
    Location,
    Match,
    Offering,
    Page,
    Site,
)
from yas.db.models._types import AlertType, OfferingStatus, ProgramType
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


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["quiet_hours_start", "quiet_hours_end", "digest_time"])
@pytest.mark.parametrize("value", ["24:00", "25:99", "12:60", "7:00", "07:00:00", "noon", ""])
async def test_patch_rejects_invalid_hhmm(client, field, value):
    """Stored quiet hours are parsed by the delivery loop on every tick; '24:00'
    used to be accepted here and then crash it."""
    c, _, _ = client
    r = await c.patch("/api/household", json={field: value})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_accepts_valid_quiet_hours_and_clearing(client):
    c, _, _ = client
    r = await c.patch(
        "/api/household", json={"quiet_hours_start": "00:00", "quiet_hours_end": "23:59"}
    )
    assert r.status_code == 200
    assert r.json()["quiet_hours_start"] == "00:00"
    assert r.json()["quiet_hours_end"] == "23:59"
    r = await c.patch("/api/household", json={"quiet_hours_start": None, "quiet_hours_end": None})
    assert r.status_code == 200
    assert r.json()["quiet_hours_start"] is None
    assert r.json()["quiet_hours_end"] is None


# --- Channel secrets survive a re-save (the form omits a blank secret) ---


async def _hh(engine) -> HouseholdSettings:
    async with session_scope(engine) as s:
        return (await s.execute(select(HouseholdSettings))).scalar_one()


_SMTP = {
    "transport": "smtp",
    "host": "smtp.example.com",
    "port": 587,
    "use_tls": True,
    "from_addr": "yas@example.com",
    "to_addrs": ["me@example.com"],
}


@pytest.mark.asyncio
async def test_resaving_channel_without_secret_keeps_stored_secret(client):
    """The settings form leaves a saved secret blank ("saved value — type to
    replace") and omits it on save; that must not wipe the stored secret."""
    c, engine, _ = client
    await c.patch(
        "/api/household",
        json={
            "smtp_config_json": {**_SMTP, "password_value": "kept"},
            "ntfy_config_json": {
                "base_url": "https://ntfy.sh",
                "topic": "t",
                "auth_token_value": "tk",
            },
            "pushover_config_json": {"user_key_value": "uk", "app_token_value": "at"},
        },
    )

    r = await c.patch(
        "/api/household",
        json={
            "smtp_config_json": {**_SMTP, "to_addrs": ["you@example.com"]},
            "ntfy_config_json": {"base_url": "https://ntfy.sh", "topic": "t2"},
            "pushover_config_json": {"devices": ["phone"]},
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["credential_status"]["smtp_password"]["via"] == "form"
    assert "password_value" not in body["smtp_config_json"]  # still redacted
    hh = await _hh(engine)
    assert hh.smtp_config_json == {
        **_SMTP,
        "to_addrs": ["you@example.com"],
        "password_value": "kept",
    }
    assert hh.ntfy_config_json == {
        "base_url": "https://ntfy.sh",
        "topic": "t2",
        "auth_token_value": "tk",
    }
    assert hh.pushover_config_json == {
        "devices": ["phone"],
        "user_key_value": "uk",
        "app_token_value": "at",
    }


@pytest.mark.asyncio
async def test_resaving_channel_with_new_secret_replaces_it(client):
    c, engine, _ = client
    await c.patch("/api/household", json={"smtp_config_json": {**_SMTP, "password_value": "old"}})

    await c.patch("/api/household", json={"smtp_config_json": {**_SMTP, "password_value": "new"}})

    assert (await _hh(engine)).smtp_config_json["password_value"] == "new"


@pytest.mark.asyncio
@pytest.mark.parametrize("cleared", [None, ""])
async def test_explicitly_blank_secret_clears_it(client, cleared):
    c, engine, _ = client
    await c.patch("/api/household", json={"pushover_config_json": {"user_key_value": "uk"}})

    await c.patch("/api/household", json={"pushover_config_json": {"user_key_value": cleared}})

    assert (await _hh(engine)).pushover_config_json == {}


@pytest.mark.asyncio
async def test_switching_email_transport_drops_the_other_transports_secret(client):
    c, engine, _ = client
    await c.patch("/api/household", json={"smtp_config_json": {**_SMTP, "password_value": "pw"}})

    fe = {"transport": "forwardemail", "from_addr": "yas@example.com", "to_addrs": ["me@x.com"]}
    await c.patch("/api/household", json={"smtp_config_json": fe})

    assert (await _hh(engine)).smtp_config_json == fe


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "valid"), [("digest_time", "06:30"), ("daily_llm_cost_cap_usd", 2.5)]
)
async def test_patch_rejects_null_for_not_null_fields(client, field, valid):
    """These columns are NOT NULL; an explicit null used to reach them and 500."""
    c, _, _ = client
    r = await c.patch("/api/household", json={field: None})
    assert r.status_code == 422
    r = await c.patch("/api/household", json={field: valid})
    assert r.status_code == 200
    assert r.json()[field] == valid


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [{"host": "smtp.other.com"}, {"username": "other"}],
    ids=["host", "username"],
)
async def test_resaving_smtp_for_another_server_drops_stored_password(client, change):
    """The saved password belongs to that server and account; sending it to
    another host (or as another user) would leak it."""
    c, engine, _ = client
    smtp = {**_SMTP, "username": "me"}
    await c.patch("/api/household", json={"smtp_config_json": {**smtp, "password_value": "pw"}})

    r = await c.patch("/api/household", json={"smtp_config_json": {**smtp, **change}})

    assert r.json()["credential_status"]["smtp_password"]["via"] is None
    assert (await _hh(engine)).smtp_config_json == {**smtp, **change}


@pytest.mark.asyncio
async def test_resaving_ntfy_for_another_server_drops_stored_token(client):
    c, engine, _ = client
    ntfy = {"base_url": "https://ntfy.internal", "topic": "t"}
    await c.patch("/api/household", json={"ntfy_config_json": {**ntfy, "auth_token_value": "tk"}})

    moved = {**ntfy, "base_url": "https://ntfy.sh"}
    await c.patch("/api/household", json={"ntfy_config_json": moved})

    assert (await _hh(engine)).ntfy_config_json == moved


@pytest.mark.asyncio
async def test_resaving_ntfy_with_trailing_slash_keeps_stored_token(client):
    """NtfyChannel strips a trailing slash, so it's the same server."""
    c, engine, _ = client
    ntfy = {"base_url": "https://ntfy.internal", "topic": "t"}
    await c.patch("/api/household", json={"ntfy_config_json": {**ntfy, "auth_token_value": "tk"}})

    await c.patch(
        "/api/household",
        json={"ntfy_config_json": {**ntfy, "base_url": "https://ntfy.internal/"}},
    )

    assert (await _hh(engine)).ntfy_config_json["auth_token_value"] == "tk"


@pytest.mark.asyncio
async def test_resaving_ntfy_for_another_server_with_new_token_keeps_it(client):
    c, engine, _ = client
    ntfy = {"base_url": "https://ntfy.internal", "topic": "t", "auth_token_value": "old"}
    await c.patch("/api/household", json={"ntfy_config_json": ntfy})

    moved = {**ntfy, "base_url": "https://ntfy.sh", "auth_token_value": "new"}
    await c.patch("/api/household", json={"ntfy_config_json": moved})

    assert (await _hh(engine)).ntfy_config_json == moved


@pytest.mark.asyncio
async def test_nulling_a_channel_still_removes_it(client):
    c, engine, _ = client
    await c.patch("/api/household", json={"smtp_config_json": {**_SMTP, "password_value": "pw"}})

    await c.patch("/api/household", json={"smtp_config_json": None})

    assert (await _hh(engine)).smtp_config_json is None


# --- Clearing the home address ---


@pytest.mark.asyncio
@pytest.mark.parametrize("cleared", [None, "", "   "])
async def test_explicit_null_home_address_clears_it(client, cleared):
    c, engine, _ = client
    await c.patch("/api/household", json={"home_address": "123 Main St, Chicago, IL"})

    r = await c.patch("/api/household", json={"home_address": cleared})

    assert r.status_code == 200
    body = r.json()
    assert body["home_address"] is None
    assert body["home_location_id"] is None
    assert body["home_lat"] is None
    assert (await _hh(engine)).home_location_id is None
    async with session_scope(engine) as s:
        # No offering points at it, so the orphaned row goes too.
        assert (await s.execute(select(Location))).scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cleared", [None, ""])
async def test_clearing_home_address_with_a_home_location_id_is_422(client, cleared):
    """Clearing deletes the home Location, so setting home_location_id in the
    same patch would point at the deleted row (an FK violation, 500)."""
    c, engine, _ = client
    first = await c.patch("/api/household", json={"home_address": "123 Main St, Chicago, IL"})
    loc_id = first.json()["home_location_id"]

    r = await c.patch("/api/household", json={"home_address": cleared, "home_location_id": loc_id})

    assert r.status_code == 422
    assert (await _hh(engine)).home_location_id == loc_id  # nothing changed


@pytest.mark.asyncio
async def test_clearing_home_address_with_null_home_location_id_clears_it(client):
    c, engine, _ = client
    await c.patch("/api/household", json={"home_address": "123 Main St, Chicago, IL"})

    r = await c.patch("/api/household", json={"home_address": None, "home_location_id": None})

    assert r.status_code == 200
    assert (await _hh(engine)).home_location_id is None


@pytest.mark.asyncio
async def test_omitted_home_address_is_unchanged(client):
    c, _, _ = client
    await c.patch("/api/household", json={"home_address": "123 Main St, Chicago, IL"})

    r = await c.patch("/api/household", json={"digest_time": "08:00"})

    assert r.json()["home_address"] == "123 Main St, Chicago, IL"


# --- Distance inputs changing rematches every active kid ---


async def _seed_far_offering(engine) -> None:
    """A soccer offering ~11 mi from the Chicago fixture, and a kid who wants soccer."""
    today = date.today()
    async with session_scope(engine) as s:
        s.add(Site(id=1, name="X", base_url="https://x"))
        s.add(Location(id=50, name="Evanston Field", address="1 Elm St", lat=42.04, lon=-87.69))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        s.add(
            Offering(
                id=1,
                site_id=1,
                page_id=1,
                name="Soccer",
                normalized_name="soccer",
                program_type=ProgramType.soccer.value,
                location_id=50,
                start_date=today + timedelta(days=10),
                end_date=today + timedelta(days=60),
                status=OfferingStatus.active.value,
            )
        )
        s.add(Kid(id=1, name="Sam", dob=today - timedelta(days=7 * 365), interests=["soccer"]))


async def _match_ids(engine) -> list[tuple[int, int]]:
    async with session_scope(engine) as s:
        return [(m.kid_id, m.offering_id) for m in (await s.execute(select(Match))).scalars()]


@pytest.mark.asyncio
async def test_household_distance_changes_rematch_active_kids(client):
    c, engine, _ = client
    await _seed_far_offering(engine)
    await c.patch("/api/household", json={"default_max_distance_mi": 5.0})

    # A home ~11 mi away rematches; the far offering fails the distance gate.
    await c.patch("/api/household", json={"home_address": "123 Main St, Chicago, IL"})
    assert await _match_ids(engine) == []

    # Widening the radius brings it in without waiting for the daily sweep.
    await c.patch("/api/household", json={"default_max_distance_mi": 20.0})
    assert await _match_ids(engine) == [(1, 1)]

    # Narrowing it drops the match again.
    await c.patch("/api/household", json={"default_max_distance_mi": 5.0})
    assert await _match_ids(engine) == []


async def _new_match_alerts(engine) -> list[Alert]:
    async with session_scope(engine) as s:
        return list(
            (await s.execute(select(Alert).where(Alert.type == AlertType.new_match.value)))
            .scalars()
            .all()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["miss", "unavailable", "cleared"])
async def test_home_becoming_unknown_does_not_rematch(client, outcome):
    """Without home coords the distance gate passes everything as
    distance_unknown, so rematching would match and alert on offerings far
    outside the radius. Existing matches are left for the daily sweep."""
    c, engine, geocoder = client
    await _seed_far_offering(engine)
    await c.patch(
        "/api/household",
        json={"home_address": "123 Main St, Chicago, IL", "default_max_distance_mi": 5.0},
    )
    assert await _match_ids(engine) == []

    if outcome == "cleared":
        patch: dict[str, object] = {"home_address": None}
    else:
        getattr(geocoder, "misses" if outcome == "miss" else "unavailable").add("1 nowhere rd")
        patch = {"home_address": "1 Nowhere Rd"}
    r = await c.patch("/api/household", json=patch)

    assert r.status_code == 200
    assert r.json()["home_lat"] is None
    assert await _new_match_alerts(engine) == []
    assert await _match_ids(engine) == []
