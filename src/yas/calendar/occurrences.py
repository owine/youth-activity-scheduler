"""Pure-function expansion of recurring weekly patterns into per-date occurrences.

No DB, no HTTP — call sites pass the row's pattern fields and a request window
and get back concrete occurrences within the intersection.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, time, timedelta

# Map weekday name → date.weekday() value (Mon=0..Sun=6).
_WEEKDAY: dict[str, int] = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


@dataclass(frozen=True, slots=True)
class Occurrence:
    """A concrete dated event derived from a recurring pattern."""

    date: date
    time_start: time | None
    time_end: time | None
    all_day: bool


def expand_recurring(
    *,
    days_of_week: list[str],
    time_start: time | None,
    time_end: time | None,
    date_start: date | None,
    date_end: date | None,
    range_from: date,
    range_to: date,
) -> Iterator[Occurrence]:
    """Yield occurrences for each weekday in `days_of_week` within the
    intersection of [range_from, range_to) (half-open) and
    [date_start, date_end] (closed, both endpoints inclusive when set).

    A row with both `time_start` and `time_end` set produces timed
    occurrences; both None produces all-day occurrences. A partial
    (one set, one None) is treated as malformed and yields nothing.
    """

    if (time_start is None) != (time_end is None):
        return
    all_day = time_start is None and time_end is None

    target_weekdays = {_WEEKDAY[name.lower()] for name in days_of_week if name.lower() in _WEEKDAY}
    if not target_weekdays:
        return

    lo = range_from
    if date_start is not None and date_start > lo:
        lo = date_start
    hi = range_to  # exclusive
    if date_end is not None:
        hi_from_source = date_end + timedelta(days=1)
        if hi_from_source < hi:
            hi = hi_from_source

    cursor = lo
    while cursor < hi:
        if cursor.weekday() in target_weekdays:
            yield Occurrence(
                date=cursor,
                time_start=time_start,
                time_end=time_end,
                all_day=all_day,
            )
        cursor += timedelta(days=1)
