"""Pure sync hard-gate functions.

Each returns a GateResult namedtuple. No I/O. No DB access. Every input is
already-loaded ORM rows or primitives. This keeps the matcher's hot path fast
and the gates trivially unit-testable."""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any, NamedTuple

from yas.crawl.normalize import normalize_name
from yas.db.models._types import OfferingStatus


class GateResult(NamedTuple):
    passed: bool
    code: str
    detail: str


def _age_on(dob: date, reference: date) -> int:
    """Whole years between dob and reference."""
    years = reference.year - dob.year
    if (reference.month, reference.day) < (dob.month, dob.day):
        years -= 1
    return max(years, 0)


def age_fits(kid: Any, offering: Any, *, today: date) -> GateResult:
    # Age reference: offering.start_date lets a kid who turns N before a future
    # program starts qualify for N-year-old programs. For past start_dates
    # (e.g. sites that list historical sessions) we clamp to today so a 6yo
    # today isn't evaluated as the 4yo they were when a 2024 program started.
    reference = offering.start_date or today
    if reference < today:
        reference = today
    age = _age_on(kid.dob, reference)
    if offering.age_min is None and offering.age_max is None:
        return GateResult(True, "age_unspecified", "offering has no age range")
    if offering.age_min is not None and age < offering.age_min:
        return GateResult(
            False, "too_young", f"age {age} on {reference.isoformat()} < min {offering.age_min}"
        )
    if offering.age_max is not None and age > offering.age_max:
        return GateResult(
            False, "too_old", f"age {age} on {reference.isoformat()} > max {offering.age_max}"
        )
    return GateResult(
        True,
        "age_ok",
        f"age {age} on {reference.isoformat()} fits [{offering.age_min}, {offering.age_max}]",
    )


def distance_fits(
    kid: Any,
    offering: Any,
    *,
    distance_mi: float | None,
    household_default: float | None,
) -> GateResult:
    cap = kid.max_distance_mi if kid.max_distance_mi is not None else household_default
    if cap is None:
        return GateResult(True, "distance_unlimited", "no distance cap configured")
    if offering.location_id is None or distance_mi is None:
        return GateResult(True, "distance_unknown", "location not geocoded")
    if distance_mi <= cap:
        return GateResult(True, "distance_ok", f"{distance_mi:.1f}mi of {cap:.1f}mi max")
    return GateResult(False, "too_far", f"{distance_mi:.1f}mi > {cap:.1f}mi max")


def interests_overlap(kid: Any, offering: Any, aliases: dict[str, list[str]]) -> GateResult:
    if not kid.interests:
        return GateResult(False, "no_kid_interests", "kid has no interests configured")
    needle_hay = normalize_name(f"{offering.name or ''} {offering.description or ''}")
    program_type_val = getattr(offering.program_type, "value", offering.program_type)
    for interest in kid.interests:
        interest = interest.lower()
        if program_type_val == interest:
            return GateResult(
                True, "interest_program_type_match", f"kid interest '{interest}' == program_type"
            )
        terms = aliases.get(interest, [interest])
        for term in terms:
            if normalize_name(term) in needle_hay:
                return GateResult(
                    True,
                    "interest_text_match",
                    f"kid interest '{interest}' matched via '{term}' in name/description",
                )
    return GateResult(
        False, "no_interest_match", f"no kid interest ({', '.join(kid.interests)}) matched offering"
    )


def offering_active_and_not_ended(offering: Any, *, today: date) -> GateResult:
    status = getattr(offering.status, "value", offering.status)
    if status != OfferingStatus.active.value:
        return GateResult(False, "not_active", f"offering status = {status}")
    if offering.end_date is not None and offering.end_date < today:
        return GateResult(False, "ended", f"offering ended {offering.end_date.isoformat()}")
    return GateResult(True, "active", "offering is active and not ended")


_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _weekday_name(d: date) -> str:
    return _DAY_NAMES[d.weekday()]


def _offering_has_full_schedule(offering: Any) -> bool:
    return (
        offering.start_date is not None
        and offering.end_date is not None
        and offering.days_of_week
        and offering.time_start is not None
        and offering.time_end is not None
    )


def _time_overlaps(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    return a_start < b_end and b_start < a_end


def no_conflict_with_unavailability(
    offering: Any,
    blocks: list[Any],
    school_holidays: set[date],
    *,
    today: date,
) -> GateResult:
    if not _offering_has_full_schedule(offering):
        return GateResult(
            True, "schedule_partial", "offering schedule incomplete; cannot verify no-conflict"
        )

    offering_days = {d.lower() for d in (getattr(d, "value", d) for d in offering.days_of_week)}
    active_blocks = [b for b in blocks if b.active]
    if not active_blocks:
        return GateResult(True, "no_blocks", "no active unavailability blocks")

    # Iterate each date in the offering's date range.
    cur = offering.start_date
    end = offering.end_date
    while cur <= end:
        weekday = _weekday_name(cur)
        if weekday in offering_days:
            for block in active_blocks:
                source = getattr(block.source, "value", block.source)
                if source == "school" and cur in school_holidays:
                    continue
                if block.date_start is not None and cur < block.date_start:
                    continue
                if block.date_end is not None and cur > block.date_end:
                    continue
                block_days = {
                    d.lower() for d in (getattr(d, "value", d) for d in (block.days_of_week or []))
                }
                if block_days and weekday not in block_days:
                    continue
                if block.time_start is None or block.time_end is None:
                    # Whole-day block on this date → conflict.
                    return GateResult(
                        False, "conflict", f"all-day block on {cur.isoformat()} ({source})"
                    )
                if _time_overlaps(
                    offering.time_start, offering.time_end, block.time_start, block.time_end
                ):
                    return GateResult(
                        False, "conflict", f"conflict on {cur.isoformat()} ({source})"
                    )
        cur += timedelta(days=1)
    return GateResult(True, "no_conflict", f"no overlap with {len(active_blocks)} active block(s)")
