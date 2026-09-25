from datetime import date

from yas.db.models import Kid
from yas.matching.matcher import _school_holidays


def test_unparseable_holiday_strings_are_skipped():
    kid = Kid(school_holidays=["2026-12-25", "not-a-date", "", date(2026, 12, 31)])
    assert _school_holidays(kid) == {date(2026, 12, 25), date(2026, 12, 31)}
