"""Pre-migration digest snapshots.

These goldens lock the current digest output BEFORE the shared-base
refactor. After Task 4 lands, the `chrome` portions (DOCTYPE, <body>, footer)
are re-baselined deliberately; section content must remain byte-identical.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from yas.alerts.digest.builder import DigestPayload, render_digest

_GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "digest"


def _payload_with_matches() -> DigestPayload:
    return DigestPayload(
        kid_id=1,
        kid_name="Ada",
        for_date=date(2026, 5, 19),
        new_matches=[
            {
                "offering_id": 10,
                "offering_name": "Soccer Camp",
                "score": 0.91,
                "site_id": 1,
                "site_name": "Park District",
                "start_date": date(2026, 6, 1),
                "price_cents": 15000,
                "registration_opens_at": datetime(2026, 5, 25, 9, 0, tzinfo=UTC),
                "registration_url": "https://example.com/reg/10",
            }
        ],
        starting_soon=[],
        registration_calendar=[],
        delivery_failures=[],
        site_stagnant_ids=[],
        silent_schedule_posts=[],
        under_no_matches_threshold=False,
    )


def _payload_empty() -> DigestPayload:
    return DigestPayload(kid_id=2, kid_name="Bo", for_date=date(2026, 5, 19))


def _payload_under_threshold() -> DigestPayload:
    return DigestPayload(
        kid_id=3,
        kid_name="Cy",
        for_date=date(2026, 5, 19),
        under_no_matches_threshold=True,
    )


_CASES = [
    ("with_matches", _payload_with_matches, "Ada — 1 new match"),
    ("empty", _payload_empty, "Bo — quiet day"),
    ("under_threshold", _payload_under_threshold, "Cy — still searching"),
]


@pytest.mark.parametrize("name, factory, top_line", _CASES, ids=[c[0] for c in _CASES])
def test_digest_golden(name: str, factory, top_line: str) -> None:
    txt, html = render_digest(factory(), top_line)
    expected_txt = (_GOLDEN_DIR / f"{name}.txt").read_text()
    expected_html = (_GOLDEN_DIR / f"{name}.html").read_text()
    assert txt == expected_txt, f"text diverges for {name}"
    assert html == expected_html, f"html diverges for {name}"
