"""Unit tests for soft-conflict detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

import pytest

from yas.matching.soft_conflicts import (
    DEFAULT_BUFFER_MINUTES,
    SoftConflict,
    find_soft_conflicts,
)


@dataclass
class _Offering:
    name: str
    days_of_week: list[str]
    time_start: time | None
    time_end: time | None
    start_date: date | None
    end_date: date | None


@dataclass
class _Block:
    id: int
    source: str
    label: str | None
    days_of_week: list[str]
    time_start: time | None
    time_end: time | None
    date_start: date | None
    date_end: date | None
    active: bool = True


_TODAY = date(2026, 5, 4)  # Monday
_SEASON_START = date(2026, 5, 5)  # Tuesday
_SEASON_END = date(2026, 6, 30)


def _school_block() -> _Block:
    return _Block(
        id=1,
        source="school",
        label="School",
        days_of_week=["mon", "tue", "wed", "thu", "fri"],
        time_start=time(8, 0),
        time_end=time(15, 0),
        date_start=date(2026, 4, 1),
        date_end=date(2026, 6, 30),
    )


def _offering(*, time_start: time, time_end: time, days: list[str] | None = None) -> _Offering:
    return _Offering(
        name="T-Ball",
        days_of_week=days or ["tue", "thu"],
        time_start=time_start,
        time_end=time_end,
        start_date=_SEASON_START,
        end_date=_SEASON_END,
    )


def test_15_min_gap_is_NOT_flagged_default_buffer_is_strict_less_than():
    """At exactly the buffer threshold, no warning. Buffer is < not <=."""
    offering = _offering(time_start=time(15, 15), time_end=time(16, 15))
    out = find_soft_conflicts(offering, [_school_block()], set(), today=_TODAY)
    assert out == []


def test_14_min_gap_is_flagged():
    offering = _offering(time_start=time(15, 14), time_end=time(16, 14))
    out = find_soft_conflicts(offering, [_school_block()], set(), today=_TODAY)
    assert len(out) == 1
    assert "14 min gap" in out[0].label


def test_overlap_returns_no_soft_conflict_hard_gate_problem():
    """Hard gate handles overlap; soft-conflict only flags non-overlapping near-misses."""
    offering = _offering(time_start=time(14, 30), time_end=time(15, 30))
    out = find_soft_conflicts(offering, [_school_block()], set(), today=_TODAY)
    assert out == []


def test_wide_gap_returns_no_soft_conflict():
    offering = _offering(time_start=time(16, 0), time_end=time(17, 0))  # 60 min after school
    out = find_soft_conflicts(offering, [_school_block()], set(), today=_TODAY)
    assert out == []


def test_offering_BEFORE_block_emits_warning_when_tight():
    """Morning offering ending right before school starts."""
    offering = _offering(
        time_start=time(7, 0), time_end=time(7, 50), days=["mon"]
    )  # ends 7:50, school 8:00 → 10 min
    out = find_soft_conflicts(offering, [_school_block()], set(), today=_TODAY)
    assert len(out) == 1
    assert "T-Ball ends 7:50am" in out[0].label
    assert "School starts 8am" in out[0].label
    assert "10 min gap" in out[0].label


def test_school_holiday_skips_school_block_check():
    """A holiday on the offering date means there's no school to be tight against."""
    school_only_tuesday = _Block(
        id=1,
        source="school",
        label="School",
        days_of_week=["tue"],
        time_start=time(8, 0),
        time_end=time(15, 0),
        date_start=date(2026, 5, 5),
        date_end=date(2026, 5, 5),  # only the one Tuesday
    )
    offering = _offering(
        time_start=time(15, 5), time_end=time(16, 0), days=["tue"]
    )  # would be 5 min gap
    holiday = {date(2026, 5, 5)}
    out = find_soft_conflicts(offering, [school_only_tuesday], holiday, today=_TODAY)
    assert out == []


def test_inactive_block_ignored():
    inactive = _school_block()
    inactive.active = False
    offering = _offering(time_start=time(15, 5), time_end=time(16, 0))
    out = find_soft_conflicts(offering, [inactive], set(), today=_TODAY)
    assert out == []


def test_dedupe_across_date_range_one_warning_per_block_side():
    """Tight every Tuesday for the season → one warning, not 8 of them."""
    offering = _offering(time_start=time(15, 5), time_end=time(16, 0))
    out = find_soft_conflicts(offering, [_school_block()], set(), today=_TODAY)
    assert len(out) == 1


def test_offering_with_partial_schedule_returns_empty():
    offering = _offering(time_start=time(15, 5), time_end=time(16, 0))
    offering.time_start = None
    out = find_soft_conflicts(offering, [_school_block()], set(), today=_TODAY)
    assert out == []


def test_block_without_time_bounds_skipped():
    """All-day blocks are the hard gate's concern, not soft-conflict's."""
    all_day = _Block(
        id=1,
        source="manual",
        label="Vacation",
        days_of_week=[],
        time_start=None,
        time_end=None,
        date_start=date(2026, 5, 5),
        date_end=date(2026, 5, 5),
    )
    offering = _offering(time_start=time(9, 0), time_end=time(10, 0), days=["tue"])
    out = find_soft_conflicts(offering, [all_day], set(), today=_TODAY)
    assert out == []


def test_block_outside_date_range_ignored():
    out_of_range = _school_block()
    out_of_range.date_start = date(2027, 1, 1)
    out_of_range.date_end = date(2027, 6, 30)
    offering = _offering(time_start=time(15, 5), time_end=time(16, 0))
    out = find_soft_conflicts(offering, [out_of_range], set(), today=_TODAY)
    assert out == []


def test_no_blocks_returns_empty():
    offering = _offering(time_start=time(15, 5), time_end=time(16, 0))
    out = find_soft_conflicts(offering, [], set(), today=_TODAY)
    assert out == []


def test_to_dict_returns_label_and_gap_min():
    sc = SoftConflict(label="hi", gap_min=5)
    assert sc.to_dict() == {"label": "hi", "gap_min": 5}


def test_default_buffer_is_15_minutes():
    assert DEFAULT_BUFFER_MINUTES == 15


def test_custom_buffer_threshold():
    """Tighter buffer means more things qualify; looser means fewer."""
    offering = _offering(time_start=time(15, 20), time_end=time(16, 0))  # 20 min gap
    # Default 15-min buffer: not tight enough.
    assert find_soft_conflicts(offering, [_school_block()], set(), today=_TODAY) == []
    # Looser 30-min buffer: now flagged.
    out = find_soft_conflicts(offering, [_school_block()], set(), today=_TODAY, buffer_minutes=30)
    assert len(out) == 1
    assert "20 min gap" in out[0].label


@pytest.mark.parametrize(
    "t,expected",
    [
        (time(15, 0), "3pm"),
        (time(15, 15), "3:15pm"),
        (time(8, 0), "8am"),
        (time(7, 50), "7:50am"),
        (time(0, 0), "12am"),
        (time(12, 0), "12pm"),
        (time(12, 30), "12:30pm"),
    ],
)
def test_time_formatter(t: time, expected: str):
    """Indirect test of _fmt_time via the label output."""
    from yas.matching.soft_conflicts import _fmt_time

    assert _fmt_time(t) == expected
