"""Alerts written by the real enqueuers must render.

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

from yas.alerts.enqueuer import (
    enqueue_new_match,
    enqueue_registration_countdowns,
    enqueue_watchlist_hit,
)
from yas.db.base import Base
from yas.db.models import Alert, Kid, Match, Offering, Page, Site
from yas.db.models._types import AlertType, PageKind
from yas.db.models.watchlist import WatchlistEntry
from yas.db.session import create_engine_for, session_scope
from yas.email import render_email


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


async def test_enqueued_watchlist_hit_renders_with_its_entry_pattern(tmp_path: Any) -> None:
    eng, kid_id, off_id, entry_id = await _seed(tmp_path)
    async with session_scope(eng) as s:
        await enqueue_watchlist_hit(
            s, kid_id=kid_id, offering_id=off_id, watchlist_entry_id=entry_id, reasons={}
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
