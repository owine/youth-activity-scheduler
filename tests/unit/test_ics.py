"""Unit tests for VCALENDAR rendering."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from yas.calendar.ics import render_calendar_ics
from yas.web.routes.kid_calendar_schemas import CalendarEventOut


def _ev(**overrides: object) -> CalendarEventOut:
    """Helper: produce a minimal CalendarEventOut with sensible defaults."""
    base = {
        "id": "enrollment:1:2026-05-13",
        "kind": "enrollment",
        "date": date(2026, 5, 13),
        "time_start": time(16, 0),
        "time_end": time(17, 0),
        "all_day": False,
        "title": "T-Ball",
    }
    base.update(overrides)
    return CalendarEventOut(**base)  # type: ignore[arg-type]


_NOW = datetime(2026, 5, 2, 20, 0, 0, tzinfo=UTC)


def test_renders_minimal_vcalendar_envelope():
    out = render_calendar_ics(calendar_name="Sam — YAS", events=[], now=_NOW)
    assert out.startswith("BEGIN:VCALENDAR\r\n")
    assert "VERSION:2.0\r\n" in out
    assert "PRODID:-//Youth Activity Scheduler//yas//EN\r\n" in out
    assert "NAME:Sam — YAS\r\n" in out
    assert "X-WR-CALNAME:Sam — YAS\r\n" in out
    assert out.endswith("END:VCALENDAR\r\n")


def test_timed_event_emits_floating_dtstart_dtend():
    out = render_calendar_ics(calendar_name="cal", events=[_ev()], now=_NOW)
    assert "BEGIN:VEVENT\r\n" in out
    assert "UID:yas-enrollment:1:2026-05-13\r\n" in out
    assert "DTSTART:20260513T160000\r\n" in out  # no Z — floating local time
    assert "DTEND:20260513T170000\r\n" in out
    assert "SUMMARY:T-Ball\r\n" in out


def test_all_day_event_uses_value_date_and_exclusive_end():
    ev = _ev(
        id="holiday:1:2026-04-29",
        kind="holiday",
        date=date(2026, 4, 29),
        time_start=None,
        time_end=None,
        all_day=True,
        title="Holiday",
    )
    out = render_calendar_ics(calendar_name="cal", events=[ev], now=_NOW)
    assert "DTSTART;VALUE=DATE:20260429\r\n" in out
    assert "DTEND;VALUE=DATE:20260430\r\n" in out  # exclusive end


def test_match_events_are_excluded():
    """Match suggestions clutter a personal calendar; export skips them."""
    timed = _ev()
    match_ev = _ev(id="match:5:2026-05-13", kind="match", title="Maybe Soccer")
    out = render_calendar_ics(calendar_name="cal", events=[timed, match_ev], now=_NOW)
    assert "T-Ball" in out
    assert "Maybe Soccer" not in out


def test_unavailability_and_holiday_events_are_included():
    school = _ev(
        id="unavailability:7:2026-05-13",
        kind="unavailability",
        all_day=False,
        time_start=time(8, 0),
        time_end=time(15, 0),
        title="School",
    )
    holiday = _ev(
        id="holiday:1:2026-04-29",
        kind="holiday",
        date=date(2026, 4, 29),
        time_start=None,
        time_end=None,
        all_day=True,
        title="Holiday",
    )
    out = render_calendar_ics(calendar_name="cal", events=[school, holiday], now=_NOW)
    assert "SUMMARY:School\r\n" in out
    assert "SUMMARY:Holiday\r\n" in out


def test_text_escape_handles_commas_semicolons_backslashes_newlines():
    ev = _ev(title="Sam, Smith; coach\\team\nNotes")
    out = render_calendar_ics(calendar_name="cal", events=[ev], now=_NOW)
    # Per RFC 5545 §3.3.11.
    assert "SUMMARY:Sam\\, Smith\\; coach\\\\team\\nNotes\r\n" in out


def test_dtstamp_is_utc_z_format():
    out = render_calendar_ics(calendar_name="cal", events=[_ev()], now=_NOW)
    assert "DTSTAMP:20260502T200000Z\r\n" in out


def test_calendar_name_with_special_chars_is_escaped():
    out = render_calendar_ics(
        calendar_name="Sam, the kid; cool", events=[], now=_NOW
    )
    assert "NAME:Sam\\, the kid\\; cool\r\n" in out


def test_empty_event_list_still_valid():
    out = render_calendar_ics(calendar_name="empty", events=[], now=_NOW)
    assert "BEGIN:VEVENT" not in out
    assert out.startswith("BEGIN:VCALENDAR")
    assert out.endswith("END:VCALENDAR\r\n")


def test_timed_event_missing_times_falls_back_to_all_day():
    """Defensive path: a 'timed' event without bounds becomes all-day."""
    ev = _ev(time_start=None, time_end=None, all_day=False)
    out = render_calendar_ics(calendar_name="cal", events=[ev], now=_NOW)
    assert "DTSTART;VALUE=DATE:" in out


@pytest.mark.parametrize(
    "kind,expect",
    [
        ("enrollment", True),
        ("unavailability", True),
        ("holiday", True),
        ("match", False),
    ],
)
def test_kind_filter_matrix(kind: str, expect: bool):
    ev = _ev(
        id=f"{kind}:1:2026-05-13",
        kind=kind,  # type: ignore[arg-type]
        all_day=(kind == "holiday"),
        time_start=None if kind == "holiday" else time(9, 0),
        time_end=None if kind == "holiday" else time(10, 0),
        title=f"X-{kind}",
    )
    out = render_calendar_ics(calendar_name="cal", events=[ev], now=_NOW)
    if expect:
        assert f"SUMMARY:X-{kind}\r\n" in out
    else:
        assert f"X-{kind}" not in out
