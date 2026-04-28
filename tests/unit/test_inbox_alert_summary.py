"""Coverage for every AlertType branch of the inbox summary dispatch."""

import pytest

from yas.db.models._types import AlertType
from yas.web.routes.inbox_alert_summary import summarize_alert


def test_watchlist_hit():
    s = summarize_alert(
        AlertType.watchlist_hit,
        kid_name="Sam",
        payload={"offering_name": "Spring T-Ball", "site_name": "Lil Sluggers"},
    )
    assert "Sam" in s and "Spring T-Ball" in s


@pytest.mark.parametrize(
    "alert_type,window_text",
    [
        (AlertType.reg_opens_24h, "24h"),
        (AlertType.reg_opens_1h, "1 hour"),
        (AlertType.reg_opens_now, "now"),
    ],
)
def test_reg_opens_variants(alert_type, window_text):
    s = summarize_alert(
        alert_type,
        kid_name="Sam",
        payload={"offering_name": "Spring T-Ball", "registration_url": "https://x"},
    )
    assert "Spring T-Ball" in s
    assert window_text.lower() in s.lower()


def test_new_match():
    s = summarize_alert(
        AlertType.new_match,
        kid_name="Sam",
        payload={"offering_name": "Beginner Swim"},
    )
    assert "Sam" in s and "Beginner Swim" in s


def test_crawl_failed():
    s = summarize_alert(
        AlertType.crawl_failed,
        kid_name=None,
        payload={"site_name": "North Side YMCA"},
    )
    assert "North Side YMCA" in s and ("crawl" in s.lower() or "fail" in s.lower())


def test_schedule_posted():
    s = summarize_alert(
        AlertType.schedule_posted,
        kid_name=None,
        payload={"site_name": "Chi Park Dist", "n_offerings": 6},
    )
    assert "Chi Park Dist" in s and "6" in s


def test_site_stagnant():
    s = summarize_alert(
        AlertType.site_stagnant,
        kid_name=None,
        payload={"site_name": "Pottery Barn"},
    )
    assert "Pottery Barn" in s and "stagnant" in s.lower()


def test_no_matches_for_kid():
    s = summarize_alert(
        AlertType.no_matches_for_kid,
        kid_name="Maya",
        payload={},
    )
    assert "Maya" in s and "no" in s.lower()


def test_push_cap():
    s = summarize_alert(
        AlertType.push_cap,
        kid_name="Sam",
        payload={"cap": 5},
    )
    assert "Sam" in s and "5" in s


def test_digest():
    s = summarize_alert(
        AlertType.digest,
        kid_name="Sam",
        payload={"top_line": "Sam's activities — 3 new matches"},
    )
    assert "Sam" in s


def test_unknown_alert_type_falls_back_to_type_name():
    # Defensive: dispatch table must not raise on unexpected input
    class FakeType:
        value = "unknown_type"

    s = summarize_alert(FakeType(), kid_name=None, payload={})  # type: ignore[arg-type]
    assert "unknown_type" in s.lower() or "alert" in s.lower()
