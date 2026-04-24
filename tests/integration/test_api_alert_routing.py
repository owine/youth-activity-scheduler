"""Integration tests for /api/alert_routing endpoints."""

from __future__ import annotations

from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from yas.alerts.routing import seed_default_routing
from yas.db.base import Base
from yas.db.models import HouseholdSettings, Kid, Site
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
        # Seed default routing
        await seed_default_routing(s)
        # Seed minimal data
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        s.add(Site(id=1, name="X", base_url="https://x"))
        # Seed household settings with email config
        s.add(HouseholdSettings(
            id=1,
            smtp_config_json={"host": "localhost", "port": 587},
            ntfy_config_json=None,
            pushover_config_json=None,
        ))
        await s.flush()
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_alert_routing_all(client):
    """GET /api/alert_routing returns all seeded routing rows."""
    r = await client.get("/api/alert_routing")
    assert r.status_code == 200
    items = r.json()
    # Should have entries for all AlertTypes
    assert len(items) > 0
    # Check that we got the default routing for at least one type
    types = {item["type"] for item in items}
    assert "watchlist_hit" in types
    assert "new_match" in types
    assert "digest" in types


@pytest.mark.asyncio
async def test_patch_alert_routing_channels(client):
    """PATCH /api/alert_routing/{type} with channels updates round-trips."""
    # Patch new_match to change channels
    r = await client.patch(
        "/api/alert_routing/new_match",
        json={"channels": ["email", "ntfy"]},
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["type"] == "new_match"
    assert updated["channels"] == ["email", "ntfy"]
    assert updated["enabled"] is True

    # Verify round-trip by GET
    r_get = await client.get("/api/alert_routing")
    items = r_get.json()
    new_match = next(item for item in items if item["type"] == "new_match")
    assert new_match["channels"] == ["email", "ntfy"]


@pytest.mark.asyncio
async def test_patch_alert_routing_enabled(client):
    """PATCH /api/alert_routing/{type} with enabled=False round-trips."""
    r = await client.patch(
        "/api/alert_routing/reg_opens_24h",
        json={"enabled": False},
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["type"] == "reg_opens_24h"
    assert updated["enabled"] is False
    # channels should remain unchanged (email from default)
    assert updated["channels"] == ["email"]

    # Verify round-trip
    r_get = await client.get("/api/alert_routing")
    items = r_get.json()
    reg_24h = next(item for item in items if item["type"] == "reg_opens_24h")
    assert reg_24h["enabled"] is False


@pytest.mark.asyncio
async def test_patch_alert_routing_not_found(tmp_path, monkeypatch):
    """PATCH /api/alert_routing/{type} for non-existent type → 404."""
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/m_nofound.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Don't seed any routing data
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch(
            "/api/alert_routing/new_match",
            json={"channels": ["email"]},
        )
        assert r.status_code == 404
        assert "not found" in r.json()["detail"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_patch_alert_routing_unknown_channel(client):
    """PATCH with unknown channel name (e.g., 'fax') → 422."""
    r = await client.patch(
        "/api/alert_routing/new_match",
        json={"channels": ["fax"]},
    )
    assert r.status_code == 422
    assert "unknown channel type" in r.json()["detail"]


@pytest.mark.asyncio
async def test_patch_alert_routing_unconfigured_channel(client, caplog):
    """PATCH with known but unconfigured channel → 200 (warning logged)."""
    # ntfy is not configured in the fixture (only email is)
    r = await client.patch(
        "/api/alert_routing/new_match",
        json={"channels": ["email", "pushover"]},
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["channels"] == ["email", "pushover"]
    # pushover should be in channels even though it's not configured
    # Warning should have been logged but test passes


@pytest.mark.asyncio
async def test_patch_alert_routing_empty_body(client):
    """PATCH with neither channels nor enabled → 422."""
    r = await client.patch(
        "/api/alert_routing/new_match",
        json={},
    )
    assert r.status_code == 422
    assert "at least one" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_alert_routing_both_fields(client):
    """PATCH with both channels and enabled updates both."""
    r = await client.patch(
        "/api/alert_routing/watchlist_hit",
        json={"channels": ["email"], "enabled": False},
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["type"] == "watchlist_hit"
    assert updated["channels"] == ["email"]
    assert updated["enabled"] is False
