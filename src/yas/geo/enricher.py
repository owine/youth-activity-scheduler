"""Geocode the locations table, in batches, and record negative cache rows.

Triggers matcher.rematch_offering for each offering at a location that just
gained coordinates.

Each address's latest outcome lives in geocode_attempts. `not_found` is a
definitive answer and is never retried; `unavailable` (the geocoder couldn't be
asked) and `error` (the geocoder raised — a bug) are retried once RETRY_AFTER
has elapsed since `last_tried`."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import sentry_sdk
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from yas.config import Settings
from yas.crawl.normalize import normalize_name
from yas.db.models import GeocodeAttempt, Location, Offering
from yas.db.session import session_scope
from yas.geo.client import Geocoder, GeocoderUnavailable
from yas.logging import get_logger

log = get_logger("yas.geo.enricher")

# Any Awaitable return type is acceptable — the enricher ignores the result.
RematchFn = Callable[[AsyncSession, int], Awaitable[Any]]

# How long a failed attempt blocks its address. `not_found` blocks it for good;
# `ok` never does, since the coordinates live on the location, not here. `error`
# waits a day so a geocoder bug reports at most once per address per day.
RETRY_AFTER: dict[str, timedelta] = {
    "unavailable": timedelta(hours=1),
    "error": timedelta(days=1),
}

_LOOKUP_CHUNK = 500


@dataclass(frozen=True)
class EnrichResult:
    updated: int
    not_found: int
    errored: int
    skipped: int
    unavailable: int = 0


def retry_due(prior: GeocodeAttempt | None, now: datetime) -> bool:
    """Whether an address with this latest attempt should be geocoded now."""
    if prior is None:
        return True
    if prior.result == "not_found":
        return False
    wait = RETRY_AFTER.get(prior.result)
    if wait is None:
        return True
    last = prior.last_tried
    if last.tzinfo is None:  # SQLite hands back naive datetimes
        last = last.replace(tzinfo=UTC)
    return now - last >= wait


def record_geocode_attempt(
    session: AsyncSession,
    prior: GeocodeAttempt | None,
    address_norm: str,
    result: str,
    *,
    now: datetime,
    detail: str | None = None,
) -> GeocodeAttempt:
    """Insert or update the address's attempt row; returns the row."""
    if prior is None:
        prior = GeocodeAttempt(address_norm=address_norm, last_tried=now, result=result)
        session.add(prior)
    prior.last_tried = now
    prior.result = result
    prior.detail = detail[:500] if detail else None
    return prior


async def enrich_ungeocoded_locations(
    session: AsyncSession,
    geocoder: Geocoder,
    *,
    batch_size: int = 20,
    on_rematch: RematchFn | None = None,
) -> EnrichResult:
    """Geocode up to `batch_size` eligible locations.

    The batch bounds geocoder calls, not rows scanned: negative-cached locations
    are skipped before they can use a slot, so they can't starve the ones
    behind them.
    """
    updated = 0
    not_found = 0
    errored = 0
    skipped = 0
    unavailable = 0
    now = datetime.now(UTC)

    locations = (
        (
            await session.execute(
                select(Location)
                .where(Location.lat.is_(None))
                .where(Location.address.isnot(None))
                .order_by(Location.id)
            )
        )
        .scalars()
        .all()
    )
    addr_norms = {loc.id: normalize_name(loc.address or "") for loc in locations}
    # Chunked: one bound variable per address, and SQLite caps a statement at 32766.
    attempts: dict[str, GeocodeAttempt] = {}
    unique_norms = sorted(set(addr_norms.values()))
    for i in range(0, len(unique_norms), _LOOKUP_CHUNK):
        chunk = unique_norms[i : i + _LOOKUP_CHUNK]
        for a in (
            await session.execute(
                select(GeocodeAttempt).where(GeocodeAttempt.address_norm.in_(chunk))
            )
        ).scalars():
            attempts[a.address_norm] = a

    calls = 0
    for loc in locations:
        addr_norm = addr_norms[loc.id]
        prior = attempts.get(addr_norm)
        if not retry_due(prior, now):
            skipped += 1
            continue
        if calls >= batch_size:
            break
        calls += 1
        try:
            result = await geocoder.geocode(loc.address or "")
        except GeocoderUnavailable as exc:
            # Expected (outage, rate limit): retry later, don't page. Stop the
            # batch rather than keep asking a service that just said it's down;
            # the untried locations keep no row and stay eligible next tick.
            log.warning("geocode.unavailable", location_id=loc.id, reason=str(exc))
            unavailable += 1
            attempts[addr_norm] = record_geocode_attempt(
                session, prior, addr_norm, "unavailable", now=now, detail=str(exc)
            )
            break
        except Exception as exc:
            # The client turns transport/HTTP/parse trouble into
            # GeocoderUnavailable, so anything else is a bug. Tagged by id, not
            # address, to keep addresses out of tag indexes.
            sentry_sdk.capture_exception(exc, tags={"location_id": str(loc.id)})
            errored += 1
            attempts[addr_norm] = record_geocode_attempt(
                session, prior, addr_norm, "error", now=now, detail=str(exc)
            )
            continue
        if result is None:
            not_found += 1
            attempts[addr_norm] = record_geocode_attempt(
                session, prior, addr_norm, "not_found", now=now
            )
            continue
        loc.lat = result.lat
        loc.lon = result.lon
        updated += 1
        attempts[addr_norm] = record_geocode_attempt(session, prior, addr_norm, "ok", now=now)
        if on_rematch is not None:
            offering_ids = (
                (await session.execute(select(Offering.id).where(Offering.location_id == loc.id)))
                .scalars()
                .all()
            )
            for oid in offering_ids:
                await on_rematch(session, oid)

    return EnrichResult(
        updated=updated,
        not_found=not_found,
        errored=errored,
        skipped=skipped,
        unavailable=unavailable,
    )


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
            if result.updated or result.not_found or result.errored or result.unavailable:
                log.info(
                    "geocode.tick",
                    updated=result.updated,
                    not_found=result.not_found,
                    errored=result.errored,
                    unavailable=result.unavailable,
                    skipped=result.skipped,
                )
            await asyncio.sleep(settings.geocode_tick_s)
    except asyncio.CancelledError:
        log.info("geocode.stop")
        raise
