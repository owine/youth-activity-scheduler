"""Seed helpers that drive BOTH the per-kind builder unit tests AND the golden bootstrap.

A scenario seeds an in-memory DB and returns ``(lead_alert, member_alerts)`` -- exactly
what render_email expects. Keeping the seed code shared means the golden file and the
unit test cannot drift from each other.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Alert, Kid, Match, Offering, Page, Site
from yas.db.models._types import AlertType, PageKind

# Fixed timestamp -- goldens must be deterministic.
GOLDEN_NOW = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)


async def seed_new_match(session: AsyncSession) -> tuple[Alert, list[Alert]]:
    """Seed a single-offering new_match scenario. Returns (lead, [lead])."""
    site = Site(name="Park District", base_url="https://p.example.com", active=True)
    session.add(site)
    await session.flush()
    page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule)
    session.add(page)
    await session.flush()
    kid = Kid(name="Ada", dob=date(2019, 5, 1), created_at=GOLDEN_NOW - timedelta(days=30))
    session.add(kid)
    await session.flush()
    off = Offering(
        site_id=site.id,
        page_id=page.id,
        name="Soccer Camp",
        normalized_name="soccer camp",
        start_date=date(2026, 6, 1),
        price_cents=15000,
        registration_url="https://p.example.com/r/10",
    )
    session.add(off)
    await session.flush()
    m = Match(kid_id=kid.id, offering_id=off.id, score=0.91, computed_at=GOLDEN_NOW)
    session.add(m)
    await session.flush()
    a = Alert(
        type=AlertType.new_match.value,
        kid_id=kid.id,
        channels=[],
        scheduled_for=GOLDEN_NOW,
        dedup_key="new_match-golden",
        payload_json={"offering_id": off.id},
        skipped=False,
    )
    session.add(a)
    await session.flush()
    return a, [a]


async def seed_reg_opens_now(session: AsyncSession) -> tuple[Alert, list[Alert]]:
    """Seed a single-offering reg_opens_now scenario. Returns (lead, [lead])."""
    site = Site(name="Park District", base_url="https://p.example.com", active=True)
    session.add(site)
    await session.flush()
    page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule)
    session.add(page)
    await session.flush()
    kid = Kid(name="Bo", dob=date(2019, 5, 1), created_at=GOLDEN_NOW - timedelta(days=30))
    session.add(kid)
    await session.flush()
    off = Offering(
        site_id=site.id,
        page_id=page.id,
        name="Tennis Camp",
        normalized_name="tennis camp",
        start_date=date(2026, 7, 1),
        price_cents=12000,
        registration_url="https://p.example.com/r/20",
        registration_opens_at=GOLDEN_NOW,
    )
    session.add(off)
    await session.flush()
    m = Match(kid_id=kid.id, offering_id=off.id, score=0.85, computed_at=GOLDEN_NOW)
    session.add(m)
    await session.flush()
    a = Alert(
        type=AlertType.reg_opens_now.value,
        kid_id=kid.id,
        offering_id=off.id,
        channels=[],
        scheduled_for=GOLDEN_NOW,
        dedup_key="reg_opens_now-golden",
        payload_json={"offering_id": off.id},
        skipped=False,
    )
    session.add(a)
    await session.flush()
    return a, [a]
