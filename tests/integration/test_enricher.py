from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select

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
    geocoder = FakeGeocoder(
        fixtures={
            "2045 n lincoln park w, chicago, il": GeocodeResult(
                lat=41.9214,
                lon=-87.6351,
                display_name="Lincoln Park",
                provider="fake",
            )
        }
    )
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
    assert r2.skipped == 1  # skipped due to prior not_found
    async with session_scope(engine) as s:
        rows = (await s.execute(select(GeocodeAttempt))).scalars().all()
        assert len(rows) == 1
        assert rows[0].result == "not_found"
    assert geocoder.call_count == 1  # second call skipped
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


@pytest.mark.asyncio
async def test_enricher_reports_geocoder_errors(tmp_path, sentry_events):
    """The client already absorbs transport/HTTP/JSON trouble, so a raise here is a bug.

    The address is stored as `error` and only retried daily, so without a report
    the location silently goes without coordinates.
    """
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=7, name="Bad", address="error-please"))
    geocoder = FakeGeocoder(errors={"error-please"})
    async with session_scope(engine) as s:
        await enrich_ungeocoded_locations(s, geocoder, batch_size=10)

    [event] = sentry_events
    assert event["exception"]["values"][-1]["type"] == "RuntimeError"
    assert event["tags"]["location_id"] == "7"
    await engine.dispose()


async def _age_attempt(engine, address_norm: str, age: timedelta) -> None:
    async with session_scope(engine) as s:
        row = (
            await s.execute(
                select(GeocodeAttempt).where(GeocodeAttempt.address_norm == address_norm)
            )
        ).scalar_one()
        row.last_tried = datetime.now(UTC) - age


_CHICAGO = GeocodeResult(lat=41.88, lon=-87.63, display_name="Chicago", provider="fake")


@pytest.mark.asyncio
async def test_enricher_records_unavailable_without_reporting(tmp_path, sentry_events):
    """An outage is expected, not a bug: record it for retry and don't page (#456)."""
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="X", address="123 Main St"))
    geocoder = FakeGeocoder(unavailable={"123 main st"})
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert r.unavailable == 1
    assert r.not_found == 0
    async with session_scope(engine) as s:
        row = (await s.execute(select(GeocodeAttempt))).scalar_one()
        assert row.result == "unavailable"
        assert "503" in (row.detail or "")
    assert sentry_events == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_enricher_stops_batch_when_geocoder_unavailable(tmp_path):
    """Don't keep hammering a service that just said it's down."""
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="A", address="aaa"))
        s.add(Location(id=2, name="B", address="bbb"))
    geocoder = FakeGeocoder(unavailable={"aaa", "bbb"})
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert geocoder.call_count == 1
    assert r.unavailable == 1
    async with session_scope(engine) as s:
        rows = (await s.execute(select(GeocodeAttempt))).scalars().all()
        # The untried address has no row, so it stays eligible on the next tick.
        assert [row.address_norm for row in rows] == ["aaa"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_enricher_retries_unavailable_after_backoff(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="X", address="123 Main St"))
    geocoder = FakeGeocoder(unavailable={"123 main st"})
    async with session_scope(engine) as s:
        await enrich_ungeocoded_locations(s, geocoder, batch_size=10)

    # Service recovers, but the retry window hasn't elapsed yet.
    geocoder.unavailable.clear()
    geocoder.fixtures["123 main st"] = _CHICAGO
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert r.skipped == 1
    assert geocoder.call_count == 1

    await _age_attempt(engine, "123 main st", timedelta(hours=2))
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert r.updated == 1
    async with session_scope(engine) as s:
        loc = (await s.execute(select(Location))).scalar_one()
        assert loc.lat == pytest.approx(41.88)
        row = (await s.execute(select(GeocodeAttempt))).scalar_one()
        assert row.result == "ok"
        assert row.detail is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_enricher_retries_error_after_a_day(tmp_path):
    """A geocoder bug stops blocking the address once it's fixed; retry is daily, so
    GlitchTip sees at most one event per address per day."""
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="X", address="error-please"))
    geocoder = FakeGeocoder(errors={"error-please"})
    async with session_scope(engine) as s:
        await enrich_ungeocoded_locations(s, geocoder, batch_size=10)

    await _age_attempt(engine, "error please", timedelta(hours=2))
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert r.skipped == 1

    await _age_attempt(engine, "error please", timedelta(days=1, minutes=1))
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    # Still broken: re-recorded on the existing row rather than a duplicate insert.
    assert r.errored == 1
    assert geocoder.call_count == 2
    async with session_scope(engine) as s:
        row = (await s.execute(select(GeocodeAttempt))).scalar_one()
        assert row.result == "error"
    await engine.dispose()


@pytest.mark.asyncio
async def test_enricher_not_found_does_not_starve_batch(tmp_path):
    """Negative-cached locations must not occupy batch slots, or once `batch_size` of
    them pile up nothing behind them is ever geocoded."""
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="Miss", address="Nowheresville, XX"))
        s.add(Location(id=2, name="Hit", address="123 Main St"))
        s.add(
            GeocodeAttempt(
                address_norm="nowheresville xx", last_tried=datetime.now(UTC), result="not_found"
            )
        )
    geocoder = FakeGeocoder(fixtures={"123 main st": _CHICAGO})
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=1)
    assert r.updated == 1
    assert r.skipped == 1
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("script", "counter"),
    [("misses", "not_found"), ("errors", "errored")],
)
async def test_enricher_handles_shared_address_in_one_batch(tmp_path, script, counter):
    """Two locations normalizing to one address share one GeocodeAttempt row, and
    the second is skipped rather than geocoded (or inserted) again."""
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="A", address="Nowheresville, XX"))
        s.add(Location(id=2, name="B", address="nowheresville xx"))
    geocoder = FakeGeocoder()
    getattr(geocoder, script).update({"nowheresville, xx", "nowheresville xx"})
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert getattr(r, counter) == 1
    assert r.skipped == 1
    assert geocoder.call_count == 1
    async with session_scope(engine) as s:
        assert len((await s.execute(select(GeocodeAttempt))).scalars().all()) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_enricher_batch_bounds_geocoder_calls(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        for i in range(1, 6):
            s.add(Location(id=i, name=f"L{i}", address=f"{i} Main St"))
    geocoder = FakeGeocoder(fixtures={f"{i} main st": _CHICAGO for i in range(1, 6)})
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=2)
    assert r.updated == 2
    assert geocoder.call_count == 2
    async with session_scope(engine) as s:
        rows = (await s.execute(select(GeocodeAttempt))).scalars().all()
        assert sorted(row.address_norm for row in rows) == ["1 main st", "2 main st"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_enricher_keeps_earlier_results_when_outage_stops_batch(tmp_path):
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="A", address="aaa"))
        s.add(Location(id=2, name="B", address="bbb"))
    geocoder = FakeGeocoder(fixtures={"aaa": _CHICAGO}, unavailable={"bbb"})
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert (r.updated, r.unavailable) == (1, 1)
    async with session_scope(engine) as s:
        loc = (await s.execute(select(Location).where(Location.id == 1))).scalar_one()
        assert loc.lat == pytest.approx(41.88)
        results = {
            a.address_norm: a.result for a in (await s.execute(select(GeocodeAttempt))).scalars()
        }
        assert results == {"aaa": "ok", "bbb": "unavailable"}
    await engine.dispose()


@pytest.mark.asyncio
async def test_enricher_survives_more_addresses_than_sqlite_variables(tmp_path):
    """Locations load without a LIMIT, so the attempt lookup must not bind one
    variable per address in a single statement (SQLite caps it at 32766)."""
    engine = await _setup(tmp_path)
    n = 33_000
    async with session_scope(engine) as s:
        await s.execute(
            insert(Location),
            [{"id": i, "name": f"L{i}", "address": f"{i} nowhere"} for i in range(1, n + 1)],
        )
        await s.execute(
            insert(GeocodeAttempt),
            [
                {
                    "address_norm": f"{i} nowhere",
                    "last_tried": datetime.now(UTC),
                    "result": "not_found",
                }
                for i in range(1, n)
            ],
        )
    geocoder = FakeGeocoder(fixtures={f"{n} nowhere": _CHICAGO})
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert (r.updated, r.skipped) == (1, n - 1)
    await engine.dispose()


@pytest.mark.asyncio
async def test_enricher_geocodes_location_whose_address_was_ok_before(tmp_path):
    """An `ok` row caches no coordinates, so a new location at an already-geocoded
    address still has to be geocoded."""
    engine = await _setup(tmp_path)
    async with session_scope(engine) as s:
        s.add(Location(id=1, name="New", address="123 Main St"))
        s.add(GeocodeAttempt(address_norm="123 main st", last_tried=datetime.now(UTC), result="ok"))
    geocoder = FakeGeocoder(fixtures={"123 main st": _CHICAGO})
    async with session_scope(engine) as s:
        r = await enrich_ungeocoded_locations(s, geocoder, batch_size=10)
    assert r.updated == 1
    await engine.dispose()
