"""Tests for digest builder: gather_digest_payload and render_digest."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from yas.alerts.digest.builder import DigestPayload, gather_digest_payload, render_digest
from yas.db.base import Base
from yas.db.models import Alert, Kid, Match, Offering, Page, Site
from yas.db.models._types import AlertType, PageKind
from yas.db.session import create_engine_for, session_scope

# ---------------------------------------------------------------------------
# Engine / schema helper
# ---------------------------------------------------------------------------


async def _make_engine(tmp_path: Any) -> Any:
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/d.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


# ---------------------------------------------------------------------------
# Fixed timestamps
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC)
TODAY = NOW.date()
WINDOW_START = datetime(2026, 4, 22, 0, 0, 0, tzinfo=UTC)
WINDOW_END = NOW


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _site(name: str = "s") -> Site:
    return Site(name=name, base_url=f"https://{name}.example.com", active=True)


def _page(site_id: int) -> Page:
    return Page(site_id=site_id, url="https://example.com/sched", kind=PageKind.schedule)


def _offering(
    site_id: int,
    page_id: int,
    *,
    name: str = "Test Offering",
    start_date: date | None = None,
    price_cents: int | None = None,
    registration_opens_at: datetime | None = None,
    first_seen: datetime | None = None,
) -> Offering:
    fs = first_seen if first_seen is not None else NOW - timedelta(days=1)
    return Offering(
        site_id=site_id,
        page_id=page_id,
        name=name,
        normalized_name=name.lower(),
        start_date=start_date,
        price_cents=price_cents,
        registration_opens_at=registration_opens_at,
        first_seen=fs,
        last_seen=fs,
    )


def _kid(
    name: str = "Alice",
    *,
    created_at: datetime | None = None,
) -> Kid:
    return Kid(
        name=name,
        dob=date(2015, 1, 1),
        active=True,
        created_at=created_at if created_at is not None else NOW - timedelta(days=30),
    )


def _match(
    kid_id: int, offering_id: int, *, score: float = 0.85, computed_at: datetime | None = None
) -> Match:
    return Match(
        kid_id=kid_id,
        offering_id=offering_id,
        score=score,
        computed_at=computed_at if computed_at is not None else NOW - timedelta(hours=1),
    )


def _alert(
    kid_id: int | None,
    alert_type: str,
    *,
    skipped: bool = False,
    sent_at: datetime | None = None,
    scheduled_for: datetime | None = None,
    site_id: int | None = None,
    offering_id: int | None = None,
    payload_json: dict[str, Any] | None = None,
) -> Alert:
    return Alert(
        type=alert_type,
        kid_id=kid_id,
        site_id=site_id,
        offering_id=offering_id,
        channels=["email"],
        scheduled_for=scheduled_for if scheduled_for is not None else NOW,
        sent_at=sent_at,
        skipped=skipped,
        dedup_key=f"test-{alert_type}-{kid_id}-{scheduled_for}",
        payload_json=payload_json or {},
    )


# ---------------------------------------------------------------------------
# Tests — gather_digest_payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gather_payload_new_matches_only_within_window(tmp_path: Any) -> None:
    """Matches computed within the window are included; older matches are not."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        site = _site("ms")
        s.add(site)
        await s.flush()
        page = _page(site.id)
        s.add(page)
        await s.flush()

        kid = _kid()
        s.add(kid)
        await s.flush()

        # Offering in-window
        o_in = _offering(site.id, page.id, name="Soccer Camp")
        s.add(o_in)
        # Offering out-of-window (computed before window_start)
        o_out = _offering(site.id, page.id, name="Old Camp")
        s.add(o_out)
        await s.flush()

        s.add(_match(kid.id, o_in.id, computed_at=NOW - timedelta(hours=2)))
        s.add(_match(kid.id, o_out.id, computed_at=WINDOW_START - timedelta(hours=1)))

    async with session_scope(engine) as s:
        kid_row = await s.get(Kid, kid.id)
        assert kid_row is not None
        payload = await gather_digest_payload(
            s,
            kid_row,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            alert_no_matches_kid_days=7,
            now=NOW,
        )

    assert len(payload.new_matches) == 1
    assert payload.new_matches[0]["offering_name"] == "Soccer Camp"


@pytest.mark.asyncio
async def test_gather_payload_starting_soon_14_day_window(tmp_path: Any) -> None:
    """Matched offerings starting within 14 days appear in starting_soon."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        site = _site()
        s.add(site)
        await s.flush()
        page = _page(site.id)
        s.add(page)
        await s.flush()
        kid = _kid()
        s.add(kid)
        await s.flush()

        # Starts in 7 days → in window
        o_soon = _offering(site.id, page.id, name="Soon Camp", start_date=TODAY + timedelta(days=7))
        # Starts in 20 days → out of window
        o_far = _offering(site.id, page.id, name="Far Camp", start_date=TODAY + timedelta(days=20))
        s.add(o_soon)
        s.add(o_far)
        await s.flush()

        # Both matched, but computed before the window (so new_matches=0)
        s.add(_match(kid.id, o_soon.id, computed_at=WINDOW_START - timedelta(hours=1)))
        s.add(_match(kid.id, o_far.id, computed_at=WINDOW_START - timedelta(hours=1)))

    async with session_scope(engine) as s:
        kid_row = await s.get(Kid, kid.id)
        assert kid_row is not None
        payload = await gather_digest_payload(
            s,
            kid_row,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            alert_no_matches_kid_days=7,
            now=NOW,
        )

    assert len(payload.starting_soon) == 1
    assert payload.starting_soon[0]["offering_name"] == "Soon Camp"


@pytest.mark.asyncio
async def test_gather_payload_registration_calendar_14_day_window(tmp_path: Any) -> None:
    """Matched offerings with registration opening in 14 days appear in registration_calendar."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        site = _site()
        s.add(site)
        await s.flush()
        page = _page(site.id)
        s.add(page)
        await s.flush()
        kid = _kid()
        s.add(kid)
        await s.flush()

        reg_soon = NOW + timedelta(days=5)
        reg_far = NOW + timedelta(days=20)

        o_soon = _offering(site.id, page.id, name="Opens Soon", registration_opens_at=reg_soon)
        o_far = _offering(site.id, page.id, name="Opens Far", registration_opens_at=reg_far)
        s.add(o_soon)
        s.add(o_far)
        await s.flush()

        s.add(_match(kid.id, o_soon.id, computed_at=WINDOW_START - timedelta(hours=1)))
        s.add(_match(kid.id, o_far.id, computed_at=WINDOW_START - timedelta(hours=1)))

    async with session_scope(engine) as s:
        kid_row = await s.get(Kid, kid.id)
        assert kid_row is not None
        payload = await gather_digest_payload(
            s,
            kid_row,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            alert_no_matches_kid_days=7,
            now=NOW,
        )

    assert len(payload.registration_calendar) == 1
    assert payload.registration_calendar[0]["offering_name"] == "Opens Soon"


@pytest.mark.asyncio
async def test_gather_payload_delivery_failures_since_last_digest(tmp_path: Any) -> None:
    """Skipped alerts after the last digest are included in delivery_failures."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        kid = _kid()
        s.add(kid)
        await s.flush()

        last_digest_sent = WINDOW_START + timedelta(hours=6)

        # A digest alert sent after window_start → defines the failure cutoff
        s.add(
            _alert(
                kid.id,
                AlertType.digest.value,
                sent_at=last_digest_sent,
                scheduled_for=last_digest_sent,
            )
        )
        # Skipped alert AFTER the last digest → should be included
        s.add(
            _alert(
                kid.id,
                AlertType.new_match.value,
                skipped=True,
                scheduled_for=last_digest_sent + timedelta(hours=1),
                payload_json={"_last_error": "channel timeout"},
            )
        )
        # Skipped alert BEFORE the last digest → should NOT be included
        s.add(
            _alert(
                kid.id,
                AlertType.new_match.value,
                skipped=True,
                scheduled_for=last_digest_sent - timedelta(hours=1),
            )
        )

    async with session_scope(engine) as s:
        kid_row = await s.get(Kid, kid.id)
        assert kid_row is not None
        payload = await gather_digest_payload(
            s,
            kid_row,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            alert_no_matches_kid_days=7,
            now=NOW,
        )

    assert len(payload.delivery_failures) == 1
    assert payload.delivery_failures[0]["detail"] == "channel timeout"


@pytest.mark.asyncio
async def test_gather_payload_site_stagnant_includes_detector_output(tmp_path: Any) -> None:
    """site_stagnant_ids reflects detect_stagnant_sites output."""
    engine = await _make_engine(tmp_path)
    stale_first_seen = NOW - timedelta(days=35)

    async with session_scope(engine) as s:
        kid = _kid()
        s.add(kid)
        site = _site("stale")
        s.add(site)
        await s.flush()
        page = _page(site.id)
        s.add(page)
        await s.flush()
        s.add(_offering(site.id, page.id, first_seen=stale_first_seen))

    async with session_scope(engine) as s:
        kid_row = await s.get(Kid, kid.id)
        assert kid_row is not None
        payload = await gather_digest_payload(
            s,
            kid_row,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            alert_no_matches_kid_days=7,
            now=NOW,
        )

    assert site.id in payload.site_stagnant_ids


@pytest.mark.asyncio
async def test_gather_payload_under_no_matches_threshold_flag(tmp_path: Any) -> None:
    """Kid created recently with no matches → under_no_matches_threshold=True."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        # Created only 2 days ago — well within the 7-day threshold
        kid = _kid(created_at=NOW - timedelta(days=2))
        s.add(kid)

    async with session_scope(engine) as s:
        kid_row = await s.get(Kid, kid.id)
        assert kid_row is not None
        payload = await gather_digest_payload(
            s,
            kid_row,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            alert_no_matches_kid_days=7,
            now=NOW,
        )

    assert payload.under_no_matches_threshold is True


@pytest.mark.asyncio
async def test_gather_payload_not_under_threshold_when_matches_exist(tmp_path: Any) -> None:
    """Kid created recently but WITH a match → under_no_matches_threshold=False."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        kid = _kid(created_at=NOW - timedelta(days=2))
        s.add(kid)
        site = _site()
        s.add(site)
        await s.flush()
        page = _page(site.id)
        s.add(page)
        await s.flush()
        o = _offering(site.id, page.id)
        s.add(o)
        await s.flush()
        s.add(_match(kid.id, o.id))

    async with session_scope(engine) as s:
        kid_row = await s.get(Kid, kid.id)
        assert kid_row is not None
        payload = await gather_digest_payload(
            s,
            kid_row,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            alert_no_matches_kid_days=7,
            now=NOW,
        )

    assert payload.under_no_matches_threshold is False


# ---------------------------------------------------------------------------
# Tests — render_digest
# ---------------------------------------------------------------------------


def _empty_payload() -> DigestPayload:
    return DigestPayload(
        kid_id=1,
        kid_name="Alice",
        for_date=TODAY,
    )


def _payload_with_matches() -> DigestPayload:
    return DigestPayload(
        kid_id=1,
        kid_name="Alice",
        for_date=TODAY,
        new_matches=[
            {
                "offering_id": 10,
                "offering_name": "Soccer Camp",
                "score": 0.92,
                "site_name": "City Rec",
                "start_date": TODAY + timedelta(days=5),
                "price_cents": 15000,
                "registration_opens_at": None,
                "registration_url": "https://example.com/register",
            }
        ],
    )


def test_render_digest_produces_both_text_and_html() -> None:
    """Smoke test: render_digest returns two non-empty strings without Jinja errors."""
    plain, html = render_digest(_empty_payload(), top_line="Good morning!")
    assert isinstance(plain, str)
    assert isinstance(html, str)
    assert len(plain) > 0
    assert len(html) > 0


def test_render_digest_includes_top_line() -> None:
    """top_line appears in both plain-text and HTML output."""
    top = "Here's your daily digest for Alice."
    plain, html = render_digest(_empty_payload(), top_line=top)
    assert top in plain
    assert top in html


def test_render_digest_empty_sections_omitted_cleanly() -> None:
    """An all-empty payload renders without section headers for missing sections."""
    plain, _html = render_digest(_empty_payload(), top_line="Hi!")
    assert "NEW MATCHES" not in plain
    assert "STARTING SOON" not in plain
    assert "REGISTRATION OPENS" not in plain
    assert "DELIVERY ISSUES" not in plain


def test_render_digest_shows_new_matches_section() -> None:
    """When new_matches is non-empty, the section appears in output."""
    plain, _html = render_digest(_payload_with_matches(), top_line="Hi!")
    assert "NEW MATCHES" in plain
    assert "Soccer Camp" in plain
    assert "$150.00" in plain


def test_digest_no_matches_kid_under_threshold_sends_honest_message() -> None:
    """Spec §6.5: under_no_matches_threshold=True renders a no-results message."""
    payload = DigestPayload(
        kid_id=1,
        kid_name="Alice",
        for_date=TODAY,
        under_no_matches_threshold=True,
    )
    plain, html = render_digest(payload, top_line="Hi Alice!")
    # Both channels must contain the honest "haven't found" message
    assert "haven't found" in plain
    assert "haven't found" in html
    # No section headers should appear
    assert "NEW MATCHES" not in plain
    assert "STARTING SOON" not in plain
