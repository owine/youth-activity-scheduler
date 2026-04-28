from datetime import UTC, date, datetime, time

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import Kid, Match, Offering, Page, Site
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
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1)))
        s.add(Kid(id=2, name="Other", dob=date(2019, 5, 1)))
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
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
        s.add(
            Offering(
                id=2,
                site_id=1,
                page_id=1,
                name="Sun Basketball",
                normalized_name="sun basketball",
                program_type=ProgramType.basketball.value,
                start_date=date(2026, 5, 2),
                days_of_week=["sun"],
                time_start=time(14, 0),
                time_end=time(15, 0),
            )
        )
        await s.flush()
        # Seed matches directly (don't exercise matcher in these tests).
        s.add(
            Match(
                kid_id=1,
                offering_id=1,
                score=0.82,
                reasons={"gates": {}, "score_breakdown": {}},
                computed_at=datetime.now(UTC),
            )
        )
        s.add(
            Match(
                kid_id=1,
                offering_id=2,
                score=0.35,
                reasons={"gates": {}, "score_breakdown": {}},
                computed_at=datetime.now(UTC),
            )
        )
        s.add(
            Match(
                kid_id=2,
                offering_id=1,
                score=0.71,
                reasons={"gates": {}, "score_breakdown": {}},
                computed_at=datetime.now(UTC),
            )
        )
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_all_matches(client):
    r = await client.get("/api/matches")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 3
    # Ordered by score desc
    scores = [row["score"] for row in rows]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_filter_by_kid_id(client):
    r = await client.get("/api/matches?kid_id=1")
    assert r.status_code == 200
    rows = r.json()
    assert {row["kid_id"] for row in rows} == {1}
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_filter_by_offering_id(client):
    r = await client.get("/api/matches?offering_id=1")
    assert r.status_code == 200
    rows = r.json()
    assert {row["offering_id"] for row in rows} == {1}
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_filter_by_min_score(client):
    r = await client.get("/api/matches?min_score=0.5")
    assert r.status_code == 200
    rows = r.json()
    assert all(row["score"] >= 0.5 for row in rows)
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_pagination(client):
    r = await client.get("/api/matches?limit=1&offset=0")
    assert len(r.json()) == 1
    r = await client.get("/api/matches?limit=1&offset=2")
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_response_shape_includes_offering_summary(client):
    r = await client.get("/api/matches?kid_id=1&offering_id=1")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["kid_id"] == 1
    assert row["offering_id"] == 1
    assert "reasons" in row
    assert "gates" in row["reasons"]
    assert "score_breakdown" in row["reasons"]
    assert row["offering"]["name"] == "Sat Soccer"
    assert row["offering"]["program_type"] == "soccer"
    assert row["offering"]["days_of_week"] == ["sat"]


@pytest.mark.asyncio
async def test_empty_result_set(client):
    r = await client.get("/api/matches?kid_id=999")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_min_score_out_of_range_422(client):
    r = await client.get("/api/matches?min_score=1.5")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_limit_enforced(client):
    r = await client.get("/api/matches?limit=0")
    assert r.status_code == 422
    r = await client.get("/api/matches?limit=501")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_match_includes_offering_registration_opens_at_and_site_name(client):
    r = await client.get("/api/matches?kid_id=1")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    # Both matches for kid 1 should have site_name and registration_opens_at in offering
    for row in body:
        offering = row["offering"]
        assert "site_name" in offering
        assert offering["site_name"] == "X"  # From fixture
        assert "registration_opens_at" in offering
