"""Diff extracted offerings against the DB and classify each row."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.crawl.normalize import normalize_name
from yas.db.models import Location, Match, Offering, Page
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
    if result.withdrawn:
        # The daily sweep only visits active offerings, so nothing else would ever
        # remove these, and match readers don't filter on offering status.
        await session.execute(delete(Match).where(Match.offering_id.in_(result.withdrawn)))

    return result


def _days(days: Any) -> tuple[str, ...]:
    return tuple(sorted(str(getattr(d, "value", d)) for d in days or []))


def _value(v: Any) -> Any:
    return getattr(v, "value", v)


# Identity tiers, most specific first. Each tier only pairs what the tiers above it
# left, and pairing is one-to-one. Same-name offerings are common: one program in
# several weekly slots, or several age cohorts in the same slot. So every schedule
# tier is preceded by the same tier plus the age range: a cohort pairs with its own
# row by age before rows in its slot become interchangeable.
def _ages(o: Any) -> tuple[Any, ...]:
    return (o.age_min, o.age_max)


_SCHEDULE_TIERS: tuple[Callable[[Any], tuple[Any, ...]], ...] = (
    # The same slot.
    lambda o: (_days(o.days_of_week), o.time_start),
    # The slot's time moved.
    lambda o: (_days(o.days_of_week),),
    # The slot's days moved.
    lambda o: (o.time_start,),
    # Anything else under this name and start date.
    lambda o: (),
)

_TIERS: tuple[Callable[[Any], tuple[Any, ...]], ...] = (
    # The same cohort in the same slot, unchanged.
    lambda o: (
        _days(o.days_of_week),
        o.time_start,
        o.time_end,
        *_ages(o),
        _value(o.program_type),
        o.end_date,
    ),
    *(
        tier
        for schedule in _SCHEDULE_TIERS
        for tier in (
            (lambda o, schedule=schedule: (*schedule(o), *_ages(o))),
            schedule,
        )
    ),
)


def _schedule_order(o: Any) -> tuple[Any, ...]:
    t = o.time_start
    return (_days(o.days_of_week), t is None, t or time.min)


def _pair(
    existing_rows: Sequence[Offering], extracted: list[ExtractedOffering]
) -> list[tuple[ExtractedOffering, Offering | None]]:
    """Match extracted items to existing rows one-to-one, tier by tier.

    Every tier keys on (normalized name, start date) plus the tier's own fields,
    so a moved or edited slot stays an update of its row, keeping its matches and
    enrollments, instead of becoming a withdraw plus a new row. Within a tier,
    ties go to the lowest row id in page order. Unpaired items are new; rows
    nobody claimed are withdrawn.
    """
    rows = sorted(existing_rows, key=lambda r: r.id)
    names = [normalize_name(e.name) for e in extracted]
    taken: set[int] = set()
    paired: list[Offering | None] = [None] * len(extracted)

    for tier in _TIERS:
        pool: dict[tuple[Any, ...], list[Offering]] = defaultdict(list)
        for r in rows:
            if r.id not in taken:
                pool[(r.normalized_name, r.start_date, *tier(r))].append(r)
        waiting: dict[tuple[Any, ...], list[int]] = defaultdict(list)
        for i, e in enumerate(extracted):
            if paired[i] is None:
                waiting[(names[i], e.start_date, *tier(e))].append(i)
        for key, indices in waiting.items():
            candidates = pool.get(key)
            if not candidates:
                continue
            # Pair in schedule order on both sides, so slots that shift together
            # (9:00 -> 9:30 and 10:00 -> 10:30) keep their rows whatever order the
            # page lists them in. sorted() is stable, so ties keep page order
            # against row-id order.
            items = sorted(indices, key=lambda i: _schedule_order(extracted[i]))
            for i, row in zip(items, sorted(candidates, key=_schedule_order), strict=False):
                paired[i] = row
                taken.add(row.id)

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
