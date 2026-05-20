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


async def seed_reg_opens_1h(session: AsyncSession) -> tuple[Alert, list[Alert]]:
    """Seed a single-offering reg_opens_1h scenario.

    ``Offering.registration_opens_at == GOLDEN_NOW`` and the alert is
    scheduled at ``GOLDEN_NOW - 1h`` so the 1h offset is exact. The builder's
    ``now`` kwarg is not exercised here (the registry calls it with no
    kwargs); the templates render ``opens_at`` directly, so the golden's
    determinism comes from ``registration_opens_at``.
    """
    site = Site(name="Park District", base_url="https://p.example.com", active=True)
    session.add(site)
    await session.flush()
    page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule)
    session.add(page)
    await session.flush()
    kid = Kid(name="Cy", dob=date(2019, 5, 1), created_at=GOLDEN_NOW - timedelta(days=30))
    session.add(kid)
    await session.flush()
    off = Offering(
        site_id=site.id,
        page_id=page.id,
        name="Swim Camp",
        normalized_name="swim camp",
        start_date=date(2026, 8, 1),
        price_cents=18000,
        registration_url="https://p.example.com/r/30",
        registration_opens_at=GOLDEN_NOW,
    )
    session.add(off)
    await session.flush()
    m = Match(kid_id=kid.id, offering_id=off.id, score=0.78, computed_at=GOLDEN_NOW)
    session.add(m)
    await session.flush()
    a = Alert(
        type=AlertType.reg_opens_1h.value,
        kid_id=kid.id,
        offering_id=off.id,
        channels=[],
        scheduled_for=GOLDEN_NOW - timedelta(hours=1),
        dedup_key="reg_opens_1h-golden",
        payload_json={"offering_id": off.id},
        skipped=False,
    )
    session.add(a)
    await session.flush()
    return a, [a]


async def seed_watchlist_hit(session: AsyncSession) -> tuple[Alert, list[Alert]]:
    """Seed a single-offering watchlist_hit scenario with a watchlist label."""
    site = Site(name="Park District", base_url="https://p.example.com", active=True)
    session.add(site)
    await session.flush()
    page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule)
    session.add(page)
    await session.flush()
    kid = Kid(name="Eli", dob=date(2019, 5, 1), created_at=GOLDEN_NOW - timedelta(days=30))
    session.add(kid)
    await session.flush()
    off = Offering(
        site_id=site.id,
        page_id=page.id,
        name="Robotics Camp",
        normalized_name="robotics camp",
        start_date=date(2026, 7, 15),
        price_cents=22000,
        registration_url="https://p.example.com/r/50",
    )
    session.add(off)
    await session.flush()
    m = Match(kid_id=kid.id, offering_id=off.id, score=0.88, computed_at=GOLDEN_NOW)
    session.add(m)
    await session.flush()
    a = Alert(
        type=AlertType.watchlist_hit.value,
        kid_id=kid.id,
        channels=[],
        scheduled_for=GOLDEN_NOW,
        dedup_key="watchlist_hit-golden",
        payload_json={"offering_id": off.id, "watchlist_label": "robotics"},
        skipped=False,
    )
    session.add(a)
    await session.flush()
    return a, [a]


async def seed_reg_opens_24h(session: AsyncSession) -> tuple[Alert, list[Alert]]:
    """Seed a single-offering reg_opens_24h scenario.

    ``Offering.registration_opens_at == GOLDEN_NOW + 24h`` and the alert is
    scheduled at ``GOLDEN_NOW`` so the 24h offset is exact.
    """
    site = Site(name="Park District", base_url="https://p.example.com", active=True)
    session.add(site)
    await session.flush()
    page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule)
    session.add(page)
    await session.flush()
    kid = Kid(name="Dee", dob=date(2019, 5, 1), created_at=GOLDEN_NOW - timedelta(days=30))
    session.add(kid)
    await session.flush()
    off = Offering(
        site_id=site.id,
        page_id=page.id,
        name="Art Class",
        normalized_name="art class",
        start_date=date(2026, 9, 1),
        price_cents=9000,
        registration_url="https://p.example.com/r/40",
        registration_opens_at=GOLDEN_NOW + timedelta(hours=24),
    )
    session.add(off)
    await session.flush()
    m = Match(kid_id=kid.id, offering_id=off.id, score=0.72, computed_at=GOLDEN_NOW)
    session.add(m)
    await session.flush()
    a = Alert(
        type=AlertType.reg_opens_24h.value,
        kid_id=kid.id,
        offering_id=off.id,
        channels=[],
        scheduled_for=GOLDEN_NOW,
        dedup_key="reg_opens_24h-golden",
        payload_json={"offering_id": off.id},
        skipped=False,
    )
    session.add(a)
    await session.flush()
    return a, [a]
