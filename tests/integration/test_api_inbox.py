from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import Alert, CrawlRun, Kid, Match, Offering, Page, Site
from yas.db.models._types import AlertType, CloseReason, CrawlStatus
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/i.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_inbox_empty_window_returns_zero_counts(client):
    c, _ = client
    now = datetime.now(UTC)
    r = await c.get(
        "/api/inbox/summary",
        params={"since": _iso(now - timedelta(days=7)), "until": _iso(now)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["alerts"] == []
    assert body["new_matches_by_kid"] == []
    assert body["site_activity"]["refreshed_count"] == 0
    assert body["site_activity"]["posted_new_count"] == 0
    assert body["site_activity"]["stagnant_count"] == 0


@pytest.mark.asyncio
async def test_inbox_includes_alert_with_kid_name_and_summary(client):
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        s.add(Site(id=1, name="Lil Sluggers", base_url="https://x", needs_browser=False))
        await s.flush()
        s.add(
            Alert(
                type=AlertType.watchlist_hit.value,
                kid_id=1,
                site_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=1),
                dedup_key="k1",
                payload_json={"offering_name": "T-Ball", "site_name": "Lil Sluggers"},
            )
        )
    r = await c.get(
        "/api/inbox/summary",
        params={
            "since": _iso(now - timedelta(days=1)),
            "until": _iso(now + timedelta(seconds=1)),
        },
    )
    body = r.json()
    assert len(body["alerts"]) == 1
    a = body["alerts"][0]
    assert a["kid_name"] == "Sam"
    assert "T-Ball" in a["summary_text"]
    assert "Sam" in a["summary_text"]


@pytest.mark.asyncio
async def test_inbox_new_matches_grouped_by_kid_with_opening_soon_counts(client):
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        s.add(Site(id=1, name="X", base_url="https://x", needs_browser=False))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        # Two offerings: one opens tomorrow (counts as opening_soon),
        # one opens in 30 days (does not).
        s.add(
            Offering(
                id=1,
                site_id=1,
                page_id=1,
                name="Open soon",
                normalized_name="open soon",
                start_date=(now + timedelta(days=20)).date(),
                registration_opens_at=now + timedelta(days=1),
                status="active",
            )
        )
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Open later",
                normalized_name="open later",
                start_date=(now + timedelta(days=60)).date(),
                registration_opens_at=now + timedelta(days=30),
                status="active",
            )
        )
        await s.flush()
        s.add(
            Match(
                kid_id=1,
                offering_id=1,
                score=0.9,
                reasons={},
                computed_at=now - timedelta(hours=1),
            )
        )
        s.add(
            Match(
                kid_id=1,
                offering_id=2,
                score=0.8,
                reasons={},
                computed_at=now - timedelta(hours=2),
            )
        )
    r = await c.get(
        "/api/inbox/summary",
        params={
            "since": _iso(now - timedelta(days=1)),
            "until": _iso(now + timedelta(seconds=1)),
        },
    )
    body = r.json()
    assert len(body["new_matches_by_kid"]) == 1
    row = body["new_matches_by_kid"][0]
    assert row["kid_id"] == 1
    assert row["kid_name"] == "Sam"
    assert row["total_new"] == 2
    assert row["opening_soon_count"] == 1  # only the one opening tomorrow


@pytest.mark.asyncio
async def test_inbox_site_activity_counts(client):
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        for i in range(2):
            s.add(Site(id=i + 1, name=f"S{i}", base_url=f"https://s{i}", needs_browser=False))
        await s.flush()
        # Site 1: successful crawl in window
        s.add(
            CrawlRun(
                site_id=1,
                started_at=now - timedelta(hours=2),
                status=CrawlStatus.ok.value,
                pages_fetched=1,
                changes_detected=0,
                llm_calls=0,
                llm_cost_usd=0.0,
            )
        )
        # Site 2: schedule_posted alert in window
        s.add(
            Alert(
                type=AlertType.schedule_posted.value,
                site_id=2,
                channels=[],
                scheduled_for=now - timedelta(hours=1),
                dedup_key="sp1",
                payload_json={"site_name": "S1", "n_offerings": 3},
            )
        )
    r = await c.get(
        "/api/inbox/summary",
        params={
            "since": _iso(now - timedelta(days=1)),
            "until": _iso(now + timedelta(seconds=1)),
        },
    )
    body = r.json()
    assert body["site_activity"]["refreshed_count"] == 1
    assert body["site_activity"]["posted_new_count"] == 1
    assert body["site_activity"]["stagnant_count"] == 0


@pytest.mark.asyncio
async def test_inbox_malformed_timestamp_returns_422(client):
    c, _ = client
    r = await c.get("/api/inbox/summary", params={"since": "not-a-date", "until": "also-not"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_inbox_falls_back_gracefully_for_unknown_stored_alert_type(client):
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        s.add(Site(id=1, name="Lil Sluggers", base_url="https://x", needs_browser=False))
        await s.flush()
        s.add(
            Alert(
                type="some_legacy_type_not_in_enum",
                kid_id=1,
                site_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=1),
                dedup_key="legacy1",
                payload_json={"offering_name": "T-Ball", "site_name": "Lil Sluggers"},
            )
        )
    r = await c.get(
        "/api/inbox/summary",
        params={
            "since": _iso(now - timedelta(days=1)),
            "until": _iso(now + timedelta(seconds=1)),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["alerts"]) == 1
    a = body["alerts"][0]
    assert a["type"] == "some_legacy_type_not_in_enum"
    assert isinstance(a["summary_text"], str)
    assert len(a["summary_text"]) > 0


@pytest.mark.asyncio
async def test_inbox_summary_excludes_closed_alerts_by_default(client):
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        await s.flush()
        s.add(
            Alert(
                id=1,
                type=AlertType.watchlist_hit,
                kid_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=1),
                dedup_key="open-1",
                payload_json={},
            )
        )
        s.add(
            Alert(
                id=2,
                type=AlertType.watchlist_hit,
                kid_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=2),
                dedup_key="closed-1",
                payload_json={},
                closed_at=now,
                close_reason=CloseReason.acknowledged,
            )
        )
    r = await c.get(
        "/api/inbox/summary",
        params={"since": _iso(now - timedelta(days=1)), "until": _iso(now + timedelta(days=1))},
    )
    assert r.status_code == 200
    ids = {a["id"] for a in r.json()["alerts"]}
    assert ids == {1}


@pytest.mark.asyncio
async def test_inbox_summary_with_include_closed_returns_closed_alerts(client):
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        await s.flush()
        s.add(
            Alert(
                id=1,
                type=AlertType.watchlist_hit,
                kid_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=1),
                dedup_key="open-1",
                payload_json={},
            )
        )
        s.add(
            Alert(
                id=2,
                type=AlertType.watchlist_hit,
                kid_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=2),
                dedup_key="closed-1",
                payload_json={},
                closed_at=now,
                close_reason=CloseReason.dismissed,
            )
        )
    r = await c.get(
        "/api/inbox/summary",
        params={
            "since": _iso(now - timedelta(days=1)),
            "until": _iso(now + timedelta(days=1)),
            "include_closed": "true",
        },
    )
    assert r.status_code == 200
    alerts = r.json()["alerts"]
    ids_to_reasons = {a["id"]: a["close_reason"] for a in alerts}
    assert ids_to_reasons == {1: None, 2: "dismissed"}


@pytest.mark.asyncio
async def test_closing_schedule_posted_alert_does_not_reduce_site_activity_count(client):
    """Regression: site-distinct schedule_posted count is analytics, not inbox.

    Closing a schedule_posted alert should NOT change posted_new_count.
    """
    c, engine = client
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(
            Alert(
                id=1,
                type=AlertType.schedule_posted,
                site_id=1,
                channels=["email"],
                scheduled_for=now - timedelta(hours=1),
                dedup_key="sp-1",
                payload_json={},
                closed_at=now,
                close_reason=CloseReason.acknowledged,
            )
        )
    r = await c.get(
        "/api/inbox/summary",
        params={"since": _iso(now - timedelta(days=1)), "until": _iso(now + timedelta(days=1))},
    )
    assert r.status_code == 200
    body = r.json()
    # The closed schedule_posted alert is NOT in the inbox alert list…
    assert body["alerts"] == []
    # …but the site-distinct analytics count still sees it.
    assert body["site_activity"]["posted_new_count"] == 1
