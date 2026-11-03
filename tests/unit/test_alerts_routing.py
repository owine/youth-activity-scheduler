import pytest
from sqlalchemy import select

from yas.alerts.routing import (
    DEFAULT_ROUTING,
    get_routing,
    seed_default_routing,
)
from yas.db.models import AlertRouting
from yas.db.models._types import AlertType
from yas.db.session import session_scope


@pytest.mark.asyncio
async def test_seed_populates_all_alert_types(engine):
    async with session_scope(engine) as s:
        await seed_default_routing(s)
    async with session_scope(engine) as s:
        rows = (await s.execute(select(AlertRouting))).scalars().all()
        types = {r.type for r in rows}
        assert types == {t.value for t in AlertType}


@pytest.mark.asyncio
async def test_seed_idempotent(engine):
    async with session_scope(engine) as s:
        await seed_default_routing(s)
    async with session_scope(engine) as s:
        await seed_default_routing(s)  # second call is a no-op
    async with session_scope(engine) as s:
        rows = (await s.execute(select(AlertRouting))).scalars().all()
        assert len(rows) == len(AlertType)


@pytest.mark.asyncio
async def test_get_routing_returns_channels_and_enabled(engine):
    async with session_scope(engine) as s:
        await seed_default_routing(s)
    async with session_scope(engine) as s:
        channels, enabled = await get_routing(s, AlertType.watchlist_hit)
    assert "push" in channels and "email" in channels
    assert enabled is True


@pytest.mark.asyncio
async def test_get_routing_respects_disabled_flag(engine):
    async with session_scope(engine) as s:
        await seed_default_routing(s)
        row = (
            await s.execute(
                select(AlertRouting).where(AlertRouting.type == AlertType.new_match.value)
            )
        ).scalar_one()
        row.enabled = False
    async with session_scope(engine) as s:
        _channels, enabled = await get_routing(s, AlertType.new_match)
    assert enabled is False


def test_default_routing_covers_all_alert_types():
    for t in AlertType:
        assert t.value in DEFAULT_ROUTING


def test_default_routing_digest_only_types_have_empty_channels():
    # schedule_posted, site_stagnant, no_matches_for_kid roll into digest only
    for t in ("schedule_posted", "site_stagnant", "no_matches_for_kid"):
        assert DEFAULT_ROUTING[t] == []


def test_default_routing_reg_opens_now_has_push_and_email():
    assert "push" in DEFAULT_ROUTING["reg_opens_now"]
    assert "email" in DEFAULT_ROUTING["reg_opens_now"]


@pytest.mark.asyncio
async def test_get_routing_falls_back_when_row_missing(engine):
    # do NOT seed
    async with session_scope(engine) as s:
        channels, enabled = await get_routing(s, AlertType.watchlist_hit)
    assert channels == ["push", "email"]
    assert enabled is True
