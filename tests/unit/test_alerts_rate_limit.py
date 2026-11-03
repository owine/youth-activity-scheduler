from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
import structlog.testing

from yas.alerts.rate_limit import (
    coalesce,
    is_in_quiet_hours,
    should_rate_limit_push,
)
from yas.db.models._types import AlertType


@dataclass
class _FakeAlert:
    id: int
    kid_id: int | None
    type: str
    scheduled_for: datetime
    payload_json: dict = field(default_factory=dict)


def _a(id_, kid, atype, offset_s: int) -> _FakeAlert:
    return _FakeAlert(
        id=id_,
        kid_id=kid,
        type=atype.value,
        scheduled_for=datetime(2026, 5, 5, 10, 0, tzinfo=UTC) + timedelta(seconds=offset_s),
    )


def test_coalesce_single_alert_single_group():
    alerts = [_a(1, 1, AlertType.new_match, 0)]
    groups = coalesce(alerts, window_s=600)
    assert len(groups) == 1
    assert len(groups[0].members) == 1


def test_coalesce_merges_same_kid_type_within_window():
    alerts = [
        _a(1, 1, AlertType.new_match, 0),
        _a(2, 1, AlertType.new_match, 60),
        _a(3, 1, AlertType.new_match, 120),
    ]
    groups = coalesce(alerts, window_s=600)
    assert len(groups) == 1
    assert {m.id for m in groups[0].members} == {1, 2, 3}


def test_coalesce_does_not_merge_across_window():
    alerts = [
        _a(1, 1, AlertType.new_match, 0),
        _a(2, 1, AlertType.new_match, 700),
    ]
    groups = coalesce(alerts, window_s=600)
    assert len(groups) == 2


def test_coalesce_does_not_merge_different_types():
    alerts = [
        _a(1, 1, AlertType.new_match, 0),
        _a(2, 1, AlertType.reg_opens_24h, 60),
    ]
    groups = coalesce(alerts, window_s=600)
    assert len(groups) == 2


def test_coalesce_does_not_merge_different_kids():
    alerts = [
        _a(1, 1, AlertType.new_match, 0),
        _a(2, 2, AlertType.new_match, 60),
    ]
    groups = coalesce(alerts, window_s=600)
    assert len(groups) == 2


def test_coalesce_non_coalesceable_types_pass_through():
    alerts = [
        _a(1, 1, AlertType.reg_opens_now, 0),
        _a(2, 1, AlertType.reg_opens_now, 60),
        _a(3, 1, AlertType.watchlist_hit, 0),
        _a(4, 1, AlertType.watchlist_hit, 60),
    ]
    groups = coalesce(alerts, window_s=600)
    assert len(groups) == 4


def test_coalesce_stable_ordering_by_scheduled_for():
    alerts = [
        _a(3, 1, AlertType.new_match, 120),
        _a(1, 1, AlertType.new_match, 0),
        _a(2, 1, AlertType.new_match, 60),
    ]
    groups = coalesce(alerts, window_s=600)
    assert groups[0].lead.id == 1


@pytest.mark.parametrize(
    "sent,cap,expected",
    [
        (0, 5, False),
        (4, 5, False),
        (5, 5, True),
        (10, 5, True),
    ],
)
def test_should_rate_limit_push(sent, cap, expected):
    assert should_rate_limit_push(sent, cap) is expected


def test_quiet_hours_same_day_window():
    now = datetime(2026, 5, 5, 14, 0, tzinfo=UTC)
    assert is_in_quiet_hours(now, "13:00", "15:00") is True
    assert is_in_quiet_hours(now, "15:00", "16:00") is False


def test_quiet_hours_wrap_around_midnight():
    assert is_in_quiet_hours(datetime(2026, 5, 5, 23, 0, tzinfo=UTC), "22:00", "07:00") is True
    assert is_in_quiet_hours(datetime(2026, 5, 5, 3, 0, tzinfo=UTC), "22:00", "07:00") is True
    assert is_in_quiet_hours(datetime(2026, 5, 5, 8, 0, tzinfo=UTC), "22:00", "07:00") is False
    assert is_in_quiet_hours(datetime(2026, 5, 5, 21, 30, tzinfo=UTC), "22:00", "07:00") is False


def test_quiet_hours_none_fields_returns_false():
    now = datetime.now(UTC)
    assert is_in_quiet_hours(now, None, "07:00") is False
    assert is_in_quiet_hours(now, "22:00", None) is False
    assert is_in_quiet_hours(now, None, None) is False


def test_quiet_hours_boundary_inclusive_at_start_exclusive_at_end():
    assert is_in_quiet_hours(datetime(2026, 5, 5, 22, 0, tzinfo=UTC), "22:00", "07:00") is True
    assert is_in_quiet_hours(datetime(2026, 5, 5, 7, 0, tzinfo=UTC), "22:00", "07:00") is False


@pytest.fixture
def _fresh_quiet_hours_warnings(monkeypatch):
    """The warn-once memory is process-wide; start each test without it."""
    import yas.alerts.rate_limit as rate_limit

    monkeypatch.setattr(rate_limit, "_warned_invalid_quiet_hours", set())


@pytest.mark.usefixtures("_fresh_quiet_hours_warnings")
@pytest.mark.parametrize(
    ("start", "end"),
    [("22:00", "24:30"), ("25:99", "07:00"), ("22:00", "7am"), ("", "07:00"), ("22:60", "07:00")],
)
def test_quiet_hours_invalid_value_is_not_quiet(start, end):
    """A bad stored value used to raise ValueError inside the delivery loop,
    which exited the worker. The window is ignored instead, with a warning."""
    with structlog.testing.capture_logs() as logs:
        assert is_in_quiet_hours(datetime(2026, 5, 5, 23, 0, tzinfo=UTC), start, end) is False
    assert [e["event"] for e in logs if e["log_level"] == "warning"] == [
        "delivery.quiet_hours.invalid"
    ]


@pytest.mark.usefixtures("_fresh_quiet_hours_warnings")
def test_quiet_hours_invalid_value_warns_once():
    now = datetime(2026, 5, 5, 23, 0, tzinfo=UTC)
    with structlog.testing.capture_logs() as logs:
        for _ in range(3):
            assert is_in_quiet_hours(now, "21:00", "24:30") is False
    assert len([e for e in logs if e["event"] == "delivery.quiet_hours.invalid"]) == 1


def test_quiet_hours_end_of_24_00_means_until_midnight():
    """The API never validated quiet hours, so "24:00" can be stored. It used to
    parse as invalid and silently switch quiet hours off; it means midnight."""

    def at(h: int, m: int) -> datetime:
        return datetime(2026, 5, 5, h, m, tzinfo=UTC)

    assert is_in_quiet_hours(at(22, 0), "22:00", "24:00") is True
    assert is_in_quiet_hours(at(23, 59), "22:00", "24:00") is True
    assert is_in_quiet_hours(at(0, 0), "22:00", "24:00") is False
    assert is_in_quiet_hours(at(21, 59), "22:00", "24:00") is False
    # As a start bound it is midnight too.
    assert is_in_quiet_hours(at(3, 0), "24:00", "07:00") is True
    assert is_in_quiet_hours(at(7, 0), "24:00", "07:00") is False
