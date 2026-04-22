import asyncio

import httpx
import pytest
import respx

from yas.geo.client import GeocodeResult, NominatimClient

_OK_PAYLOAD = [
    {"lat": "41.8781", "lon": "-87.6298", "display_name": "Chicago, IL, USA"},
]


@pytest.mark.asyncio
@respx.mock
async def test_happy_path():
    respx.get(NominatimClient.BASE_URL).mock(return_value=httpx.Response(200, json=_OK_PAYLOAD))
    client = NominatimClient(min_interval_s=0.0)
    try:
        r = await client.geocode("Chicago, IL")
        assert isinstance(r, GeocodeResult)
        assert r.lat == pytest.approx(41.8781)
        assert r.lon == pytest.approx(-87.6298)
        assert r.provider == "nominatim"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_empty_result_returns_none():
    respx.get(NominatimClient.BASE_URL).mock(return_value=httpx.Response(200, json=[]))
    client = NominatimClient(min_interval_s=0.0)
    try:
        assert await client.geocode("Nowheresville, XX") is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_transport_error_retries_once_then_returns_none():
    route = respx.get(NominatimClient.BASE_URL).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.ConnectError("boom")],
    )
    client = NominatimClient(min_interval_s=0.0)
    try:
        result = await client.geocode("Chicago")
        assert result is None
        assert route.call_count == 2    # one retry
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_429_doubles_interval():
    respx.get(NominatimClient.BASE_URL).mock(return_value=httpx.Response(429))
    client = NominatimClient(min_interval_s=0.1)
    try:
        assert await client.geocode("anywhere") is None
        # session interval doubled (0.1 → 0.2), capped at 10s
        assert client._min_interval_s >= 0.2
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit_serializes_concurrent_calls():
    respx.get(NominatimClient.BASE_URL).mock(return_value=httpx.Response(200, json=_OK_PAYLOAD))
    client = NominatimClient(min_interval_s=0.2)
    try:
        start = asyncio.get_event_loop().time()
        await asyncio.gather(client.geocode("a"), client.geocode("b"), client.geocode("c"))
        elapsed = asyncio.get_event_loop().time() - start
        # Three calls x 0.2s interval -> at least 0.4s wall clock (first free, two spaced)
        assert elapsed >= 0.35
    finally:
        await client.aclose()
