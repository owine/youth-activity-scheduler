"""Render CalendarEventOut events as a VCALENDAR (RFC 5545) feed.

Hand-rolled rather than pulling in the `icalendar` dep — the format is
simple, the events are well-known shapes, and the output is verified by
tests against the actual byte-for-byte structure.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable

from yas.web.routes.kid_calendar_schemas import CalendarEventOut

# RFC 5545 mandates CRLF line endings. Some consumers tolerate LF, but
# Apple Calendar and Google Calendar both enforce CRLF on import paths.
_CRLF = "\r\n"

# Match events are LLM-suggested — too noisy to import into a personal
# calendar. Keep the export limited to commitments + structural blocks.
_EXPORT_KINDS = {"enrollment", "unavailability", "holiday"}


def _escape(text: str) -> str:
    """Escape per RFC 5545 §3.3.11 (TEXT property values)."""
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def _fmt_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def _fmt_datetime_utc(d: datetime) -> str:
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    else:
        d = d.astimezone(timezone.utc)
    return d.strftime("%Y%m%dT%H%M%SZ")


def _event_lines(ev: CalendarEventOut, *, dtstamp: str) -> list[str]:
    """Render one VEVENT block for the given calendar event."""
    lines = [
        "BEGIN:VEVENT",
        f"UID:yas-{ev.id}",
        f"DTSTAMP:{dtstamp}",
        f"SUMMARY:{_escape(ev.title)}",
    ]
    if ev.all_day:
        # All-day per RFC 5545 §3.6.1: DTSTART;VALUE=DATE; DTEND is the
        # day AFTER (exclusive end).
        from datetime import timedelta as _td

        next_day = ev.date + _td(days=1)
        lines.append(f"DTSTART;VALUE=DATE:{_fmt_date(ev.date)}")
        lines.append(f"DTEND;VALUE=DATE:{_fmt_date(next_day)}")
    else:
        # Timed event: combine the date with time fields. Times in our
        # data model are local naive; we publish them as-floating
        # (RFC 5545 "form 1") so subscribing apps render them in the
        # viewer's local zone, matching how the SPA already shows them.
        time_start = ev.time_start
        time_end = ev.time_end
        if time_start is None or time_end is None:
            # Defensive: treat as all-day if a timed event somehow
            # arrived without bounds.
            from datetime import timedelta as _td

            next_day = ev.date + _td(days=1)
            lines.append(f"DTSTART;VALUE=DATE:{_fmt_date(ev.date)}")
            lines.append(f"DTEND;VALUE=DATE:{_fmt_date(next_day)}")
        else:
            start_local = datetime.combine(ev.date, time_start)
            end_local = datetime.combine(ev.date, time_end)
            lines.append(f"DTSTART:{start_local.strftime('%Y%m%dT%H%M%S')}")
            lines.append(f"DTEND:{end_local.strftime('%Y%m%dT%H%M%S')}")
    lines.append("END:VEVENT")
    return lines


def render_calendar_ics(
    *,
    calendar_name: str,
    events: Iterable[CalendarEventOut],
    now: datetime | None = None,
) -> str:
    """Render a complete VCALENDAR document.

    - `calendar_name` becomes both NAME and X-WR-CALNAME for broad
      compatibility (RFC 7986 plus the older Apple/Google extension).
    - `events` is filtered: only enrollment, unavailability, and
      holiday kinds are exported. Match suggestions are intentionally
      excluded — they would clutter a personal calendar.
    - `now` is the DTSTAMP value. Defaults to `datetime.now(UTC)`.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    dtstamp = _fmt_datetime_utc(now)
    out: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Youth Activity Scheduler//yas//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"NAME:{_escape(calendar_name)}",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
    ]
    for ev in events:
        if ev.kind not in _EXPORT_KINDS:
            continue
        out.extend(_event_lines(ev, dtstamp=dtstamp))
    out.append("END:VCALENDAR")
    out.append("")  # trailing CRLF per RFC
    return _CRLF.join(out)
