"""Integration tests for /api/digest/preview endpoint."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import HouseholdSettings, Kid, Match, Offering, Page, Site
from yas.db.models._types import ProgramType
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        # Create kids
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        s.add(Kid(id=2, name="Alex", dob=date(2019, 5, 1)))
        # Create site and page
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        # Create offering
        s.add(
            Offering(
                id=1,
                site_id=1,
                page_id=1,
                name="Sat Soccer",
                normalized_name="sat soccer",
                program_type=ProgramType.soccer.value,
                start_date=date(2026, 5, 1),
                days_of_week=["sat"],
                time_start=time(9, 0),
                time_end=time(10, 0),
            )
        )
        await s.flush()
        # Create a match within the past 24h
        now = datetime.now(UTC)
        s.add(
            Match(
                kid_id=1,
                offering_id=1,
                score=0.82,
                reasons={"gates": {}, "score_breakdown": {}},
                computed_at=now,
            )
        )
        # Create household settings
        s.add(
            HouseholdSettings(
                id=1,
                smtp_config_json={"host": "localhost", "port": 587},
            )
        )
        await s.flush()
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_digest_preview_existing_kid(client):
    """GET /api/digest/preview?kid_id=1 for existing kid returns 200 with content."""
    r = await client.get("/api/digest/preview?kid_id=1")
    assert r.status_code == 200
    body = r.json()

    # Check all fields are present
    assert "subject" in body
    assert "body_plain" in body
    assert "body_html" in body

    # Check that fields are non-empty
    assert len(body["subject"]) > 0
    assert len(body["body_plain"]) > 0
    assert len(body["body_html"]) > 0

    # Check subject contains kid name
    assert "Sam" in body["subject"]


@pytest.mark.asyncio
async def test_digest_preview_missing_kid(client):
    """GET /api/digest/preview?kid_id=999 for missing kid → 404."""
    r = await client.get("/api/digest/preview?kid_id=999")
    assert r.status_code == 404
    assert "kid 999 not found" in r.json()["detail"]


@pytest.mark.asyncio
async def test_digest_preview_shape(client):
    """GET /api/digest/preview returns correct shape (subject, body_plain, body_html)."""
    r = await client.get("/api/digest/preview?kid_id=1")
    assert r.status_code == 200
    body = r.json()

    # Validate shape
    assert isinstance(body["subject"], str)
    assert isinstance(body["body_plain"], str)
    assert isinstance(body["body_html"], str)

    # Validate subject format
    assert "Daily digest" in body["subject"]
    assert "Sam" in body["subject"]

    # Validate that HTML contains expected tags (basic check)
    assert "<" in body["body_html"]
    assert ">" in body["body_html"]
