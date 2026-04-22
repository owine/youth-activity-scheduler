from dataclasses import dataclass
from datetime import date, time

from yas.db.models._types import OfferingStatus, ProgramType, UnavailabilitySource
from yas.matching.gates import (
    age_fits,
    distance_fits,
    interests_overlap,
    no_conflict_with_unavailability,
    offering_active_and_not_ended,
)


# Lightweight ORM-shaped stand-ins so the gates stay testable without a DB.
@dataclass
class _Kid:
    id: int = 1
    dob: date = date(2019, 5, 1)
    interests: list[str] = None
    max_distance_mi: float | None = None
    school_holidays: list[str] = None

    def __post_init__(self):
        if self.interests is None:
            self.interests = []
        if self.school_holidays is None:
            self.school_holidays = []


@dataclass
class _Offering:
    id: int = 1
    site_id: int = 1
    name: str = ""
    description: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    program_type: ProgramType = ProgramType.unknown
    start_date: date | None = None
    end_date: date | None = None
    days_of_week: list[str] = None
    time_start: time | None = None
    time_end: time | None = None
    status: str = OfferingStatus.active.value
    location_id: int | None = None

    def __post_init__(self):
        if self.days_of_week is None:
            self.days_of_week = []


@dataclass
class _Block:
    id: int = 1
    kid_id: int = 1
    source: str = UnavailabilitySource.school.value
    days_of_week: list[str] = None
    time_start: time | None = None
    time_end: time | None = None
    date_start: date | None = None
    date_end: date | None = None
    active: bool = True

    def __post_init__(self):
        if self.days_of_week is None:
            self.days_of_week = []


ALIASES = {
    "soccer": ["soccer", "futbol", "kickers"],
    "baseball": ["baseball", "t-ball", "tball", "coach pitch"],
}


# --- age gate -----------------------------------------------------------------

def test_age_uses_offering_start_date_not_today():
    kid = _Kid(dob=date(2021, 5, 1))
    offering = _Offering(start_date=date(2026, 5, 15), age_min=5, age_max=6)
    today = date(2026, 4, 22)
    # today's age = 4; age at start = 5
    r = age_fits(kid, offering, today=today)
    assert r.passed, r.detail
    assert "5" in r.detail


def test_age_just_missed_rejects():
    kid = _Kid(dob=date(2021, 5, 1))
    offering = _Offering(start_date=date(2026, 4, 25), age_min=5)  # before birthday
    today = date(2026, 4, 22)
    r = age_fits(kid, offering, today=today)
    assert not r.passed
    assert r.code == "too_young"


def test_age_upper_bound_inclusive():
    kid = _Kid(dob=date(2019, 1, 1))
    offering = _Offering(start_date=date(2026, 6, 1), age_max=7)
    today = date(2026, 4, 22)
    r = age_fits(kid, offering, today=today)
    assert r.passed


def test_age_falls_back_to_today_when_no_start_date():
    kid = _Kid(dob=date(2019, 5, 1))
    offering = _Offering(start_date=None, age_min=6)
    today = date(2026, 4, 22)  # age 6
    r = age_fits(kid, offering, today=today)
    assert r.passed


def test_age_unspecified_range_passes():
    kid = _Kid(dob=date(2019, 5, 1))
    offering = _Offering(start_date=date(2026, 6, 1))  # no age_min/max
    today = date(2026, 4, 22)
    r = age_fits(kid, offering, today=today)
    assert r.passed


# --- distance gate ------------------------------------------------------------

def test_distance_unknown_fails_open():
    kid = _Kid(max_distance_mi=15.0)
    offering = _Offering(location_id=None)
    r = distance_fits(kid, offering, distance_mi=None, household_default=None)
    assert r.passed
    assert r.code == "distance_unknown"


def test_distance_under_cap_passes():
    kid = _Kid(max_distance_mi=15.0)
    offering = _Offering(location_id=7)
    r = distance_fits(kid, offering, distance_mi=5.0, household_default=None)
    assert r.passed


def test_distance_over_cap_fails():
    kid = _Kid(max_distance_mi=15.0)
    offering = _Offering(location_id=7)
    r = distance_fits(kid, offering, distance_mi=20.0, household_default=None)
    assert not r.passed
    assert r.code == "too_far"


def test_distance_falls_back_to_household_default():
    kid = _Kid(max_distance_mi=None)
    offering = _Offering(location_id=7)
    r = distance_fits(kid, offering, distance_mi=10.0, household_default=20.0)
    assert r.passed


def test_distance_no_cap_set_passes():
    kid = _Kid(max_distance_mi=None)
    offering = _Offering(location_id=7)
    r = distance_fits(kid, offering, distance_mi=100.0, household_default=None)
    assert r.passed
    assert r.code == "distance_unlimited"


# --- interests gate -----------------------------------------------------------

def test_interests_match_via_program_type():
    kid = _Kid(interests=["soccer"])
    offering = _Offering(program_type=ProgramType.soccer, name="Spring Soccer")
    r = interests_overlap(kid, offering, ALIASES)
    assert r.passed


def test_interests_match_via_alias_in_name():
    kid = _Kid(interests=["baseball"])
    offering = _Offering(program_type=ProgramType.multisport, name="T-Ball Program")
    r = interests_overlap(kid, offering, ALIASES)
    assert r.passed


def test_interests_no_match_rejects():
    kid = _Kid(interests=["swim"])
    offering = _Offering(program_type=ProgramType.soccer, name="Spring Soccer")
    r = interests_overlap(kid, offering, ALIASES)
    assert not r.passed


def test_interests_empty_list_rejects():
    kid = _Kid(interests=[])
    offering = _Offering(program_type=ProgramType.soccer, name="Spring Soccer")
    r = interests_overlap(kid, offering, ALIASES)
    assert not r.passed


# --- status gate --------------------------------------------------------------

def test_offering_active_passes():
    offering = _Offering(status=OfferingStatus.active.value, end_date=date(2027, 1, 1))
    today = date(2026, 4, 22)
    r = offering_active_and_not_ended(offering, today=today)
    assert r.passed


def test_offering_ended_rejects():
    offering = _Offering(status=OfferingStatus.active.value, end_date=date(2026, 1, 1))
    today = date(2026, 4, 22)
    r = offering_active_and_not_ended(offering, today=today)
    assert not r.passed
    assert r.code == "ended"


def test_offering_withdrawn_rejects():
    offering = _Offering(status=OfferingStatus.withdrawn.value)
    today = date(2026, 4, 22)
    r = offering_active_and_not_ended(offering, today=today)
    assert not r.passed
    assert r.code == "not_active"


# --- no-conflict gate ---------------------------------------------------------

def _school_block():
    return _Block(
        source=UnavailabilitySource.school.value,
        days_of_week=["mon", "tue", "wed", "thu", "fri"],
        time_start=time(8, 0),
        time_end=time(15, 0),
        date_start=date(2026, 9, 2),
        date_end=date(2027, 6, 14),
    )


def test_summer_offering_passes_school_year_gate():
    """A summer program (Jun-Aug) should pass even though school weekday 8-3 is blocked."""
    block = _school_block()
    offering = _Offering(
        start_date=date(2026, 6, 15),
        end_date=date(2026, 8, 15),
        days_of_week=["mon", "wed"],
        time_start=time(9, 0),
        time_end=time(12, 0),
    )
    r = no_conflict_with_unavailability(offering, [block], school_holidays=set(), today=date(2026, 4, 22))
    assert r.passed, r.detail


def test_during_school_year_conflicts_with_school():
    block = _school_block()
    offering = _Offering(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 11, 1),
        days_of_week=["tue"],
        time_start=time(10, 0),   # overlaps 08-15
        time_end=time(11, 0),
    )
    r = no_conflict_with_unavailability(offering, [block], school_holidays=set(), today=date(2026, 4, 22))
    assert not r.passed


def test_after_school_during_school_year_passes():
    block = _school_block()
    offering = _Offering(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 11, 1),
        days_of_week=["tue"],
        time_start=time(16, 0),
        time_end=time(17, 0),
    )
    r = no_conflict_with_unavailability(offering, [block], school_holidays=set(), today=date(2026, 4, 22))
    assert r.passed


def test_school_holiday_carves_exception_on_specific_date():
    """Offering lands on a listed school holiday → school block skipped for that date."""
    block = _school_block()
    # MLK Day 2027-01-18 is a Monday during the school year
    offering = _Offering(
        start_date=date(2027, 1, 18),
        end_date=date(2027, 1, 18),
        days_of_week=["mon"],
        time_start=time(10, 0),
        time_end=time(11, 0),
    )
    r = no_conflict_with_unavailability(
        offering, [block],
        school_holidays={date(2027, 1, 18)},
        today=date(2026, 4, 22),
    )
    assert r.passed, r.detail


def test_partial_schedule_fails_open():
    block = _school_block()
    offering = _Offering(start_date=None, end_date=None, days_of_week=[], time_start=None, time_end=None)
    r = no_conflict_with_unavailability(offering, [block], school_holidays=set(), today=date(2026, 4, 22))
    assert r.passed
    assert r.code == "schedule_partial"


def test_enrollment_block_blocks_overlapping_offering():
    block = _Block(
        source=UnavailabilitySource.enrollment.value,
        days_of_week=["sat"],
        time_start=time(9, 0),
        time_end=time(10, 0),
        date_start=date(2026, 5, 1),
        date_end=date(2026, 7, 1),
    )
    offering = _Offering(
        start_date=date(2026, 5, 10),
        end_date=date(2026, 6, 20),
        days_of_week=["sat"],
        time_start=time(9, 30),   # overlaps
        time_end=time(10, 30),
    )
    r = no_conflict_with_unavailability(offering, [block], school_holidays=set(), today=date(2026, 4, 22))
    assert not r.passed
