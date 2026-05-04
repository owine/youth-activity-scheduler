from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import pytest

from yas.matching.scoring import ScoreBreakdown, compute_score


@dataclass
class _Kid:
    availability: dict = field(default_factory=dict)
    max_distance_mi: float | None = None
    max_drive_minutes: int | None = None


@dataclass
class _Offering:
    days_of_week: list[str] = field(default_factory=list)
    time_start: time | None = None
    time_end: time | None = None
    start_date: date | None = None
    end_date: date | None = None
    registration_opens_at: datetime | None = None
    price_cents: int | None = None
    first_seen: datetime | None = None


TODAY = date(2026, 4, 22)


def test_score_breakdown_weighted_sum():
    bd = ScoreBreakdown(
        availability=1.0,
        distance=1.0,
        price=1.0,
        registration_timing=1.0,
        freshness=1.0,
    )
    assert bd.score == pytest.approx(1.0)


def test_score_all_zeros():
    bd = ScoreBreakdown(
        availability=0.0,
        distance=0.0,
        price=0.0,
        registration_timing=0.0,
        freshness=0.0,
    )
    assert bd.score == 0.0


def test_availability_default_on_missing():
    kid = _Kid(availability={})
    offering = _Offering()
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=None,
        household_max_distance_mi=None,
        today=TODAY,
    )
    assert reasons["availability"] == pytest.approx(0.5)


def test_distance_full_credit_under_cap():
    kid = _Kid(max_distance_mi=10.0)
    offering = _Offering()
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=2.0,
        household_max_distance_mi=None,
        today=TODAY,
    )
    # 2mi < 30% of 10 (=3mi) → full credit
    assert reasons["distance"] == pytest.approx(1.0)


def test_distance_linear_decay():
    kid = _Kid(max_distance_mi=10.0)
    offering = _Offering()
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=6.5,
        household_max_distance_mi=None,
        today=TODAY,
    )
    # between 3 and 10; partial
    assert 0.0 < reasons["distance"] < 1.0


def test_distance_zero_at_cap():
    kid = _Kid(max_distance_mi=10.0)
    offering = _Offering()
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=10.0,
        household_max_distance_mi=None,
        today=TODAY,
    )
    assert reasons["distance"] == pytest.approx(0.0)


def test_distance_uses_drive_time_when_kid_has_drive_cap():
    """When kid has max_drive_minutes set AND drive_minutes is provided,
    the distance signal is computed from drive-time, not miles."""
    kid = _Kid(max_distance_mi=5.0, max_drive_minutes=30)
    offering = _Offering()
    # 9 min drive: well under the 30% threshold (=9 min) → full credit
    # despite distance_mi=50 (which would be 0.0 on miles path).
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=50.0,
        household_max_distance_mi=None,
        today=TODAY,
        drive_minutes=9.0,
    )
    assert reasons["distance"] == pytest.approx(1.0)


def test_distance_drive_time_decays_to_zero_at_drive_cap():
    kid = _Kid(max_drive_minutes=30)
    offering = _Offering()
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=None,
        household_max_distance_mi=None,
        today=TODAY,
        drive_minutes=30.0,
    )
    assert reasons["distance"] == pytest.approx(0.0)


def test_distance_falls_back_to_miles_when_drive_minutes_missing():
    """Provider failed → drive_minutes=None → use miles path."""
    kid = _Kid(max_distance_mi=10.0, max_drive_minutes=30)
    offering = _Offering()
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=2.0,
        household_max_distance_mi=None,
        today=TODAY,
        drive_minutes=None,
    )
    # Falls through to miles signal: 2mi < 30% of 10 → 1.0
    assert reasons["distance"] == pytest.approx(1.0)


def test_distance_ignores_drive_minutes_when_no_drive_cap():
    """drive_minutes provided but kid.max_drive_minutes is None → use miles."""
    kid = _Kid(max_distance_mi=10.0, max_drive_minutes=None)
    offering = _Offering()
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=10.0,
        household_max_distance_mi=None,
        today=TODAY,
        drive_minutes=5.0,
    )
    # Miles path: at cap → 0.0 (drive value ignored)
    assert reasons["distance"] == pytest.approx(0.0)


def test_price_full_when_unset():
    kid = _Kid()
    offering = _Offering(price_cents=99999)
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=None,
        household_max_distance_mi=None,
        today=TODAY,
    )
    assert reasons["price"] == pytest.approx(1.0)


def test_registration_timing_open_now():
    kid = _Kid()
    offering = _Offering(registration_opens_at=datetime(2026, 4, 1, tzinfo=UTC))
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=None,
        household_max_distance_mi=None,
        today=TODAY,
    )
    assert reasons["registration_timing"] == pytest.approx(1.0)


def test_registration_timing_closed():
    kid = _Kid()
    offering = _Offering(
        registration_opens_at=datetime(2026, 4, 1, tzinfo=UTC),
        end_date=date(2026, 4, 15),  # already ended
    )
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=None,
        household_max_distance_mi=None,
        today=TODAY,
    )
    # end_date < today interpreted as "registration closed"
    assert reasons["registration_timing"] == pytest.approx(0.0)


def test_registration_timing_unknown_defaults_half():
    kid = _Kid()
    offering = _Offering(registration_opens_at=None)
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=None,
        household_max_distance_mi=None,
        today=TODAY,
    )
    assert reasons["registration_timing"] == pytest.approx(0.5)


def test_freshness_recent_full():
    kid = _Kid()
    offering = _Offering(first_seen=datetime.now(UTC))
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=None,
        household_max_distance_mi=None,
        today=TODAY,
    )
    assert reasons["freshness"] > 0.95


def test_freshness_old_zero():
    kid = _Kid()
    offering = _Offering(first_seen=datetime.now(UTC) - timedelta(days=120))
    _score, reasons = compute_score(
        kid,
        offering,
        distance_mi=None,
        household_max_distance_mi=None,
        today=TODAY,
    )
    assert reasons["freshness"] == pytest.approx(0.0)


def test_score_is_weighted_combination():
    kid = _Kid(max_distance_mi=10.0)
    offering = _Offering(first_seen=datetime.now(UTC))
    score, _reasons = compute_score(
        kid,
        offering,
        distance_mi=2.0,
        household_max_distance_mi=None,
        today=TODAY,
    )
    # weighted sum with distance=1.0, freshness≈1.0, availability=0.5, price=1.0, reg=0.5
    # 0.5*0.4 + 1.0*0.2 + 1.0*0.1 + 0.5*0.2 + 1.0*0.1 = 0.2 + 0.2 + 0.1 + 0.1 + 0.1 = 0.7
    assert score == pytest.approx(0.7, abs=0.02)
