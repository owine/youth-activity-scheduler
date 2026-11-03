"""API timestamps carry a UTC offset.

SQLite has no timezone storage, so `DateTime(timezone=True)` columns read back
naive. Serialized as-is ("2026-11-02T18:00:00") a browser parses that as *local*
time, shifting every alert / crawl time by the viewer's UTC offset. Response
schemas annotate timestamps as `UtcDatetime`, which reads a naive value as UTC
and emits it with a "Z".
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import Alert, Kid, WatchlistEntry
from yas.db.models._types import AlertType, CloseReason
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app

SCHEDULED = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)
CLOSED = datetime(2026, 11, 2, 19, 30, tzinfo=UTC)


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/tz.db"
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
                type=AlertType.new_match,
                kid_id=1,
                channels=["email"],
                scheduled_for=SCHEDULED,
                sent_at=SCHEDULED,
                dedup_key="k1",
                payload_json={},
                closed_at=CLOSED,
                close_reason=CloseReason.acknowledged,
            )
        )
        s.add(WatchlistEntry(id=1, kid_id=1, pattern="soccer", created_at=SCHEDULED))
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


def _assert_utc(value: str, expected: datetime) -> None:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None, f"{value!r} has no UTC offset"
    assert parsed == expected


async def test_alert_timestamps_have_offset(client):
    r = await client.get("/api/alerts/1")
    assert r.status_code == 200
    body = r.json()
    assert body["scheduled_for"] == "2026-11-02T18:00:00Z"
    _assert_utc(body["sent_at"], SCHEDULED)
    _assert_utc(body["closed_at"], CLOSED)


async def test_alert_list_timestamps_have_offset(client):
    r = await client.get("/api/alerts")
    assert r.status_code == 200
    (item,) = r.json()["items"]
    _assert_utc(item["scheduled_for"], SCHEDULED)
    _assert_utc(item["closed_at"], CLOSED)


async def test_inbox_alert_timestamps_have_offset(client):
    r = await client.get(
        "/api/inbox/summary",
        params={
            "since": (SCHEDULED - timedelta(days=1)).isoformat(),
            "until": (SCHEDULED + timedelta(days=1)).isoformat(),
            "include_closed": "true",
        },
    )
    assert r.status_code == 200
    body = r.json()
    (alert,) = body["alerts"]
    _assert_utc(alert["scheduled_for"], SCHEDULED)
    _assert_utc(alert["closed_at"], CLOSED)
    _assert_utc(body["window_start"], SCHEDULED - timedelta(days=1))


async def test_watchlist_created_at_has_offset(client):
    r = await client.get("/api/kids/1/watchlist")
    assert r.status_code == 200
    (entry,) = r.json()
    _assert_utc(entry["created_at"], SCHEDULED)
