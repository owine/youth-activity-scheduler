"""Tests for digest Jinja filters: price, rel_date, fmt."""

from __future__ import annotations

from datetime import UTC, date, datetime

from yas.alerts.digest.filters import fmt, price, rel_date

# ---------------------------------------------------------------------------
# price filter
# ---------------------------------------------------------------------------


def test_price_none_returns_empty():
    assert price(None) == ""


def test_price_zero_returns_free():
    assert price(0) == "Free"


def test_price_normal_formatting():
    assert price(12345) == "$123.45"


def test_price_single_digit_cents():
    assert price(101) == "$1.01"


def test_price_negative_returns_empty():
    assert price(-1) == ""
    assert price(-500) == ""


# ---------------------------------------------------------------------------
# rel_date filter
# ---------------------------------------------------------------------------

_TODAY = date(2026, 5, 1)  # Friday


def test_rel_date_none_returns_empty():
    assert rel_date(None, today=_TODAY) == ""


def test_rel_date_today():
    assert rel_date(_TODAY, today=_TODAY) == "today"


def test_rel_date_tomorrow():
    assert rel_date(date(2026, 5, 2), today=_TODAY) == "tomorrow"


def test_rel_date_within_week():
    # 3 days out
    assert rel_date(date(2026, 5, 4), today=_TODAY) == "in 3 days"
    # 6 days out (boundary)
    assert rel_date(date(2026, 5, 7), today=_TODAY) == "in 6 days"


def test_rel_date_within_month():
    # 7 days out → weekday abbreviation format
    result = rel_date(date(2026, 5, 8), today=_TODAY)
    assert result == "Fri, May 8"
    # 30 days out (boundary)
    result30 = rel_date(date(2026, 5, 31), today=_TODAY)
    assert result30 == "Sun, May 31"


def test_rel_date_beyond_month():
    # 31+ days out → absolute date format
    result = rel_date(date(2026, 6, 2), today=_TODAY)
    assert result == "Jun 2, 2026"


def test_rel_date_past():
    # Any past date → absolute format
    result = rel_date(date(2026, 4, 1), today=_TODAY)
    assert result == "Apr 1, 2026"


def test_rel_date_accepts_datetime():
    dt = datetime(2026, 5, 4, 9, 0, 0, tzinfo=UTC)
    assert rel_date(dt, today=_TODAY) == "in 3 days"


# ---------------------------------------------------------------------------
# fmt filter
# ---------------------------------------------------------------------------

_DT = datetime(2026, 5, 6, 9, 0, 0, tzinfo=UTC)  # Wednesday 09:00 UTC


def test_fmt_none_returns_empty():
    assert fmt(None) == ""


def test_fmt_produces_expected_format():
    # Wed 9:00 AM May 6
    result = fmt(_DT)
    assert result == "Wed 9:00 AM May 6"


def test_fmt_midnight_as_12_am():
    dt = datetime(2026, 5, 6, 0, 30, 0, tzinfo=UTC)
    result = fmt(dt)
    assert result == "Wed 12:30 AM May 6"


def test_fmt_noon_as_12_pm():
    dt = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    result = fmt(dt)
    assert result == "Wed 12:00 PM May 6"


def test_fmt_pm_time():
    dt = datetime(2026, 5, 6, 15, 45, 0, tzinfo=UTC)
    result = fmt(dt)
    assert result == "Wed 3:45 PM May 6"
