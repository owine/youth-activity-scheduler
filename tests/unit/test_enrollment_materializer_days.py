"""attended_days: which weekdays an enrollment actually occupies (#636)."""

from types import SimpleNamespace

from yas.unavailability.enrollment_materializer import attended_days


def _days(chosen, listed):
    return attended_days(
        SimpleNamespace(days_of_week=chosen),  # type: ignore[arg-type]
        SimpleNamespace(days_of_week=listed),  # type: ignore[arg-type]
    )


def test_no_choice_means_every_listed_day():
    assert _days(None, ["mon", "wed"]) == ["mon", "wed"]
    assert _days([], ["mon", "wed"]) == ["mon", "wed"]


def test_choice_wins_when_the_offering_lists_it():
    assert _days(["wed"], ["mon", "tue", "wed"]) == ["wed"]


def test_choice_the_offering_dropped_falls_back_to_the_offering_days():
    """A crawl moved the slot off the chosen day; blocking a day with no class
    would be wrong, so the block follows the offering until the family re-picks."""
    assert _days(["tue"], ["wed", "thu"]) == ["wed", "thu"]


def test_partial_overlap_keeps_only_the_days_still_offered():
    assert _days(["tue", "thu"], ["wed", "thu"]) == ["thu"]


def test_offering_with_no_days_keeps_the_choice():
    assert _days(["sat"], []) == ["sat"]
