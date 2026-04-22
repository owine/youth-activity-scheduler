from datetime import date, time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import (
    Kid,
    Offering,
    Page,
    Site,
    UnavailabilityBlock,
)
from yas.db.models._types import ProgramType, UnavailabilitySource
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/en.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1), interests=["soccer"]))
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        s.add(
            Offering(
                id=1, site_id=1, page_id=1,
                name="Sat Soccer", normalized_name="sat soccer",
                program_type=ProgramType.soccer.value,
                start_date=date(2026, 5, 1), end_date=date(2026, 6, 30),
                days_of_week=["sat"], time_start=time(9, 0), time_end=time(10, 0),
            )
        )
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_post_enrollment_interested_does_not_create_block(client):
    c, engine = client
    r = await c.post(
        "/api/enrollments",
        json={"kid_id": 1, "offering_id": 1, "status": "interested"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "interested"
    async with session_scope(engine) as s:
        blocks = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert blocks == []


@pytest.mark.asyncio
async def test_post_enrollment_enrolled_creates_block(client):
    c, engine = client
    r = await c.post(
        "/api/enrollments",
        json={"kid_id": 1, "offering_id": 1, "status": "enrolled"},
    )
    assert r.status_code == 201
    async with session_scope(engine) as s:
        blocks = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert len(blocks) == 1
        b = blocks[0]
        assert b.source == UnavailabilitySource.enrollment.value
        assert b.source_enrollment_id == r.json()["id"]


@pytest.mark.asyncio
async def test_patch_interested_to_enrolled_creates_block(client):
    c, engine = client
    created = await c.post(
        "/api/enrollments",
        json={"kid_id": 1, "offering_id": 1, "status": "interested"},
    )
    eid = created.json()["id"]
    r = await c.patch(f"/api/enrollments/{eid}", json={"status": "enrolled"})
    assert r.status_code == 200
    async with session_scope(engine) as s:
        blocks = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert len(blocks) == 1


@pytest.mark.asyncio
async def test_patch_enrolled_to_cancelled_removes_block(client):
    c, engine = client
    created = await c.post(
        "/api/enrollments",
        json={"kid_id": 1, "offering_id": 1, "status": "enrolled"},
    )
    eid = created.json()["id"]
    r = await c.patch(f"/api/enrollments/{eid}", json={"status": "cancelled"})
    assert r.status_code == 200
    async with session_scope(engine) as s:
        blocks = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert blocks == []


@pytest.mark.asyncio
async def test_delete_enrollment_cleans_up_block(client):
    c, engine = client
    created = await c.post(
        "/api/enrollments",
        json={"kid_id": 1, "offering_id": 1, "status": "enrolled"},
    )
    eid = created.json()["id"]
    r = await c.delete(f"/api/enrollments/{eid}")
    assert r.status_code == 204
    async with session_scope(engine) as s:
        blocks = (await s.execute(select(UnavailabilityBlock))).scalars().all()
        assert blocks == []


@pytest.mark.asyncio
async def test_filters_by_kid_id_and_status(client, engine=None):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(Kid(id=2, name="Other", dob=date(2019, 1, 1)))
    await c.post("/api/enrollments", json={"kid_id": 1, "offering_id": 1, "status": "interested"})
    await c.post("/api/enrollments", json={"kid_id": 1, "offering_id": 1, "status": "enrolled"})
    await c.post("/api/enrollments", json={"kid_id": 2, "offering_id": 1, "status": "interested"})

    r_kid = await c.get("/api/enrollments?kid_id=1")
    assert len({e["id"] for e in r_kid.json()}) == 2

    r_status = await c.get("/api/enrollments?status=enrolled")
    assert [e["status"] for e in r_status.json()] == ["enrolled"]


@pytest.mark.asyncio
async def test_rejects_nonexistent_kid(client):
    c, _ = client
    r = await c.post(
        "/api/enrollments",
        json={"kid_id": 999, "offering_id": 1, "status": "interested"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_rejects_nonexistent_offering(client):
    c, _ = client
    r = await c.post(
        "/api/enrollments",
        json={"kid_id": 1, "offering_id": 999, "status": "interested"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_rejects_unknown_fields(client):
    c, _ = client
    r = await c.post(
        "/api/enrollments",
        json={"kid_id": 1, "offering_id": 1, "garbage": 1},
    )
    assert r.status_code == 422
