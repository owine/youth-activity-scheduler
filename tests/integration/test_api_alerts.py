"""Integration tests for /api/alerts endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import Alert, Kid, Site
from yas.db.models._types import AlertType
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
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        s.add(Kid(id=2, name="Alex", dob=date(2019, 5, 1)))
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        # Seed alerts with various statuses
        now = datetime.now(UTC)
        s.add(
            Alert(
                id=1,
                type=AlertType.new_match,
                kid_id=1,
                offering_id=None,
                site_id=1,
                channels=["push"],
                scheduled_for=now - timedelta(days=1),
                sent_at=now - timedelta(hours=1),
                skipped=False,
                dedup_key="key1",
                payload_json={"msg": "test1"},
            )
        )
        s.add(
            Alert(
                id=2,
                type=AlertType.watchlist_hit,
                kid_id=1,
                offering_id=None,
                site_id=None,
                channels=["email"],
                scheduled_for=now - timedelta(hours=1),
                sent_at=None,
                skipped=False,
                dedup_key="key2",
                payload_json={"msg": "test2"},
            )
        )
        s.add(
            Alert(
                id=3,
                type=AlertType.reg_opens_24h,
                kid_id=2,
                offering_id=None,
                site_id=1,
                channels=["push", "email"],
                scheduled_for=now,
                sent_at=None,
                skipped=True,
                dedup_key="key3",
                payload_json={"msg": "test3"},
            )
        )
        s.add(
            Alert(
                id=4,
                type=AlertType.digest,
                kid_id=2,
                offering_id=None,
                site_id=None,
                channels=["email"],
                scheduled_for=now + timedelta(days=1),
                sent_at=None,
                skipped=False,
                dedup_key="key4",
                payload_json={"msg": "test4"},
            )
        )
        await s.flush()
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_alerts_empty(tmp_path, monkeypatch):
    """GET /api/alerts on empty alerts table returns 200 with empty list."""
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/empty.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        # Create dummy kid and site for FK constraints if needed
        s.add(Kid(id=1, name="Dummy", dob=date(2019, 1, 1)))
        s.add(Site(id=1, name="Dummy", base_url="https://dummy"))
        await s.flush()
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/alerts")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["limit"] == 25
        assert body["offset"] == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_alerts_all(client):
    """GET /api/alerts returns all alerts with pagination info."""
    r = await client.get("/api/alerts")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert len(body["items"]) == 4
    assert body["limit"] == 25
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_get_alerts_filter_by_kid_id(client):
    """GET /api/alerts?kid_id=1 filters by kid."""
    r = await client.get("/api/alerts?kid_id=1")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert {item["kid_id"] for item in body["items"]} == {1}


@pytest.mark.asyncio
async def test_get_alerts_filter_by_status_pending(client):
    """GET /api/alerts?status=pending returns only pending alerts."""
    r = await client.get("/api/alerts?status=pending")
    assert r.status_code == 200
    body = r.json()
    # pending: sent_at IS NULL AND skipped=False
    # That's alert id=2 and id=4
    assert body["total"] == 2
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert item["sent_at"] is None
        assert item["skipped"] is False


@pytest.mark.asyncio
async def test_get_alerts_filter_by_status_sent(client):
    """GET /api/alerts?status=sent returns only sent alerts."""
    r = await client.get("/api/alerts?status=sent")
    assert r.status_code == 200
    body = r.json()
    # sent: sent_at IS NOT NULL
    # That's alert id=1
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == 1
    assert body["items"][0]["sent_at"] is not None


@pytest.mark.asyncio
async def test_get_alerts_filter_by_status_skipped(client):
    """GET /api/alerts?status=skipped returns only skipped alerts."""
    r = await client.get("/api/alerts?status=skipped")
    assert r.status_code == 200
    body = r.json()
    # skipped: skipped=True
    # That's alert id=3
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == 3
    assert body["items"][0]["skipped"] is True


@pytest.mark.asyncio
async def test_get_alerts_filter_by_type(client):
    """GET /api/alerts?type=new_match filters by alert type."""
    r = await client.get("/api/alerts?type=new_match")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["type"] == "new_match"


@pytest.mark.asyncio
async def test_get_alerts_filter_by_since(client):
    """GET /api/alerts?since=<datetime> filters by scheduled_for >= since (excludes earlier alerts)."""
    now = datetime.now(UTC)
    # Use a cutoff point that falls between alert 1 (1 day ago) and earlier
    # The cutoff is 1.5 days ago, so only alerts from the last 1.5 days are included
    # Alert 1 is 1 day ago (included), alerts 2,3,4 are within 1.5 days (included)
    # But we need to test that earlier alerts ARE excluded.
    # Since our fixture has alert 1 at 1 day ago, let's use a cutoff between
    # the beginning of time and 1 day ago... Actually, simpler: use 0.5 days ago
    # This includes: alert 2 (1 hour ago), alert 3 (now), alert 4 (1 day future)
    # This excludes: alert 1 (1 day ago < 0.5 days ago)
    half_day_ago = (now - timedelta(hours=12)).isoformat()
    encoded_since = half_day_ago.replace("+", "%2B")
    r = await client.get(f"/api/alerts?since={encoded_since}")
    assert r.status_code == 200
    body = r.json()
    # Should include alerts 2, 3, 4 but exclude alert 1 (which is 1 day ago)
    assert body["total"] == 3
    # Verify that alert 1 is not in the results
    alert_ids = {item["id"] for item in body["items"]}
    assert 1 not in alert_ids
    assert {2, 3, 4} == alert_ids


@pytest.mark.asyncio
async def test_get_alerts_filter_by_until(client):
    """GET /api/alerts?until=<datetime> filters by scheduled_for <= until (excludes later alerts)."""
    now = datetime.now(UTC)
    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    # URL-encode the + sign in the ISO format datetime
    encoded_until = one_hour_ago.replace("+", "%2B")
    r = await client.get(f"/api/alerts?until={encoded_until}")
    assert r.status_code == 200
    body = r.json()
    # Alerts 1 (1 day ago), 2 (1 hour ago) are at or before 1 hour ago
    # Alerts 3 (now), 4 (1 day future) are after 1 hour ago, so excluded
    assert body["total"] == 2
    alert_ids = {item["id"] for item in body["items"]}
    assert {1, 2} == alert_ids


@pytest.mark.asyncio
async def test_get_alerts_filter_by_since_and_until(client):
    """GET /api/alerts?since=&until= with both params filters date range intersection."""
    now = datetime.now(UTC)
    # Define a range: 2 days ago to 2 hours ago
    # Alert 1 (1 day ago) is in range
    # Alert 2 (1 hour ago) is OUTSIDE (too recent, after 2 hours ago)
    # Alert 3 (now) is OUTSIDE (too recent, after 2 hours ago)
    # Alert 4 (1 day future) is OUTSIDE (too far in future, after 2 hours ago)
    # So only alert 1 should be returned... but wait, let me reconsider.
    # Actually, let's define: since=3 days ago, until=12 hours ago
    # Alert 1 (1 day ago): within range? (3 days ago <= 1 day ago <= 12 hours ago)? YES
    # Alert 2 (1 hour ago): within range? NO (after 12 hours ago)
    # Alert 3 (now): within range? NO (after 12 hours ago)
    # Alert 4 (1 day future): within range? NO (after 12 hours ago)
    # So only alert 1 should match.

    # But the spec says "seeds 4 alerts across a wide time span", so we're
    # testing with the existing 4 alerts. Let's use:
    # since = 2 days ago (includes alerts 1,2,3,4)
    # until = 30 minutes ago (excludes alert 3 at now and alert 4 at future)
    # This should include only alerts 1, 2 which are both before 30 min ago.

    since_dt = (now - timedelta(days=2)).isoformat()
    until_dt = (now - timedelta(minutes=30)).isoformat()
    encoded_since = since_dt.replace("+", "%2B")
    encoded_until = until_dt.replace("+", "%2B")
    r = await client.get(f"/api/alerts?since={encoded_since}&until={encoded_until}")
    assert r.status_code == 200
    body = r.json()
    # Alert 1 (1 day ago): 2 days ago <= 1 day ago <= 30 min ago? YES
    # Alert 2 (1 hour ago): 2 days ago <= 1 hour ago <= 30 min ago? YES
    # Alert 3 (now): 2 days ago <= now <= 30 min ago? NO (now > 30 min ago)
    # Alert 4 (1 day future): 2 days ago <= 1 day future <= 30 min ago? NO
    assert body["total"] == 2
    alert_ids = {item["id"] for item in body["items"]}
    assert {1, 2} == alert_ids


@pytest.mark.asyncio
async def test_get_alerts_pagination_limit(client):
    """GET /api/alerts?limit=2 respects limit."""
    r = await client.get("/api/alerts?limit=2")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert body["limit"] == 2
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_alerts_pagination_offset(client):
    """GET /api/alerts?offset=2 skips first N items."""
    r = await client.get("/api/alerts?offset=2&limit=2")
    assert r.status_code == 200
    body = r.json()
    assert body["offset"] == 2
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_alert_detail(client):
    """GET /api/alerts/{id} returns alert detail."""
    r = await client.get("/api/alerts/1")
    assert r.status_code == 200
    item = r.json()
    assert item["id"] == 1
    assert item["type"] == "new_match"
    assert item["kid_id"] == 1
    assert item["site_id"] == 1
    assert item["channels"] == ["push"]
    assert item["dedup_key"] == "key1"
    assert item["payload_json"] == {"msg": "test1"}
    assert item["sent_at"] is not None
    assert item["skipped"] is False


@pytest.mark.asyncio
async def test_get_alert_detail_not_found(client):
    """GET /api/alerts/{id} returns 404 for missing alert."""
    r = await client.get("/api/alerts/999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_resend_alert_clones_row(client):
    """POST /api/alerts/{id}/resend clones the alert with new dedup_key."""
    # Resend alert 1 (already sent)
    r = await client.post("/api/alerts/1/resend")
    assert r.status_code == 202
    new_alert = r.json()

    # Check the new alert has same fields as original except:
    # - id should be auto-assigned (different)
    # - scheduled_for should be roughly now
    # - sent_at should be None
    # - skipped should be False
    # - dedup_key should have suffix
    assert new_alert["id"] != 1
    assert new_alert["type"] == "new_match"
    assert new_alert["kid_id"] == 1
    assert new_alert["site_id"] == 1
    assert new_alert["channels"] == ["push"]
    assert new_alert["payload_json"] == {"msg": "test1"}
    assert new_alert["sent_at"] is None
    assert new_alert["skipped"] is False
    assert new_alert["dedup_key"].startswith("key1:resend:")


@pytest.mark.asyncio
async def test_alerts_resend_clones_original_payload(client):
    """Named must-have: resend clones payload, channels, distinct dedup_key, original unchanged."""
    # Get original alert
    r_orig = await client.get("/api/alerts/1")
    original = r_orig.json()

    # Resend it
    r_resend = await client.post("/api/alerts/1/resend")
    assert r_resend.status_code == 202
    cloned = r_resend.json()

    # Verify original is unchanged
    r_orig2 = await client.get("/api/alerts/1")
    original_after = r_orig2.json()
    assert original_after["dedup_key"] == original["dedup_key"]
    assert original_after["payload_json"] == original["payload_json"]
    assert original_after["sent_at"] == original["sent_at"]

    # Verify cloned has same payload and channels but different dedup_key
    assert cloned["payload_json"] == original["payload_json"]
    assert cloned["payload_json"] is not None
    assert cloned["channels"] == original["channels"]
    assert cloned["channels"] is not original["channels"]  # Different list objects
    assert cloned["dedup_key"] != original["dedup_key"]
    assert cloned["dedup_key"].startswith(original["dedup_key"] + ":resend:")


@pytest.mark.asyncio
async def test_resend_alert_not_found(client):
    """POST /api/alerts/{id}/resend returns 404 for missing alert."""
    r = await client.post("/api/alerts/999/resend")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_resend_pending_alert(client):
    """POST /api/alerts/{id}/resend works on pending alerts too."""
    # Resend alert 2 (pending)
    r = await client.post("/api/alerts/2/resend")
    assert r.status_code == 202
    cloned = r.json()
    assert cloned["payload_json"] == {"msg": "test2"}
    assert cloned["dedup_key"].startswith("key2:resend:")
