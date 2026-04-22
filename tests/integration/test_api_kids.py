from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import Kid, UnavailabilityBlock, WatchlistEntry
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/k.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine, fetcher=None, llm=None, geocoder=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_kid_minimal(client):
    c, _ = client
    r = await c.post("/api/kids", json={"name": "Sam", "dob": "2019-05-01"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Sam"
    assert body["dob"] == "2019-05-01"
    assert body["active"] is True
    assert body["unavailability"] == []
    assert body["watchlist"] == []
    assert body["matches"] == []


@pytest.mark.asyncio
async def test_create_kid_with_nested_unavailability_atomic(client):
    c, engine = client
    payload = {
        "name": "Sam",
        "dob": "2019-05-01",
        "unavailability": [
            {
                "source": "manual",
                "label": "Tuesday piano",
                "days_of_week": ["tue"],
                "time_start": "16:00:00",
                "time_end": "17:00:00",
            }
        ],
    }
    r = await c.post("/api/kids", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert len(body["unavailability"]) == 1
    assert body["unavailability"][0]["label"] == "Tuesday piano"
    async with session_scope(engine) as s:
        blocks = (
            (
                await s.execute(
                    select(UnavailabilityBlock).where(UnavailabilityBlock.kid_id == body["id"])
                )
            )
            .scalars()
            .all()
        )
        assert len(blocks) == 1


@pytest.mark.asyncio
async def test_create_kid_with_nested_watchlist_atomic(client):
    c, engine = client
    payload = {
        "name": "Sam",
        "dob": "2019-05-01",
        "watchlist": [{"pattern": "chess club", "priority": "high"}],
    }
    r = await c.post("/api/kids", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert len(body["watchlist"]) == 1
    assert body["watchlist"][0]["pattern"] == "chess club"
    async with session_scope(engine) as s:
        entries = (
            (await s.execute(select(WatchlistEntry).where(WatchlistEntry.kid_id == body["id"])))
            .scalars()
            .all()
        )
        assert len(entries) == 1


@pytest.mark.asyncio
async def test_get_kid_list_brief(client):
    c, _ = client
    await c.post("/api/kids", json={"name": "Sam", "dob": "2019-05-01"})
    await c.post("/api/kids", json={"name": "Alex", "dob": "2020-07-15"})
    r = await c.get("/api/kids")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    keys = set(body[0].keys())
    assert keys == {"id", "name", "dob", "interests", "active"}


@pytest.mark.asyncio
async def test_get_kid_detail_includes_nested_collections(client):
    c, _ = client
    create = await c.post(
        "/api/kids",
        json={
            "name": "Sam",
            "dob": "2019-05-01",
            "unavailability": [{"source": "manual", "label": "piano", "days_of_week": ["tue"]}],
            "watchlist": [{"pattern": "chess club"}],
        },
    )
    kid_id = create.json()["id"]
    r = await c.get(f"/api/kids/{kid_id}")
    assert r.status_code == 200
    body = r.json()
    assert len(body["unavailability"]) == 1
    assert len(body["watchlist"]) == 1
    assert "enrollments" in body
    assert "matches" in body


@pytest.mark.asyncio
async def test_patch_kid_triggers_rematch_once(client, monkeypatch):
    c, _ = client
    create = await c.post("/api/kids", json={"name": "Sam", "dob": "2019-05-01"})
    kid_id = create.json()["id"]

    call_count = {"n": 0}

    async def spy(session, kid_id_arg, *, today=None):
        call_count["n"] += 1
        from yas.matching.matcher import MatchResult

        return MatchResult(kid_id=kid_id_arg)

    monkeypatch.setattr("yas.web.routes.kids.rematch_kid", spy)

    r = await c.patch(f"/api/kids/{kid_id}", json={"notes": "hi"})
    assert r.status_code == 200
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_patch_school_schedule_materializes_blocks(client):
    c, engine = client
    create = await c.post("/api/kids", json={"name": "Sam", "dob": "2019-05-01"})
    kid_id = create.json()["id"]

    r = await c.patch(
        f"/api/kids/{kid_id}",
        json={
            "school_time_start": "08:30:00",
            "school_time_end": "15:00:00",
            "school_year_ranges": [{"start": "2026-09-01", "end": "2027-06-15"}],
        },
    )
    assert r.status_code == 200
    async with session_scope(engine) as s:
        blocks = (
            (
                await s.execute(
                    select(UnavailabilityBlock).where(
                        UnavailabilityBlock.kid_id == kid_id,
                        UnavailabilityBlock.source == "school",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(blocks) == 1
        assert blocks[0].date_start == date(2026, 9, 1)


@pytest.mark.asyncio
async def test_delete_kid_cascades(client):
    c, engine = client
    create = await c.post(
        "/api/kids",
        json={
            "name": "Sam",
            "dob": "2019-05-01",
            "unavailability": [{"source": "manual", "label": "piano"}],
            "watchlist": [{"pattern": "chess"}],
        },
    )
    kid_id = create.json()["id"]
    r = await c.delete(f"/api/kids/{kid_id}")
    assert r.status_code == 204
    async with session_scope(engine) as s:
        assert (await s.execute(select(Kid).where(Kid.id == kid_id))).scalar_one_or_none() is None
        assert (
            await s.execute(select(UnavailabilityBlock).where(UnavailabilityBlock.kid_id == kid_id))
        ).scalars().all() == []
        assert (
            await s.execute(select(WatchlistEntry).where(WatchlistEntry.kid_id == kid_id))
        ).scalars().all() == []


@pytest.mark.asyncio
async def test_create_kid_rejects_unknown_fields(client):
    c, _ = client
    r = await c.post(
        "/api/kids",
        json={"name": "Sam", "dob": "2019-05-01", "bogus": "nope"},
    )
    assert r.status_code == 422
