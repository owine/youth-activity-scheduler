"""Integration tests for POST /api/alerts/{id}/close and /reopen."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import Alert, Kid
from yas.db.models._types import AlertType
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/c.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        await s.flush()
        s.add(
            Alert(
                id=1,
                type=AlertType.watchlist_hit,
                kid_id=1,
                channels=["email"],
                scheduled_for=datetime.now(UTC) - timedelta(hours=1),
                sent_at=None,
                skipped=False,
                dedup_key="open-1",
                payload_json={"msg": "open"},
            )
        )
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_close_alert_with_acknowledged_sets_fields(client):
    c, _ = client
    r = await c.post("/api/alerts/1/close", json={"reason": "acknowledged"})
    assert r.status_code == 200
    body = r.json()
    assert body["close_reason"] == "acknowledged"
    assert body["closed_at"] is not None


@pytest.mark.asyncio
async def test_close_alert_with_dismissed_sets_fields(client):
    c, _ = client
    r = await c.post("/api/alerts/1/close", json={"reason": "dismissed"})
    assert r.status_code == 200
    body = r.json()
    assert body["close_reason"] == "dismissed"
    assert body["closed_at"] is not None


@pytest.mark.asyncio
async def test_closing_already_closed_with_same_reason_is_idempotent(client):
    c, _ = client
    first = await c.post("/api/alerts/1/close", json={"reason": "acknowledged"})
    closed_at_first = first.json()["closed_at"]

    second = await c.post("/api/alerts/1/close", json={"reason": "acknowledged"})
    assert second.status_code == 200
    assert second.json()["close_reason"] == "acknowledged"
    # closed_at MUST NOT advance on a same-reason re-close.
    assert second.json()["closed_at"] == closed_at_first


@pytest.mark.asyncio
async def test_closing_already_closed_with_different_reason_updates_reason(client):
    c, _ = client
    first = await c.post("/api/alerts/1/close", json={"reason": "acknowledged"})
    closed_at_first = first.json()["closed_at"]

    second = await c.post("/api/alerts/1/close", json={"reason": "dismissed"})
    assert second.status_code == 200
    assert second.json()["close_reason"] == "dismissed"
    # Last-write-wins on reason; closed_at does NOT advance.
    assert second.json()["closed_at"] == closed_at_first


@pytest.mark.asyncio
async def test_close_returns_404_for_unknown_id(client):
    c, _ = client
    r = await c.post("/api/alerts/9999/close", json={"reason": "acknowledged"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_close_returns_422_when_reason_missing(client):
    c, _ = client
    r = await c.post("/api/alerts/1/close", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_close_returns_422_for_invalid_reason(client):
    c, _ = client
    r = await c.post("/api/alerts/1/close", json={"reason": "snoozed"})
    assert r.status_code == 422
