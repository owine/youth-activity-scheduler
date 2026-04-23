"""Tests for site_stagnant and no_matches_for_kid detectors."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from yas.alerts.detectors.no_matches_for_kid import detect_kids_without_matches
from yas.alerts.detectors.site_stagnant import detect_stagnant_sites
from yas.db.base import Base
from yas.db.models import Kid, Match, Offering, Page, Site
from yas.db.models._types import PageKind
from yas.db.session import create_engine_for, session_scope


async def _make_engine(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/d.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC)
STALE = NOW - timedelta(days=35)   # older than 30-day threshold
FRESH = NOW - timedelta(days=5)    # within 30-day threshold


def _site(name: str = "s", *, active: bool = True, muted_until: datetime | None = None) -> Site:
    return Site(
        name=name,
        base_url=f"https://{name}.example.com",
        active=active,
        muted_until=muted_until,
    )


def _page(site_id: int) -> Page:
    return Page(site_id=site_id, url="https://example.com/schedule", kind=PageKind.schedule)


def _offering(site_id: int, page_id: int, *, first_seen: datetime) -> Offering:
    return Offering(
        site_id=site_id,
        page_id=page_id,
        name="Test Offering",
        normalized_name="test offering",
        first_seen=first_seen,
        last_seen=first_seen,
    )


def _kid(name: str = "k", *, active: bool = True, created_at: datetime) -> Kid:
    return Kid(
        name=name,
        dob=date(2015, 1, 1),
        active=active,
        created_at=created_at,
    )


def _match(kid_id: int, offering_id: int) -> Match:
    return Match(kid_id=kid_id, offering_id=offering_id, score=0.9)


# ---------------------------------------------------------------------------
# site_stagnant detector tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_site_stagnant_includes_stagnant_site(tmp_path):
    """Active site with an offering older than threshold → included."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        site = _site("stale")
        s.add(site)
        await s.flush()
        page = _page(site.id)
        s.add(page)
        await s.flush()
        s.add(_offering(site.id, page.id, first_seen=STALE))

    async with session_scope(engine) as s:
        result = await detect_stagnant_sites(s, threshold_days=30, now=NOW)

    assert result == [site.id]


@pytest.mark.asyncio
async def test_site_stagnant_excludes_recent_offering(tmp_path):
    """Site with a recent offering → not stagnant."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        site = _site("fresh")
        s.add(site)
        await s.flush()
        page = _page(site.id)
        s.add(page)
        await s.flush()
        s.add(_offering(site.id, page.id, first_seen=FRESH))

    async with session_scope(engine) as s:
        result = await detect_stagnant_sites(s, threshold_days=30, now=NOW)

    assert result == []


@pytest.mark.asyncio
async def test_site_stagnant_excludes_muted_site(tmp_path):
    """Site muted until a future time → excluded even if stale."""
    future_mute = NOW + timedelta(days=10)
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        site = _site("muted", muted_until=future_mute)
        s.add(site)
        await s.flush()
        page = _page(site.id)
        s.add(page)
        await s.flush()
        s.add(_offering(site.id, page.id, first_seen=STALE))

    async with session_scope(engine) as s:
        result = await detect_stagnant_sites(s, threshold_days=30, now=NOW)

    assert result == []


@pytest.mark.asyncio
async def test_site_stagnant_excludes_inactive_site(tmp_path):
    """Site with active=False → excluded."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        site = _site("inactive", active=False)
        s.add(site)
        await s.flush()
        page = _page(site.id)
        s.add(page)
        await s.flush()
        s.add(_offering(site.id, page.id, first_seen=STALE))

    async with session_scope(engine) as s:
        result = await detect_stagnant_sites(s, threshold_days=30, now=NOW)

    assert result == []


@pytest.mark.asyncio
async def test_site_stagnant_detector_ignores_fresh_sites(tmp_path):
    """Spec §6.5: site created recently with zero offerings → excluded."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        # site with no offerings at all (just added)
        site = _site("brand_new")
        s.add(site)

    async with session_scope(engine) as s:
        result = await detect_stagnant_sites(s, threshold_days=30, now=NOW)

    assert site.id not in result


@pytest.mark.asyncio
async def test_site_stagnant_expired_mute_does_not_exclude(tmp_path):
    """Expired mute (muted_until < now) should NOT protect the site."""
    past_mute = NOW - timedelta(days=1)
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        site = _site("expired_mute", muted_until=past_mute)
        s.add(site)
        await s.flush()
        page = _page(site.id)
        s.add(page)
        await s.flush()
        s.add(_offering(site.id, page.id, first_seen=STALE))

    async with session_scope(engine) as s:
        result = await detect_stagnant_sites(s, threshold_days=30, now=NOW)

    assert result == [site.id]


# ---------------------------------------------------------------------------
# no_matches_for_kid detector tests
# ---------------------------------------------------------------------------

OLD_ENOUGH = NOW - timedelta(days=10)    # > 7-day threshold
TOO_RECENT = NOW - timedelta(days=3)     # < 7-day threshold


@pytest.mark.asyncio
async def test_no_matches_for_kid_includes_kid_with_zero_matches(tmp_path):
    """Active kid created 10+ days ago with no matches → included."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        kid = _kid("alice", created_at=OLD_ENOUGH)
        s.add(kid)

    async with session_scope(engine) as s:
        result = await detect_kids_without_matches(s, threshold_days=7, now=NOW)

    assert result == [kid.id]


@pytest.mark.asyncio
async def test_no_matches_for_kid_excludes_kid_with_a_match(tmp_path):
    """Active kid with at least one match row → excluded."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        kid = _kid("bob", created_at=OLD_ENOUGH)
        s.add(kid)
        await s.flush()
        # Need a site/page/offering for the match FK
        site = _site("ms")
        s.add(site)
        await s.flush()
        page = _page(site.id)
        s.add(page)
        await s.flush()
        offering = _offering(site.id, page.id, first_seen=STALE)
        s.add(offering)
        await s.flush()
        s.add(_match(kid.id, offering.id))

    async with session_scope(engine) as s:
        result = await detect_kids_without_matches(s, threshold_days=7, now=NOW)

    assert result == []


@pytest.mark.asyncio
async def test_no_matches_for_kid_excludes_inactive_kid(tmp_path):
    """Inactive kid (active=False) → excluded."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        kid = _kid("carol", active=False, created_at=OLD_ENOUGH)
        s.add(kid)

    async with session_scope(engine) as s:
        result = await detect_kids_without_matches(s, threshold_days=7, now=NOW)

    assert result == []


@pytest.mark.asyncio
async def test_no_matches_for_kid_detector_requires_N_days_active(tmp_path):
    """Spec §6.5: kid created 3 days ago (< threshold 7) → excluded even with zero matches."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        kid = _kid("dave", created_at=TOO_RECENT)
        s.add(kid)

    async with session_scope(engine) as s:
        result = await detect_kids_without_matches(s, threshold_days=7, now=NOW)

    assert result == []


@pytest.mark.asyncio
async def test_no_matches_for_kid_multiple_kids_ordering(tmp_path):
    """Result is sorted by id ascending."""
    engine = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        k1 = _kid("eve", created_at=OLD_ENOUGH)
        k2 = _kid("frank", created_at=OLD_ENOUGH)
        s.add(k1)
        s.add(k2)

    async with session_scope(engine) as s:
        result = await detect_kids_without_matches(s, threshold_days=7, now=NOW)

    expected = sorted([k1.id, k2.id])
    assert result == expected
