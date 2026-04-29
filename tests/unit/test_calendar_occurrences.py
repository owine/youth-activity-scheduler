"""Pure-function tests for the calendar recurring-expansion helper."""

from __future__ import annotations

from datetime import date, time

from yas.calendar.occurrences import Occurrence, expand_recurring


def _occ(
    d: tuple[int, int, int], start: tuple[int, int] | None, end: tuple[int, int] | None
) -> Occurrence:
    return Occurrence(
        date=date(*d),
        time_start=time(*start) if start else None,
        time_end=time(*end) if end else None,
        all_day=start is None and end is None,
    )


def test_weekly_recurring_within_range_returns_correct_dates():
    out = list(
        expand_recurring(
            days_of_week=["mon", "wed", "fri"],
            time_start=time(16, 0),
            time_end=time(17, 0),
            date_start=None,
            date_end=None,
            range_from=date(2026, 4, 27),
            range_to=date(2026, 5, 4),
        )
    )
    assert out == [
        _occ((2026, 4, 27), (16, 0), (17, 0)),
        _occ((2026, 4, 29), (16, 0), (17, 0)),
        _occ((2026, 5, 1), (16, 0), (17, 0)),
    ]


def test_date_start_clips_lower_bound():
    out = list(
        expand_recurring(
            days_of_week=["tue"],
            time_start=time(10, 0),
            time_end=time(11, 0),
            date_start=date(2026, 4, 28),
            date_end=None,
            range_from=date(2026, 4, 21),
            range_to=date(2026, 5, 5),
        )
    )
    assert [o.date for o in out] == [date(2026, 4, 28)]


def test_date_end_clips_upper_bound_inclusive():
    out = list(
        expand_recurring(
            days_of_week=["tue"],
            time_start=time(10, 0),
            time_end=time(11, 0),
            date_start=None,
            date_end=date(2026, 4, 28),
            range_from=date(2026, 4, 21),
            range_to=date(2026, 5, 12),
        )
    )
    assert [o.date for o in out] == [date(2026, 4, 21), date(2026, 4, 28)]


def test_range_to_is_exclusive():
    out = list(
        expand_recurring(
            days_of_week=["mon"],
            time_start=time(9, 0),
            time_end=time(10, 0),
            date_start=None,
            date_end=None,
            range_from=date(2026, 4, 27),
            range_to=date(2026, 4, 27),
        )
    )
    assert out == []


def test_all_day_when_both_times_none():
    out = list(
        expand_recurring(
            days_of_week=["sat"],
            time_start=None,
            time_end=None,
            date_start=None,
            date_end=None,
            range_from=date(2026, 4, 25),
            range_to=date(2026, 4, 26),
        )
    )
    assert len(out) == 1
    assert out[0].all_day is True
    assert out[0].time_start is None
    assert out[0].time_end is None


def test_empty_days_of_week_returns_no_occurrences():
    out = list(
        expand_recurring(
            days_of_week=[],
            time_start=time(9, 0),
            time_end=time(10, 0),
            date_start=None,
            date_end=None,
            range_from=date(2026, 4, 27),
            range_to=date(2026, 5, 4),
        )
    )
    assert out == []


def test_days_of_week_case_insensitive():
    out = list(
        expand_recurring(
            days_of_week=["MON", "Wed"],
            time_start=time(9, 0),
            time_end=time(10, 0),
            date_start=None,
            date_end=None,
            range_from=date(2026, 4, 27),
            range_to=date(2026, 5, 4),
        )
    )
    assert [o.date for o in out] == [date(2026, 4, 27), date(2026, 4, 29)]


def test_source_outside_request_window_returns_no_occurrences():
    out = list(
        expand_recurring(
            days_of_week=["mon"],
            time_start=time(9, 0),
            time_end=time(10, 0),
            date_start=date(2026, 1, 1),
            date_end=date(2026, 1, 31),
            range_from=date(2026, 4, 27),
            range_to=date(2026, 5, 4),
        )
    )
    assert out == []


def test_malformed_partial_time_skipped():
    """time_start without time_end (or vice versa) is malformed; helper skips."""
    out = list(
        expand_recurring(
            days_of_week=["mon"],
            time_start=time(9, 0),
            time_end=None,
            date_start=None,
            date_end=None,
            range_from=date(2026, 4, 27),
            range_to=date(2026, 5, 4),
        )
    )
    assert out == []
