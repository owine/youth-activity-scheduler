"""Geocoder protocol and Nominatim-backed client.

Respects Nominatim's usage policy: 1 req/s max, identifying User-Agent.
Rate-limit is internal (asyncio.Lock + monotonic timestamp). Failures
(transport, HTTP, parse) return None and are reported separately by
the enricher via geocode_attempts.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lon: float
    display_name: str
    provider: str  # "nominatim"


class Geocoder(Protocol):
    async def geocode(self, address: str) -> GeocodeResult | None: ...


class NominatimClient:
    BASE_URL = "https://nominatim.openstreetmap.org/search"
    USER_AGENT = "yas/0.1 (+https://github.com/example/youth-activity-scheduler)"
    _MAX_INTERVAL_S = 10.0

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        min_interval_s: float = 1.0,
    ) -> None:
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            headers={"User-Agent": self.USER_AGENT},
            timeout=httpx.Timeout(15.0),
        )
        self._min_interval_s = min_interval_s
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def geocode(self, address: str) -> GeocodeResult | None:
        await self._wait_turn()
        return await self._do_geocode(address, attempt=0)

    async def _wait_turn(self) -> None:
        async with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._min_interval_s:
                await asyncio.sleep(self._min_interval_s - elapsed)
            self._last_request_at = time.monotonic()

    async def _do_geocode(self, address: str, *, attempt: int) -> GeocodeResult | None:
        params: dict[str, Any] = {"q": address, "format": "json", "limit": 1}
        try:
            r = await self._http.get(self.BASE_URL, params=params)
        except httpx.TransportError:
            if attempt == 0:
                await asyncio.sleep(2.0)
                return await self._do_geocode(address, attempt=1)
            return None
        if r.status_code == 429:
            self._min_interval_s = min(self._min_interval_s * 2 or 1.0, self._MAX_INTERVAL_S)
            return None
        if r.status_code >= 400:
            return None
        try:
            data = r.json()
        except Exception:
            return None
        if not data:
            return None
        item = data[0]
        try:
            return GeocodeResult(
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                display_name=str(item.get("display_name", "")),
                provider="nominatim",
            )
        except (KeyError, TypeError, ValueError):
            return None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()
