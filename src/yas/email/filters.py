"""Jinja2 filters for digest templates: price, rel_date, fmt."""

from __future__ import annotations

from datetime import UTC, date, datetime


def price(cents: int | None) -> str:
    """Format price_cents as a human-readable string.

    None or negative → ""
    0 → "Free"
    positive → "$X.XX"
    """
    if cents is None or cents < 0:
        return ""
    if cents == 0:
        return "Free"
    dollars = cents // 100
    remainder = cents % 100
    return f"${dollars}.{remainder:02d}"


def rel_date(d: date | datetime | None, *, today: date | None = None) -> str:
    """Format a date relative to today.

    Rules (in priority order):
    1. today -> "today"
    2. tomorrow -> "tomorrow"
    3. 2-6 days in future -> "in N days"
    4. 7-30 days in future -> "Sat, May 2"
    5. >30 days in future or any past date -> "May 2, 2026"
    """
    if d is None:
        return ""
    target: date = d.date() if isinstance(d, datetime) else d
    ref = today if today is not None else datetime.now(UTC).date()
    delta = (target - ref).days

    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if 2 <= delta <= 6:
        return f"in {delta} days"
    if 7 <= delta <= 30:
        # "Sat, May 2" — strip leading zero from day manually for portability
        weekday = target.strftime("%a")
        month = target.strftime("%b")
        return f"{weekday}, {month} {target.day}"
    # >30 days in future or any past date → absolute format
    month = target.strftime("%b")
    return f"{month} {target.day}, {target.year}"


def fmt(dt: datetime | None) -> str:
    """Format a datetime as "Tue 9:00 AM May 6" (12-hour, no leading zeros on hour/day).

    Portably constructed to avoid %-I platform differences.
    """
    if dt is None:
        return ""
    hour_12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    weekday = dt.strftime("%a")
    month = dt.strftime("%b")
    return f"{weekday} {hour_12}:{dt.minute:02d} {ampm} {month} {dt.day}"
