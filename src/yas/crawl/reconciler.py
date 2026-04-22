"""Diff extracted offerings against the DB and classify each row."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.crawl.normalize import normalize_name
from yas.db.models import Location, Offering, Page
from yas.db.models._types import OfferingStatus
from yas.llm.schemas import ExtractedOffering

# Fields compared for deciding "updated" vs "unchanged".
_COMPARE_FIELDS = (
    "name", "description", "age_min", "age_max", "program_type",
    "start_date", "end_date", "days_of_week", "time_start", "time_end",
    "location_id", "price_cents", "registration_opens_at", "registration_url",
)


@dataclass(frozen=True)
class ReconcileResult:
    new: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)
    withdrawn: list[int] = field(default_factory=list)
    unchanged: list[int] = field(default_factory=list)


async def reconcile(
    session: AsyncSession,
    page: Page,
    extracted: list[ExtractedOffering],
) -> ReconcileResult:
    """Diff `extracted` against active offerings for `page`; mutate session accordingly.

    Does NOT commit. Caller controls the transaction."""
    existing_rows = (
        await session.execute(
            select(Offering).where(
                Offering.page_id == page.id,
                Offering.status == OfferingStatus.active,
            )
        )
    ).scalars().all()
    existing_by_key: dict[tuple[str, Any], Offering] = {
        (r.normalized_name, r.start_date): r for r in existing_rows
    }

    now = datetime.now(UTC)
    result = ReconcileResult()
    matched_keys: set[tuple[str, Any]] = set()

    for e in extracted:
        norm = normalize_name(e.name)
        key = (norm, e.start_date)
        matched_keys.add(key)
        location_id = await _location_id(session, page.site_id, e)
        desired = _offering_fields(e, norm, location_id)

        existing = existing_by_key.get(key)
        if existing is None:
            row = Offering(
                site_id=page.site_id,
                page_id=page.id,
                status=OfferingStatus.active,
                raw_json=_raw_json(e),
                first_seen=now,
                last_seen=now,
                **desired,
            )
            session.add(row)
            await session.flush()  # populate id
            result.new.append(row.id)
        else:
            # Compare the subset of fields we treat as user-visible.
            differs = any(
                getattr(existing, f) != desired[f] for f in _COMPARE_FIELDS
                if f in desired
            )
            existing.raw_json = _raw_json(e)
            existing.last_seen = now
            if differs:
                for f in _COMPARE_FIELDS:
                    if f in desired:
                        setattr(existing, f, desired[f])
                result.updated.append(existing.id)
            else:
                result.unchanged.append(existing.id)

    for key, row in existing_by_key.items():
        if key not in matched_keys:
            row.status = OfferingStatus.withdrawn
            row.last_seen = now
            result.withdrawn.append(row.id)

    return result


def _offering_fields(e: ExtractedOffering, norm: str, location_id: int | None) -> dict[str, Any]:
    return {
        "name": e.name,
        "normalized_name": norm,
        "description": e.description,
        "age_min": e.age_min,
        "age_max": e.age_max,
        "program_type": e.program_type,
        "start_date": e.start_date,
        "end_date": e.end_date,
        "days_of_week": [d.value for d in e.days_of_week],
        "time_start": e.time_start,
        "time_end": e.time_end,
        "location_id": location_id,
        "price_cents": e.price_cents,
        "registration_opens_at": e.registration_opens_at,
        "registration_url": e.registration_url,
    }


def _raw_json(e: ExtractedOffering) -> dict[str, Any]:
    import json
    result: dict[str, Any] = json.loads(e.model_dump_json())
    return result


async def _location_id(session: AsyncSession, site_id: int, e: ExtractedOffering) -> int | None:
    if not e.location_name:
        return None
    norm = normalize_name(e.location_name)
    existing = (
        await session.execute(
            select(Location).where(Location.name == e.location_name)
        )
    ).scalars().first()
    if existing is not None:
        return existing.id
    # Scope dedup loosely — same normalized name anywhere is "same" location.
    any_norm = (
        await session.execute(select(Location))
    ).scalars().all()
    for loc in any_norm:
        if normalize_name(loc.name) == norm:
            return loc.id
    loc = Location(name=e.location_name, address=e.location_address)
    session.add(loc)
    await session.flush()
    return loc.id
