"""Per-kind builder tests: real DB joins, payload-shape assertions, failure modes."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from yas.db.base import Base
from yas.db.models import Alert, Kid, Match, Offering, Page, Site
from yas.db.models._types import AlertType, PageKind
from yas.db.session import create_engine_for, session_scope
from yas.email import EmailRenderError
from yas.email.builders import build_new_match
from yas.email.payloads import NewMatchPayload

NOW = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)


async def _engine(tmp_path: Any):
    eng = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/b.db")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    return eng


@pytest.mark.asyncio
async def test_build_new_match_single(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        site = Site(name="Park", base_url="https://p.example.com", active=True)
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule)
        s.add(page)
        await s.flush()
        kid = Kid(name="Ada", dob=date(2019, 5, 1), created_at=NOW - timedelta(days=30))
        s.add(kid)
        await s.flush()
        off = Offering(
            site_id=site.id,
            page_id=page.id,
            name="Soccer Camp",
            normalized_name="soccer camp",
            start_date=date(2026, 6, 1),
            price_cents=15000,
            registration_url="https://p.example.com/r/10",
        )
        s.add(off)
        await s.flush()
        m = Match(kid_id=kid.id, offering_id=off.id, score=0.9, computed_at=NOW)
        s.add(m)
        await s.flush()
        a = Alert(
            type=AlertType.new_match.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="x",
            payload_json={"offering_id": off.id},
            skipped=False,
        )
        s.add(a)
        await s.flush()

        payload = await build_new_match(s, a, [a])

    assert isinstance(payload, NewMatchPayload)
    assert payload.kid_name == "Ada"
    assert len(payload.matches) == 1
    assert payload.matches[0]["offering_name"] == "Soccer Camp"
    assert payload.matches[0]["price_cents"] == 15000
    assert payload.matches[0]["registration_url"] == "https://p.example.com/r/10"


@pytest.mark.asyncio
async def test_build_new_match_coalesced(tmp_path: Any) -> None:
    """Two member alerts -> both offerings in payload.matches, ordered by score desc."""
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        site = Site(name="Park", base_url="https://p.example.com", active=True)
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule)
        s.add(page)
        await s.flush()
        kid = Kid(name="Ada", dob=date(2019, 5, 1), created_at=NOW - timedelta(days=30))
        s.add(kid)
        await s.flush()
        off1 = Offering(
            site_id=site.id,
            page_id=page.id,
            name="Soccer Camp",
            normalized_name="soccer camp",
            start_date=date(2026, 6, 1),
            price_cents=15000,
            registration_url="https://p.example.com/r/10",
        )
        s.add(off1)
        await s.flush()
        off2 = Offering(
            site_id=site.id,
            page_id=page.id,
            name="Tennis Camp",
            normalized_name="tennis camp",
            start_date=date(2026, 6, 15),
            price_cents=12000,
            registration_url="https://p.example.com/r/20",
        )
        s.add(off2)
        await s.flush()
        m1 = Match(kid_id=kid.id, offering_id=off1.id, score=0.7, computed_at=NOW)
        s.add(m1)
        m2 = Match(kid_id=kid.id, offering_id=off2.id, score=0.9, computed_at=NOW)
        s.add(m2)
        await s.flush()
        a1 = Alert(
            type=AlertType.new_match.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="x1",
            payload_json={"offering_id": off1.id},
            skipped=False,
        )
        a2 = Alert(
            type=AlertType.new_match.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="x2",
            payload_json={"offering_id": off2.id},
            skipped=False,
        )
        s.add(a1)
        s.add(a2)
        await s.flush()

        payload = await build_new_match(s, a1, [a1, a2])

    assert len(payload.matches) == 2
    # Ordered by score desc
    assert payload.matches[0]["offering_name"] == "Tennis Camp"
    assert payload.matches[1]["offering_name"] == "Soccer Camp"


@pytest.mark.asyncio
async def test_build_new_match_missing_offering(tmp_path: Any) -> None:
    """payload_json points at a non-existent offering -> EmailRenderError."""
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        kid = Kid(name="Ada", dob=date(2019, 5, 1), created_at=NOW)
        s.add(kid)
        await s.flush()
        a = Alert(
            type=AlertType.new_match.value,
            kid_id=kid.id,
            channels=[],
            scheduled_for=NOW,
            dedup_key="x",
            payload_json={"offering_id": 999999},
            skipped=False,
        )
        s.add(a)
        await s.flush()
        with pytest.raises(EmailRenderError):
            await build_new_match(s, a, [a])


@pytest.mark.asyncio
async def test_build_new_match_no_kid(tmp_path: Any) -> None:
    """Lead alert without kid_id -> EmailRenderError."""
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        a = Alert(
            type=AlertType.new_match.value,
            kid_id=None,
            channels=[],
            scheduled_for=NOW,
            dedup_key="x",
            payload_json={"offering_id": 1},
            skipped=False,
        )
        s.add(a)
        await s.flush()
        with pytest.raises(EmailRenderError):
            await build_new_match(s, a, [a])
