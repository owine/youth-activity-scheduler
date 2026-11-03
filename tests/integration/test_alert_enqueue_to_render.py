"""Alerts written by the real enqueuers must render, summarize and report.

The builders read `offering_id` from `payload_json`, while the enqueuers store it
only in the `offering_id` column. Every fixture seeded the payload by hand, so the
suite passed while every new_match, watchlist_hit and reg_opens_now alert in prod
failed to render and was skipped. These tests enqueue through the production
functions instead of constructing Alert rows.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from tests.fakes.notifier import FakeNotifier
from yas.alerts.delivery import send_alert_group
from yas.alerts.enqueuer import (
    enqueue_crawl_failed,
    enqueue_new_match,
    enqueue_no_matches_for_kid,
    enqueue_push_cap,
    enqueue_registration_countdowns,
    enqueue_watchlist_hit,
)
from yas.alerts.rate_limit import coalesce
from yas.alerts.routing import seed_default_routing
from yas.config import Settings
from yas.db.base import Base
from yas.db.models import Alert, Kid, Match, Offering, Page, Site
from yas.db.models._types import AlertType, PageKind
from yas.db.models.watchlist import WatchlistEntry
from yas.db.session import create_engine_for, session_scope
from yas.email import render_email
from yas.email.builders import gather_digest_payload
from yas.web.routes.inbox_alert_summary import load_alert_names, summarize_alert


async def _seed(tmp_path: Any):
    eng = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/r.db")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with session_scope(eng) as s:
        site = Site(name="Park", base_url="https://p.example.com", active=True)
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule)
        s.add(page)
        await s.flush()
        kid = Kid(name="Ada", dob=date(2019, 5, 1))
        s.add(kid)
        await s.flush()
        off = Offering(
            site_id=site.id,
            page_id=page.id,
            name="Soccer Camp",
            normalized_name="soccer camp",
            start_date=date.today() + timedelta(days=30),
            registration_url="https://p.example.com/r/10",
            registration_opens_at=datetime.now(UTC) + timedelta(days=2),
        )
        s.add(off)
        await s.flush()
        s.add(Match(kid_id=kid.id, offering_id=off.id, score=0.9, computed_at=datetime.now(UTC)))
        entry = WatchlistEntry(kid_id=kid.id, pattern="soccer")
        s.add(entry)
        await s.flush()
        return eng, kid.id, off.id, entry.id


async def _render(eng: Any, alert_type: AlertType):
    async with session_scope(eng) as s:
        alert = (await s.execute(select(Alert).where(Alert.type == alert_type.value))).scalar_one()
        return await render_email(s, alert_type, alert, [alert])


async def test_enqueued_new_match_renders(tmp_path: Any) -> None:
    eng, kid_id, off_id, _ = await _seed(tmp_path)
    async with session_scope(eng) as s:
        await enqueue_new_match(s, kid_id=kid_id, offering_id=off_id, score=0.9, reasons={})
    rendered = await _render(eng, AlertType.new_match)
    assert "Soccer Camp" in rendered.body_plain
    assert rendered.url == "https://p.example.com/r/10"
    await eng.dispose()


async def test_enqueued_watchlist_hit_renders_with_its_hit_pattern(tmp_path: Any) -> None:
    eng, kid_id, off_id, entry_id = await _seed(tmp_path)
    async with session_scope(eng) as s:
        # The reasons shape matcher._reasons_payload records at hit time.
        reasons = {"watchlist_hit": {"entry_id": entry_id, "pattern": "soccer"}}
        await enqueue_watchlist_hit(
            s, kid_id=kid_id, offering_id=off_id, watchlist_entry_id=entry_id, reasons=reasons
        )
    rendered = await _render(eng, AlertType.watchlist_hit)
    assert "Soccer Camp" in rendered.body_plain
    assert '"soccer"' in rendered.body_plain
    await eng.dispose()


async def test_enqueued_reg_opens_now_renders(tmp_path: Any) -> None:
    eng, kid_id, off_id, _ = await _seed(tmp_path)
    async with session_scope(eng) as s:
        await enqueue_registration_countdowns(s, offering_id=off_id, kid_id=kid_id)
    for t in (AlertType.reg_opens_24h, AlertType.reg_opens_1h, AlertType.reg_opens_now):
        rendered = await _render(eng, t)
        assert "Soccer Camp" in rendered.body_plain
    await eng.dispose()


# --- Inbox summaries and digest failures from real writers (#641) -----------


async def _summaries(eng: Any) -> dict[str, str]:
    async with session_scope(eng) as s:
        alerts = (await s.execute(select(Alert))).scalars().all()
        names = await load_alert_names(s, alerts)
        return {
            a.type: summarize_alert(
                a.type,
                kid_name="Ada",
                payload=a.payload_json,
                offering_name=names[a.id][0],
                site_name=names[a.id][1],
            )
            for a in alerts
        }


async def test_enqueued_alerts_summarize_with_offering_and_site_names(tmp_path: Any) -> None:
    """The inbox read `offering_name` / `site_name` from payloads these enqueuers
    never write, so it showed "an activity · a site"."""
    eng, kid_id, off_id, entry_id = await _seed(tmp_path)
    async with session_scope(eng) as s:
        site_id = (await s.execute(select(Offering.site_id))).scalar_one()
        await enqueue_new_match(s, kid_id=kid_id, offering_id=off_id, score=0.9, reasons={})
        await enqueue_watchlist_hit(
            s, kid_id=kid_id, offering_id=off_id, watchlist_entry_id=entry_id, reasons={}
        )
        await enqueue_crawl_failed(s, site_id=site_id, consecutive_failures=3, last_error="boom")
        await enqueue_push_cap(s, kid_id=kid_id, hour_bucket="2026-04-22T15", suppressed_count=4)
    out = await _summaries(eng)
    assert out[AlertType.new_match.value] == "New match for Ada — Soccer Camp · Park"
    assert out[AlertType.watchlist_hit.value] == "Watchlist hit for Ada — Soccer Camp · Park"
    assert out[AlertType.crawl_failed.value] == "Crawl failed — Park"
    assert "4 held back" in out[AlertType.push_cap.value]
    await eng.dispose()


async def test_digest_lists_delivery_failures_but_not_deliberate_skips(tmp_path: Any) -> None:
    """Failures are recorded by send_alert_group itself, not by hand-built payloads.
    The digest read `_last_error`, which nothing writes, and listed every skipped
    row, so a digest-only no_matches_for_kid showed as a failed delivery."""
    eng, kid_id, off_id, _ = await _seed(tmp_path)
    email = FakeNotifier(name="email")
    email.queue_permanent_failure("550 mailbox unavailable")
    async with session_scope(eng) as s:
        await seed_default_routing(s)
        await enqueue_new_match(s, kid_id=kid_id, offering_id=off_id, score=0.9, reasons={})
        await enqueue_no_matches_for_kid(s, kid_id=kid_id, days_since_created=8)
        due = (await s.execute(select(Alert))).scalars().all()
        for group in coalesce(list(due), window_s=600):
            await send_alert_group(
                s, group, {"email": email}, Settings(anthropic_api_key="x"), None
            )

    now = datetime.now(UTC)
    async with session_scope(eng) as s:
        assert all(a.skipped for a in (await s.execute(select(Alert))).scalars().all())
        kid = await s.get(Kid, kid_id)
        assert kid is not None
        payload = await gather_digest_payload(
            s,
            kid,
            window_start=now - timedelta(days=1),
            window_end=now + timedelta(minutes=1),
            alert_no_matches_kid_days=7,
            now=now,
        )
    assert payload.delivery_failures == [
        {
            "alert_type": AlertType.new_match.value,
            "detail": "email: 550 mailbox unavailable",
            "scheduled_for": payload.delivery_failures[0]["scheduled_for"],
        }
    ]
    await eng.dispose()
