"""Integration tests: alert enqueue hooks wired into pipeline + matcher paths.

Uses a real SQLite DB (in-memory via tmp_path), a FakeLLMClient, and an
inline FakeFetcher.  No network calls; no notifiers — we only assert that
the correct alerts rows land in the DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from tests.fakes.llm import FakeLLMClient
from yas.crawl.fetcher import FetchError, FetchResult
from yas.crawl.pipeline import crawl_page
from yas.db.base import Base
from yas.db.models import Alert, HouseholdSettings, Kid, Match, Page, Site, WatchlistEntry
from yas.db.models._types import AlertType, ProgramType, WatchlistPriority
from yas.db.session import create_engine_for, session_scope
from yas.llm.schemas import ExtractedOffering

# ---------------------------------------------------------------------------
# Minimal fake fetcher
# ---------------------------------------------------------------------------

_PAGE_HTML = "<!doctype html><html><body><main><h1>Soccer Camp</h1></body></main></html>"


@dataclass
class FakeFetcher:
    """Scripted fetcher — either returns fixed HTML or raises FetchError."""

    html: str = _PAGE_HTML
    raise_error: str | None = None
    call_count: int = 0

    async def fetch(self, page: Any, site: Any) -> FetchResult:
        self.call_count += 1
        if self.raise_error is not None:
            raise FetchError(500, page.url, self.raise_error)
        return FetchResult(
            url=page.url,
            status_code=200,
            html=self.html,
            used_browser=False,
            elapsed_ms=1,
        )

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _make_engine(tmp_path: Any, name: str = "alerts.db") -> Any:
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/{name}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _seed_site_and_page(engine: Any) -> tuple[int, int, Any, Any]:
    """Seed a Site + Page, return (site_id, page_id, site_obj, page_obj)."""
    async with session_scope(engine) as s:
        site = Site(name="Test Site", base_url="http://example.com")
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="http://example.com/schedule")
        s.add(page)
        await s.flush()
        site_id = site.id
        page_id = page.id
    async with session_scope(engine) as s:
        site_obj = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one()
        page_obj = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
    return site_id, page_id, site_obj, page_obj


async def _seed_kid(
    engine: Any,
    *,
    alert_score_threshold: float = 0.3,
    alert_on: dict[str, Any] | None = None,
    dob: date | None = None,
) -> int:
    async with session_scope(engine) as s:
        kid = Kid(
            name="Alice",
            dob=dob or date(2015, 1, 1),
            interests=["soccer"],
            alert_score_threshold=alert_score_threshold,
            alert_on=alert_on or {},
        )
        s.add(kid)
        await s.flush()
        return kid.id


async def _seed_household(engine: Any) -> None:
    """Seed a HouseholdSettings row so matchers do not fail FK lookups."""
    async with session_scope(engine) as s:
        s.add(HouseholdSettings(id=1))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_enqueues_new_match_alert_on_fresh_match(tmp_path: Any) -> None:
    """New offering + one kid scoring above threshold → one new_match alerts row."""
    engine = await _make_engine(tmp_path, "t1.db")
    await _seed_household(engine)
    kid_id = await _seed_kid(engine, alert_score_threshold=0.0)
    _site_id, _page_id, site, page = await _seed_site_and_page(engine)

    llm = FakeLLMClient(
        default=[
            ExtractedOffering(
                name="Soccer Camp",
                program_type=ProgramType.soccer,
                age_min=5,
                age_max=12,
            )
        ]
    )
    fetcher = FakeFetcher()
    await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)

    async with session_scope(engine) as s:
        alerts = (
            await s.execute(select(Alert).where(Alert.type == AlertType.new_match.value))
        ).scalars().all()
        assert len(alerts) == 1, f"Expected 1 new_match alert, got {len(alerts)}"
        assert alerts[0].kid_id == kid_id


@pytest.mark.asyncio
async def test_pipeline_enqueues_watchlist_hit_even_when_new_match_disabled(
    tmp_path: Any,
) -> None:
    """Kid with alert_on.new_match=False + watchlist entry matching offering → watchlist_hit
    alert present; no new_match alert."""
    engine = await _make_engine(tmp_path, "t2.db")
    await _seed_household(engine)
    kid_id = await _seed_kid(
        engine,
        alert_score_threshold=0.0,
        alert_on={"new_match": False},
    )

    # Add a watchlist entry that matches "Soccer Camp"
    async with session_scope(engine) as s:
        s.add(
            WatchlistEntry(
                kid_id=kid_id,
                pattern="soccer",
                priority=WatchlistPriority.normal.value,
            )
        )

    _site_id, _page_id, site, page = await _seed_site_and_page(engine)

    llm = FakeLLMClient(
        default=[
            ExtractedOffering(
                name="Soccer Camp",
                program_type=ProgramType.soccer,
                age_min=5,
                age_max=12,
            )
        ]
    )
    fetcher = FakeFetcher()
    await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)

    async with session_scope(engine) as s:
        watchlist_alerts = (
            await s.execute(select(Alert).where(Alert.type == AlertType.watchlist_hit.value))
        ).scalars().all()
        new_match_alerts = (
            await s.execute(select(Alert).where(Alert.type == AlertType.new_match.value))
        ).scalars().all()

    assert len(watchlist_alerts) >= 1, "Expected at least one watchlist_hit alert"
    assert len(new_match_alerts) == 0, "Expected no new_match alert when new_match is disabled"


@pytest.mark.asyncio
async def test_pipeline_enqueues_countdowns_when_offering_has_registration_opens_at(
    tmp_path: Any,
) -> None:
    """Offering with registration_opens_at in future → three countdown alerts (24h, 1h, now)
    for the matched kid."""
    engine = await _make_engine(tmp_path, "t3.db")
    await _seed_household(engine)
    kid_id = await _seed_kid(engine, alert_score_threshold=0.0)
    _site_id, _page_id, site, page = await _seed_site_and_page(engine)

    # Registration opens 48h from now so all three countdown slots are in the future.
    opens_at = datetime.now(UTC) + timedelta(hours=48)

    llm = FakeLLMClient(
        default=[
            ExtractedOffering(
                name="Soccer Camp",
                program_type=ProgramType.soccer,
                age_min=5,
                age_max=12,
                registration_opens_at=opens_at,
            )
        ]
    )
    fetcher = FakeFetcher()
    await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)

    async with session_scope(engine) as s:
        countdown_types = [
            AlertType.reg_opens_24h.value,
            AlertType.reg_opens_1h.value,
            AlertType.reg_opens_now.value,
        ]
        countdown_alerts = (
            await s.execute(
                select(Alert).where(
                    Alert.type.in_(countdown_types),
                    Alert.kid_id == kid_id,
                )
            )
        ).scalars().all()

    assert len(countdown_alerts) == 3, (
        f"Expected 3 countdown alerts (24h, 1h, now), got {len(countdown_alerts)}"
    )
    alert_types_found = {a.type for a in countdown_alerts}
    assert AlertType.reg_opens_24h.value in alert_types_found
    assert AlertType.reg_opens_1h.value in alert_types_found
    assert AlertType.reg_opens_now.value in alert_types_found


@pytest.mark.asyncio
async def test_pipeline_enqueues_crawl_failed_on_third_consecutive_failure(
    tmp_path: Any,
) -> None:
    """Three fetch failures → exactly one crawl_failed alert on the third;
    fourth failure keeps it at one row (dedup)."""
    engine = await _make_engine(tmp_path, "t4.db")
    _site_id, _page_id, site, page = await _seed_site_and_page(engine)

    llm = FakeLLMClient()
    fetcher = FakeFetcher(raise_error="HTTP 500")

    # Failures 1 and 2 — no crawl_failed alert yet.
    for _ in range(2):
        async with session_scope(engine) as s:
            page = (await s.execute(select(Page).where(Page.id == _page_id))).scalar_one()
            site = (await s.execute(select(Site).where(Site.id == _site_id))).scalar_one()
        await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)

    async with session_scope(engine) as s:
        early_alerts = (
            await s.execute(select(Alert).where(Alert.type == AlertType.crawl_failed.value))
        ).scalars().all()
    assert len(early_alerts) == 0, "No crawl_failed alert should exist before the 3rd failure"

    # Third failure — alert should now exist.
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == _page_id))).scalar_one()
        site = (await s.execute(select(Site).where(Site.id == _site_id))).scalar_one()
    await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)

    async with session_scope(engine) as s:
        alerts_after_3 = (
            await s.execute(select(Alert).where(Alert.type == AlertType.crawl_failed.value))
        ).scalars().all()
    assert len(alerts_after_3) == 1, (
        f"Expected exactly 1 crawl_failed alert after third failure, got {len(alerts_after_3)}"
    )

    # Fourth failure — still exactly one row (dedup via _upsert_alert).
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == _page_id))).scalar_one()
        site = (await s.execute(select(Site).where(Site.id == _site_id))).scalar_one()
    await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)

    async with session_scope(engine) as s:
        alerts_after_4 = (
            await s.execute(select(Alert).where(Alert.type == AlertType.crawl_failed.value))
        ).scalars().all()
    assert len(alerts_after_4) == 1, (
        f"Expected still 1 crawl_failed alert after fourth failure (dedup), got {len(alerts_after_4)}"
    )


@pytest.mark.asyncio
async def test_countdown_rewrite_on_registration_date_change(tmp_path: Any) -> None:
    """When offering's registration_opens_at changes, old unsent countdown rows are
    deleted and new ones inserted at updated scheduled_for times.

    This verifies the delete-old-insert-new logic inside
    enqueue_registration_countdowns (Task 2 implementation)."""
    engine = await _make_engine(tmp_path, "t5.db")
    await _seed_household(engine)
    kid_id = await _seed_kid(engine, alert_score_threshold=0.0)
    _site_id, _page_id, site, page = await _seed_site_and_page(engine)

    # Use fixed future datetimes (not relative to now()) so they differ at minute precision,
    # which is the granularity used by dedup_key_for for countdown alert types.
    opens_at_v1 = datetime(2030, 6, 1, 10, 0, 0, tzinfo=UTC)
    llm_v1 = FakeLLMClient(
        default=[
            ExtractedOffering(
                name="Soccer Camp",
                program_type=ProgramType.soccer,
                age_min=5,
                age_max=12,
                registration_opens_at=opens_at_v1,
            )
        ]
    )
    fetcher = FakeFetcher()
    await crawl_page(engine=engine, fetcher=fetcher, llm=llm_v1, page=page, site=site)

    # Collect first-pass scheduled_for values.
    async with session_scope(engine) as s:
        v1_alerts = (
            await s.execute(
                select(Alert).where(
                    Alert.kid_id == kid_id,
                    Alert.type.in_([
                        AlertType.reg_opens_24h.value,
                        AlertType.reg_opens_1h.value,
                        AlertType.reg_opens_now.value,
                    ]),
                )
            )
        ).scalars().all()
        v1_scheduled = {a.type: a.scheduled_for for a in v1_alerts}
    assert len(v1_alerts) == 3

    # Second crawl: registration_opens_at pushed back by 48h.  Fixed datetime so
    # the minute-precision dedup key differs meaningfully from v1.
    opens_at_v2 = datetime(2030, 6, 3, 10, 0, 0, tzinfo=UTC)
    llm_v2 = FakeLLMClient(
        default=[
            ExtractedOffering(
                name="Soccer Camp",
                program_type=ProgramType.soccer,
                age_min=5,
                age_max=12,
                registration_opens_at=opens_at_v2,
            )
        ]
    )
    # Use a different visible text so the normalized content hash differs from v1,
    # forcing the pipeline to re-extract instead of short-circuiting on hash match.
    _PAGE_HTML_V2 = "<!doctype html><html><body><main><h1>Soccer Camp</h1><p>Updated.</p></body></main></html>"
    fetcher_v2 = FakeFetcher(html=_PAGE_HTML_V2)

    async with session_scope(engine) as s:
        page2 = (await s.execute(select(Page).where(Page.id == _page_id))).scalar_one()
        site2 = (await s.execute(select(Site).where(Site.id == _site_id))).scalar_one()
    await crawl_page(engine=engine, fetcher=fetcher_v2, llm=llm_v2, page=page2, site=site2)

    async with session_scope(engine) as s:
        v2_alerts = (
            await s.execute(
                select(Alert).where(
                    Alert.kid_id == kid_id,
                    Alert.type.in_([
                        AlertType.reg_opens_24h.value,
                        AlertType.reg_opens_1h.value,
                        AlertType.reg_opens_now.value,
                    ]),
                    Alert.sent_at.is_(None),
                    Alert.skipped.is_(False),
                )
            )
        ).scalars().all()
        v2_scheduled = {a.type: a.scheduled_for for a in v2_alerts}

    assert len(v2_alerts) == 3, f"Expected 3 alerts after date change, got {len(v2_alerts)}"
    # The v2 scheduled_for values must all be later than v1.
    for alert_type_val, v2_sf in v2_scheduled.items():
        v1_sf = v1_scheduled.get(alert_type_val)
        assert v1_sf is not None, f"Missing v1 alert for {alert_type_val}"
        # Normalise tz for comparison.
        v2_sf_norm = v2_sf if v2_sf.tzinfo else v2_sf.replace(tzinfo=UTC)
        v1_sf_norm = v1_sf if v1_sf.tzinfo else v1_sf.replace(tzinfo=UTC)
        assert v2_sf_norm > v1_sf_norm, (
            f"{alert_type_val}: v2 scheduled_for ({v2_sf_norm}) should be later than v1 ({v1_sf_norm})"
        )


@pytest.mark.asyncio
async def test_enqueue_new_match_dedups_across_pipeline_and_matcher_paths(
    tmp_path: Any,
) -> None:
    """Calling both the pipeline-path hook and the matcher-path _upsert_match for the
    same (kid, offering) pair must produce exactly one alerts row with type=new_match.

    This pins the dedup_key collision behaviour between the two call sites."""
    engine = await _make_engine(tmp_path, "t6.db")
    await _seed_household(engine)
    kid_id = await _seed_kid(engine, alert_score_threshold=0.0)
    _site_id, _page_id, site, page = await _seed_site_and_page(engine)

    llm = FakeLLMClient(
        default=[
            ExtractedOffering(
                name="Soccer Camp",
                program_type=ProgramType.soccer,
                age_min=5,
                age_max=12,
            )
        ]
    )
    fetcher = FakeFetcher()

    # First crawl goes through the pipeline path: reconcile → rematch_offering →
    # _upsert_match (matcher path alert) → pipeline alert hook.
    # Both fire for the same (kid_id, offering_id) pair.
    await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)

    async with session_scope(engine) as s:
        new_match_alerts = (
            await s.execute(select(Alert).where(Alert.type == AlertType.new_match.value))
        ).scalars().all()
        match_rows = (await s.execute(select(Match))).scalars().all()

    # There must be exactly one Match row and exactly one new_match alert.
    assert len(match_rows) == 1, f"Expected 1 match row, got {len(match_rows)}"
    assert len(new_match_alerts) == 1, (
        f"Dedup must ensure exactly 1 new_match alert across both call paths, "
        f"got {len(new_match_alerts)}"
    )
    assert new_match_alerts[0].kid_id == kid_id
