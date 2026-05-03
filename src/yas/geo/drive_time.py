"""Routed driving distance/duration via OSRM, with DB-backed caching.

Every (home, dest) pair becomes a row in `drive_time_cache` once
computed. Coordinates are rounded to 4 decimals (~11 m) before lookup
and write so geocode jitter doesn't fragment the cache.

OSRM is the default provider — open-source, no API key. Public
endpoint at router.project-osrm.org works for low-volume use; for
higher volume, point YAS_OSRM_BASE_URL at a self-hosted instance.

Failures (transport, HTTP, parse) return None. Callers decide whether
to fall back to great-circle distance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import DriveTimeCache

_COORD_PRECISION = 4
PROVIDER_OSRM = "osrm"


def _round(c: float) -> float:
    return round(c, _COORD_PRECISION)


@dataclass(frozen=True)
class DriveTimeResult:
    drive_minutes: float
    drive_meters: float
    provider: str


class DriveTimeProvider(Protocol):
    async def query(
        self,
        home: tuple[float, float],
        dest: tuple[float, float],
    ) -> DriveTimeResult | None: ...


class OsrmClient:
    """OSRM /route/v1/driving fetcher.

    The public endpoint at https://router.project-osrm.org has rate
    limits but is fine for a single household's lifetime usage. For
    higher volume, set YAS_OSRM_BASE_URL to a self-hosted instance.
    """

    DEFAULT_BASE_URL = "https://router.project-osrm.org"

    def __init__(
        self,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(15.0))

    async def query(
        self,
        home: tuple[float, float],
        dest: tuple[float, float],
    ) -> DriveTimeResult | None:
        # OSRM expects lon,lat (NOT lat,lon). Pre-coordinate-pair order is critical.
        url = (
            f"{self._base_url}/route/v1/driving/"
            f"{home[1]:.6f},{home[0]:.6f};{dest[1]:.6f},{dest[0]:.6f}"
            "?overview=false&alternatives=false"
        )
        try:
            r = await self._http.get(url)
        except httpx.TransportError:
            return None
        if r.status_code >= 400:
            return None
        try:
            data: dict[str, Any] = r.json()
        except ValueError:
            return None
        if data.get("code") != "Ok":
            return None
        routes = data.get("routes") or []
        if not routes:
            return None
        first = routes[0]
        try:
            duration_s = float(first["duration"])
            distance_m = float(first["distance"])
        except KeyError, TypeError, ValueError:
            return None
        return DriveTimeResult(
            drive_minutes=duration_s / 60.0,
            drive_meters=distance_m,
            provider=PROVIDER_OSRM,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()


async def get_cached_drive_time(
    session: AsyncSession,
    home: tuple[float, float],
    dest: tuple[float, float],
) -> DriveTimeResult | None:
    """Return a cached drive time if present, else None. Coordinates rounded."""
    h_lat, h_lon = _round(home[0]), _round(home[1])
    d_lat, d_lon = _round(dest[0]), _round(dest[1])
    row = (
        await session.execute(
            select(DriveTimeCache).where(
                DriveTimeCache.home_lat == h_lat,
                DriveTimeCache.home_lon == h_lon,
                DriveTimeCache.dest_lat == d_lat,
                DriveTimeCache.dest_lon == d_lon,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return DriveTimeResult(
        drive_minutes=row.drive_minutes,
        drive_meters=row.drive_meters,
        provider=row.provider,
    )


async def store_drive_time(
    session: AsyncSession,
    home: tuple[float, float],
    dest: tuple[float, float],
    result: DriveTimeResult,
) -> None:
    """Upsert a cache row. Caller is responsible for commit/flush."""
    h_lat, h_lon = _round(home[0]), _round(home[1])
    d_lat, d_lon = _round(dest[0]), _round(dest[1])
    existing = (
        await session.execute(
            select(DriveTimeCache).where(
                DriveTimeCache.home_lat == h_lat,
                DriveTimeCache.home_lon == h_lon,
                DriveTimeCache.dest_lat == d_lat,
                DriveTimeCache.dest_lon == d_lon,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if existing is not None:
        existing.drive_minutes = result.drive_minutes
        existing.drive_meters = result.drive_meters
        existing.provider = result.provider
        existing.computed_at = now
        return
    session.add(
        DriveTimeCache(
            home_lat=h_lat,
            home_lon=h_lon,
            dest_lat=d_lat,
            dest_lon=d_lon,
            drive_minutes=result.drive_minutes,
            drive_meters=result.drive_meters,
            provider=result.provider,
            computed_at=now,
        )
    )


async def compute_drive_time(
    session: AsyncSession,
    provider: DriveTimeProvider,
    home: tuple[float, float],
    dest: tuple[float, float],
) -> DriveTimeResult | None:
    """Cache-first lookup. On miss, query the provider and persist.

    Returns None if the provider call fails — callers fall back to
    great-circle distance.
    """
    cached = await get_cached_drive_time(session, home, dest)
    if cached is not None:
        return cached
    result = await provider.query(home, dest)
    if result is None:
        return None
    await store_drive_time(session, home, dest, result)
    return result
