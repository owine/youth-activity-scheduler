"""Tests for POST /api/notifiers/{channel}/test."""
from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.fakes.geocoder import FakeGeocoder
from yas.alerts.channels.base import SendResult
from yas.db.base import Base
from yas.db.models import HouseholdSettings
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/n.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=FakeGeocoder())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, engine
    await engine.dispose()


async def _seed_household(engine: AsyncEngine, **fields: Any) -> None:
    async with session_scope(engine) as s:
        hh = HouseholdSettings(id=1, **fields)
        s.add(hh)


@pytest.mark.asyncio
async def test_unknown_channel_returns_404(client):
    c, _engine = client
    r = await c.post("/api/notifiers/bogus/test")
    assert r.status_code == 404
    assert "unknown channel" in r.json()["detail"]


@pytest.mark.asyncio
async def test_unconfigured_channel_returns_503(client):
    c, engine = client
    await _seed_household(engine)  # all *_config_json default null
    r = await c.post("/api/notifiers/email/test")
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_send_returns_ok_true_on_success(client, monkeypatch):
    """Mock the channel send to return ok=True."""
    c, engine = client
    await _seed_household(
        engine,
        ntfy_config_json={"base_url": "https://ntfy.sh", "topic": "test"},
    )
    from yas.alerts.channels import ntfy as ntfy_mod

    async def fake_send(self: Any, msg: Any) -> SendResult:
        return SendResult(ok=True, transient_failure=False, detail="published")

    monkeypatch.setattr(ntfy_mod.NtfyChannel, "send", fake_send)

    r = await c.post("/api/notifiers/ntfy/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["detail"] == "published"


@pytest.mark.asyncio
async def test_channel_init_failure_surfaces_as_ok_false(client, monkeypatch):
    """Pushover ctor raises ValueError if user_key_env is missing — surface as ok=false."""
    c, engine = client
    await _seed_household(
        engine,
        pushover_config_json={
            "user_key_env": "YAS_PUSHOVER_USER_KEY_DOES_NOT_EXIST",
            "app_token_env": "YAS_PUSHOVER_APP_TOKEN_DOES_NOT_EXIST",
        },
    )
    monkeypatch.delenv("YAS_PUSHOVER_USER_KEY_DOES_NOT_EXIST", raising=False)
    monkeypatch.delenv("YAS_PUSHOVER_APP_TOKEN_DOES_NOT_EXIST", raising=False)

    r = await c.post("/api/notifiers/pushover/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "channel init failed" in body["detail"]


@pytest.mark.asyncio
async def test_channel_send_failure_surfaces_as_ok_false(client, monkeypatch):
    """If the channel constructs but send returns ok=False, propagate."""
    c, engine = client
    await _seed_household(
        engine,
        ntfy_config_json={"base_url": "https://ntfy.sh", "topic": "test"},
    )
    from yas.alerts.channels import ntfy as ntfy_mod

    async def fake_send(self: Any, msg: Any) -> SendResult:
        return SendResult(ok=False, transient_failure=True, detail="connection refused")

    monkeypatch.setattr(ntfy_mod.NtfyChannel, "send", fake_send)

    r = await c.post("/api/notifiers/ntfy/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["detail"] == "connection refused"
