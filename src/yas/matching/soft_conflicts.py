"""Detect soft (tight) conflicts between an offering and unavailability blocks.

A soft conflict is a near-miss the hard gate would have allowed but a
human would still want to know about: e.g., school ends at 3:00pm and
T-Ball starts at 3:15pm — technically no overlap, but realistically the
kid can't get from school to the field on time.

Returns short human-readable warning strings. Empty list when nothing
is tight enough to flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

DEFAULT_BUFFER_MINUTES = 15


@dataclass(frozen=True)
class SoftConflict:
    label: str
    gap_min: int

    def to_dict(self) -> dict[str, object]:
        return {"label": self.label, "gap_min": self.gap_min}


_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _weekday_name(d: date) -> str:
    return _DAY_NAMES[d.weekday()]


def _to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _fmt_time(t: time) -> str:
    """Format like '3:15pm' (no leading zero on hour)."""
    h = t.hour % 12 or 12
    suffix = "am" if t.hour < 12 else "pm"
    if t.minute == 0:
        return f"{h}{suffix}"
    return f"{h}:{t.minute:02d}{suffix}"


def _gap_minutes(
    offering_start: time,
    offering_end: time,
    block_start: time,
    block_end: time,
) -> int | None:
    """Return the smallest minute gap if the two intervals don't overlap.

    None if they overlap (the hard gate handles that). Positive int
    otherwise — the smaller of (offering_start - block_end) and
    (block_start - offering_end).
    """
    o_s, o_e = _to_minutes(offering_start), _to_minutes(offering_end)
    b_s, b_e = _to_minutes(block_start), _to_minutes(block_end)
    if o_s < b_e and b_s < o_e:
        return None  # overlap
    # Two non-overlap cases: offering before block, or offering after block.
    if o_e <= b_s:
        return b_s - o_e
    return o_s - b_e


def find_soft_conflicts(
    offering: Any,
    blocks: list[Any],
    school_holidays: set[date],
    *,
    today: date,
    buffer_minutes: int = DEFAULT_BUFFER_MINUTES,
) -> list[SoftConflict]:
    """Return SoftConflict warnings for tight (non-overlap, < buffer) gaps.

    Mirrors the iteration shape of `no_conflict_with_unavailability` —
    same date range, same weekday filter, same school-holiday handling.
    Skips offerings or blocks without complete schedules; nothing to
    measure against if either side has missing time bounds.
    """
    if (
        offering.start_date is None
        or offering.end_date is None
        or not offering.days_of_week
        or offering.time_start is None
        or offering.time_end is None
    ):
        return []

    offering_days = {d.lower() for d in (getattr(d, "value", d) for d in offering.days_of_week)}
    active_blocks = [b for b in blocks if b.active]
    if not active_blocks:
        return []

    # Dedupe: emit one warning per (block_id, side) combo across the
    # date range, since the same school-end-vs-tball-start tightness
    # repeats every Tuesday for the whole season.
    seen: set[tuple[Any, str]] = set()
    out: list[SoftConflict] = []

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
                    continue  # all-day block; hard gate would have caught this

                gap = _gap_minutes(
                    offering.time_start, offering.time_end, block.time_start, block.time_end
                )
                if gap is None:
                    continue  # overlap → hard gate's problem
                if gap >= buffer_minutes:
                    continue
                # Decide which side: is offering AFTER the block (block-end → offering-start),
                # or BEFORE the block (offering-end → block-start)?
                if _to_minutes(offering.time_start) >= _to_minutes(block.time_end):
                    side = "after"
                    label = (
                        f"{(block.label or source).strip().capitalize()} ends "
                        f"{_fmt_time(block.time_end)}; "
                        f"{offering.name} starts {_fmt_time(offering.time_start)} "
                        f"({gap} min gap)"
                    )
                else:
                    side = "before"
                    label = (
                        f"{offering.name} ends {_fmt_time(offering.time_end)}; "
                        f"{(block.label or source).strip().capitalize()} starts "
                        f"{_fmt_time(block.time_start)} ({gap} min gap)"
                    )
                key = (block.id, side)
                if key in seen:
                    continue
                seen.add(key)
                out.append(SoftConflict(label=label, gap_min=gap))
        cur += timedelta(days=1)

    return out
