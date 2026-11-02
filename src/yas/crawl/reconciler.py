"""Diff extracted offerings against the DB and classify each row."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
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
    "name",
    "description",
    "age_min",
    "age_max",
    "program_type",
    "start_date",
    "end_date",
    "days_of_week",
    "time_start",
    "time_end",
    "location_id",
    "price_cents",
    "registration_opens_at",
    "registration_url",
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
        (
            await session.execute(
                select(Offering).where(
                    Offering.page_id == page.id,
                    Offering.status == OfferingStatus.active,
                )
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    result = ReconcileResult()

    # Pair each extracted item with at most one existing row. A page can list
    # several offerings that share (normalized_name, start_date): a program run in
    # several weekly time slots. A dict on that pair alone collapsed them: every
    # slot overwrote one row and the others stayed active with stale schedules.
    pairs = _pair(existing_rows, extracted)

    claimed: set[int] = set()
    for e, existing in pairs:
        norm = normalize_name(e.name)
        location_id = await _location_id(session, page.site_id, e)
        desired = _offering_fields(e, norm, location_id)

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
            claimed.add(existing.id)
            # Compare the subset of fields we treat as user-visible.
            differs = any(
                getattr(existing, f) != desired[f] for f in _COMPARE_FIELDS if f in desired
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

    for row in existing_rows:
        if row.id not in claimed:
            row.status = OfferingStatus.withdrawn
            row.last_seen = now
            result.withdrawn.append(row.id)

    return result


def _slot_key(norm: str, start: Any, days: Any, time_start: Any) -> tuple[Any, ...]:
    return (norm, start, tuple(sorted(str(getattr(d, "value", d)) for d in days or [])), time_start)


def _pair(
    existing_rows: Sequence[Offering], extracted: list[ExtractedOffering]
) -> list[tuple[ExtractedOffering, Offering | None]]:
    """Match extracted items to existing rows one-to-one, in two passes.

    1. Same name, start date, days and start time: the same slot, unchanged or
       with other fields edited.
    2. What's left, on name and start date alone, in page order: a slot whose
       days or time moved stays an update of its row, so the row keeps its
       matches and enrollments instead of becoming a withdraw plus a new row.

    Anything still unpaired is new; existing rows nobody claimed are withdrawn.
    """
    rows = sorted(existing_rows, key=lambda r: r.id)
    taken: set[int] = set()
    paired: list[Offering | None] = [None] * len(extracted)

    by_slot: dict[tuple[Any, ...], list[Offering]] = defaultdict(list)
    for r in rows:
        by_slot[_slot_key(r.normalized_name, r.start_date, r.days_of_week, r.time_start)].append(r)
    for i, e in enumerate(extracted):
        key = _slot_key(normalize_name(e.name), e.start_date, e.days_of_week, e.time_start)
        candidates = [r for r in by_slot.get(key, []) if r.id not in taken]
        if candidates:
            paired[i] = candidates[0]
            taken.add(candidates[0].id)

    by_name: dict[tuple[str, Any], list[Offering]] = defaultdict(list)
    for r in rows:
        by_name[(r.normalized_name, r.start_date)].append(r)
    for i, e in enumerate(extracted):
        if paired[i] is not None:
            continue
        loose = [
            r for r in by_name.get((normalize_name(e.name), e.start_date), []) if r.id not in taken
        ]
        if loose:
            paired[i] = loose[0]
            taken.add(loose[0].id)

    return list(zip(extracted, paired, strict=True))


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
        (await session.execute(select(Location).where(Location.name == e.location_name)))
        .scalars()
        .first()
    )
    if existing is not None:
        return existing.id
    # Scope dedup loosely — same normalized name anywhere is "same" location.
    any_norm = (await session.execute(select(Location))).scalars().all()
    for loc in any_norm:
        if normalize_name(loc.name) == norm:
            return loc.id
    loc = Location(name=e.location_name, address=e.location_address)
    session.add(loc)
    await session.flush()
    return loc.id
