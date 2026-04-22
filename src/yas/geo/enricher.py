"""Geocode the locations table, in batches, and record negative cache rows.

Triggers matcher.rematch_offering for each offering at a location that just
gained coordinates."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from yas.config import Settings
from yas.crawl.normalize import normalize_name
from yas.db.models import GeocodeAttempt, Location, Offering
from yas.db.session import session_scope
from yas.geo.client import Geocoder
from yas.logging import get_logger

log = get_logger("yas.geo.enricher")

# Any Awaitable return type is acceptable — the enricher ignores the result.
RematchFn = Callable[[AsyncSession, int], Awaitable[Any]]


@dataclass(frozen=True)
class EnrichResult:
    updated: int
    not_found: int
    errored: int
    skipped: int


async def enrich_ungeocoded_locations(
    session: AsyncSession,
    geocoder: Geocoder,
    *,
    batch_size: int = 20,
    on_rematch: RematchFn | None = None,
) -> EnrichResult:
    updated = 0
    not_found = 0
    errored = 0
    skipped = 0

    locations = (
        (
            await session.execute(
                select(Location)
                .where(Location.lat.is_(None))
                .where(Location.address.isnot(None))
                .limit(batch_size)
            )
        )
        .scalars()
        .all()
    )

    for loc in locations:
        addr_norm = normalize_name(loc.address or "")
        prior = (
            await session.execute(
                select(GeocodeAttempt).where(GeocodeAttempt.address_norm == addr_norm)
            )
        ).scalar_one_or_none()
        if prior is not None and prior.result in {"not_found", "error"}:
            skipped += 1
            continue
        try:
            result = await geocoder.geocode(loc.address or "")
        except Exception as exc:
            errored += 1
            session.add(
                GeocodeAttempt(
                    address_norm=addr_norm,
                    last_tried=datetime.now(UTC),
                    result="error",
                    detail=str(exc)[:500],
                )
            )
            continue
        if result is None:
            not_found += 1
            if prior is None:
                session.add(
                    GeocodeAttempt(
                        address_norm=addr_norm,
                        last_tried=datetime.now(UTC),
                        result="not_found",
                    )
                )
            else:
                prior.last_tried = datetime.now(UTC)
                prior.result = "not_found"
            continue
        loc.lat = result.lat
        loc.lon = result.lon
        updated += 1
        if prior is None:
            session.add(
                GeocodeAttempt(
                    address_norm=addr_norm,
                    last_tried=datetime.now(UTC),
                    result="ok",
                )
            )
        else:
            prior.last_tried = datetime.now(UTC)
            prior.result = "ok"
        if on_rematch is not None:
            offering_ids = (
                (await session.execute(select(Offering.id).where(Offering.location_id == loc.id)))
                .scalars()
                .all()
            )
            for oid in offering_ids:
                await on_rematch(session, oid)

    return EnrichResult(updated=updated, not_found=not_found, errored=errored, skipped=skipped)


async def geocode_enricher_loop(
    engine: AsyncEngine,
    settings: Settings,
    geocoder: Geocoder,
) -> None:
    from yas.matching.matcher import rematch_offering

    log.info(
        "geocode.start", tick_s=settings.geocode_tick_s, batch_size=settings.geocode_batch_size
    )
    try:
        while True:
            async with session_scope(engine) as s:
                result = await enrich_ungeocoded_locations(
                    s,
                    geocoder,
                    batch_size=settings.geocode_batch_size,
                    on_rematch=rematch_offering,
                )
            if result.updated or result.not_found or result.errored:
                log.info(
                    "geocode.tick",
                    updated=result.updated,
                    not_found=result.not_found,
                    errored=result.errored,
                    skipped=result.skipped,
                )
            await asyncio.sleep(settings.geocode_tick_s)
    except asyncio.CancelledError:
        log.info("geocode.stop")
        raise
