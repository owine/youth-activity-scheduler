"""Unit tests for OSRM client + drive-time caching."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from yas.geo.drive_time import (
    PROVIDER_OSRM,
    DriveTimeResult,
    OsrmClient,
    compute_drive_time,
    get_cached_drive_time,
    store_drive_time,
)

# ---- OsrmClient ----------------------------------------------------------------


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


def _ok_response(*, duration_s: float, distance_m: float) -> dict[str, Any]:
    return {
        "code": "Ok",
        "routes": [{"duration": duration_s, "distance": distance_m}],
    }


@pytest.mark.asyncio
async def test_osrm_client_parses_ok_response():
    def handler(request: httpx.Request) -> httpx.Response:
        # Verify lon,lat order in the URL (OSRM expects it inverted) and
        # that 6-decimal formatting is used.
        assert "/route/v1/driving/-122.419400,37.774900;-118.243700,34.052200" in str(request.url)
        return httpx.Response(200, json=_ok_response(duration_s=21600.0, distance_m=600000.0))

    client = OsrmClient(http_client=httpx.AsyncClient(transport=_FakeTransport(handler)))
    result = await client.query(home=(37.7749, -122.4194), dest=(34.0522, -118.2437))
    assert result is not None
    assert result.drive_minutes == pytest.approx(360.0)  # 21600s = 360 min
    assert result.drive_meters == 600000.0
    assert result.provider == PROVIDER_OSRM


@pytest.mark.asyncio
async def test_osrm_client_returns_none_on_no_route():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "NoRoute"})

    client = OsrmClient(http_client=httpx.AsyncClient(transport=_FakeTransport(handler)))
    result = await client.query(home=(0.0, 0.0), dest=(1.0, 1.0))
    assert result is None


@pytest.mark.asyncio
async def test_osrm_client_returns_none_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "InvalidQuery"})

    client = OsrmClient(http_client=httpx.AsyncClient(transport=_FakeTransport(handler)))
    result = await client.query(home=(0.0, 0.0), dest=(1.0, 1.0))
    assert result is None


@pytest.mark.asyncio
async def test_osrm_client_returns_none_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = OsrmClient(http_client=httpx.AsyncClient(transport=_FakeTransport(handler)))
    result = await client.query(home=(0.0, 0.0), dest=(1.0, 1.0))
    assert result is None


@pytest.mark.asyncio
async def test_osrm_client_uses_custom_base_url():
    seen_url: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_url.append(str(request.url))
        return httpx.Response(200, json=_ok_response(duration_s=60.0, distance_m=1000.0))

    client = OsrmClient(
        base_url="http://my-osrm.local:5000/",
        http_client=httpx.AsyncClient(transport=_FakeTransport(handler)),
    )
    await client.query(home=(1.0, 2.0), dest=(3.0, 4.0))
    assert seen_url[0].startswith("http://my-osrm.local:5000/route/v1/driving/")


@pytest.mark.asyncio
async def test_osrm_client_returns_none_on_malformed_routes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "Ok", "routes": []})

    client = OsrmClient(http_client=httpx.AsyncClient(transport=_FakeTransport(handler)))
    assert await client.query(home=(0.0, 0.0), dest=(1.0, 1.0)) is None


# ---- cache layer ---------------------------------------------------------------


@pytest.fixture
async def session(tmp_path):
    from yas.db.base import Base
    from yas.db.session import create_engine_for, session_scope

    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/dt.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_cache_miss_returns_none(session):
    out = await get_cached_drive_time(session, (1.0, 2.0), (3.0, 4.0))
    assert out is None


@pytest.mark.asyncio
async def test_store_then_get_roundtrip(session):
    res = DriveTimeResult(drive_minutes=12.5, drive_meters=8000.0, provider=PROVIDER_OSRM)
    await store_drive_time(session, (1.0, 2.0), (3.0, 4.0), res)
    await session.flush()
    cached = await get_cached_drive_time(session, (1.0, 2.0), (3.0, 4.0))
    assert cached is not None
    assert cached.drive_minutes == 12.5
    assert cached.drive_meters == 8000.0
    assert cached.provider == PROVIDER_OSRM


@pytest.mark.asyncio
async def test_cache_rounds_coordinates_to_4_decimals(session):
    """Geocode jitter at the 5th decimal must hit the same cache row."""
    res = DriveTimeResult(drive_minutes=10.0, drive_meters=5000.0, provider=PROVIDER_OSRM)
    # Both stored and lookup coords rounded to 4 decimals should land on
    # (37.7749, -122.4194) and (34.0522, -118.2437) respectively.
    await store_drive_time(session, (37.7749, -122.4194), (34.0522, -118.2437), res)
    await session.flush()
    # 5th-decimal jitter that doesn't push past the rounding boundary.
    cached = await get_cached_drive_time(session, (37.77492, -122.41943), (34.05222, -118.24373))
    assert cached is not None
    assert cached.drive_minutes == 10.0


@pytest.mark.asyncio
async def test_store_overwrites_existing_row(session):
    a = DriveTimeResult(drive_minutes=10.0, drive_meters=5000.0, provider=PROVIDER_OSRM)
    b = DriveTimeResult(drive_minutes=15.0, drive_meters=7500.0, provider=PROVIDER_OSRM)
    await store_drive_time(session, (1.0, 2.0), (3.0, 4.0), a)
    await session.flush()
    await store_drive_time(session, (1.0, 2.0), (3.0, 4.0), b)
    await session.flush()
    cached = await get_cached_drive_time(session, (1.0, 2.0), (3.0, 4.0))
    assert cached is not None
    assert cached.drive_minutes == 15.0


# ---- compute_drive_time -------------------------------------------------------


class _StubProvider:
    def __init__(self, result: DriveTimeResult | None):
        self.result = result
        self.calls = 0

    async def query(self, home, dest):
        self.calls += 1
        return self.result


@pytest.mark.asyncio
async def test_compute_returns_cached_without_calling_provider(session):
    res = DriveTimeResult(drive_minutes=10.0, drive_meters=5000.0, provider=PROVIDER_OSRM)
    await store_drive_time(session, (1.0, 2.0), (3.0, 4.0), res)
    await session.flush()
    provider = _StubProvider(result=None)
    out = await compute_drive_time(session, provider, (1.0, 2.0), (3.0, 4.0))
    assert out is not None
    assert out.drive_minutes == 10.0
    assert provider.calls == 0  # cache hit; provider untouched


@pytest.mark.asyncio
async def test_compute_calls_provider_on_miss_and_caches(session):
    new_res = DriveTimeResult(drive_minutes=22.0, drive_meters=15000.0, provider=PROVIDER_OSRM)
    provider = _StubProvider(result=new_res)
    out = await compute_drive_time(session, provider, (1.0, 2.0), (3.0, 4.0))
    assert out is not None
    assert out.drive_minutes == 22.0
    assert provider.calls == 1
    # Second call should hit cache.
    await session.flush()
    out2 = await compute_drive_time(session, provider, (1.0, 2.0), (3.0, 4.0))
    assert out2 is not None
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_compute_returns_none_when_provider_fails(session):
    provider = _StubProvider(result=None)
    out = await compute_drive_time(session, provider, (1.0, 2.0), (3.0, 4.0))
    assert out is None
    # Nothing was cached either — failed lookups stay open for retry.
    cached = await get_cached_drive_time(session, (1.0, 2.0), (3.0, 4.0))
    assert cached is None
