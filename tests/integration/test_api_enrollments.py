from datetime import date, time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from yas.db.base import Base
from yas.db.models import (
    Kid,
    Location,
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
                id=1,
                site_id=1,
                page_id=1,
                name="Sat Soccer",
                normalized_name="sat soccer",
                program_type=ProgramType.soccer.value,
                start_date=date(2026, 5, 1),
                end_date=date(2026, 6, 30),
                days_of_week=["sat"],
                time_start=time(9, 0),
                time_end=time(10, 0),
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


@pytest.mark.asyncio
async def test_enrollment_includes_offering_summary(client):
    """EnrollmentOut.offering populated from join (D2).

    Covers both null and populated location_lat/location_lon branches.
    """
    c, engine = client
    # Create an enrollment for the seeded kid+offering (no location).
    r = await c.post(
        "/api/enrollments",
        json={"kid_id": 1, "offering_id": 1, "status": "interested"},
    )
    assert r.status_code == 201

    # Create a location and a second offering pointing to it.
    async with session_scope(engine) as s:
        location = Location(id=1, name="Downtown Arena", lat=40.71, lon=-74.01)
        s.add(location)
        await s.flush()
        offering = Offering(
            id=2,
            site_id=1,
            page_id=1,
            name="Swimming Lessons",
            normalized_name="swimming lessons",
            program_type=ProgramType.swim.value,
            start_date=date(2026, 5, 2),
            end_date=date(2026, 6, 30),
            days_of_week=["sun"],
            time_start=time(14, 0),
            time_end=time(15, 0),
            location_id=1,
        )
        s.add(offering)
        await s.flush()

    # Create an enrollment for the second offering (with location).
    r_enroll2 = await c.post(
        "/api/enrollments",
        json={"kid_id": 1, "offering_id": 2, "status": "enrolled"},
    )
    assert r_enroll2.status_code == 201

    # Fetch all enrollments for this kid and verify both have correct location info.
    r2 = await c.get("/api/enrollments?kid_id=1")
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) == 2

    # Find the enrollment for each offering by name.
    null_location_enrollment = next(e for e in rows if e["offering"]["name"] == "Sat Soccer")
    populated_location_enrollment = next(
        e for e in rows if e["offering"]["name"] == "Swimming Lessons"
    )

    # Verify null-location branch.
    null_offering = null_location_enrollment["offering"]
    assert null_offering["name"] == "Sat Soccer"
    assert null_offering["site_name"] == "X"
    assert null_offering["program_type"] == "soccer"
    assert null_offering["days_of_week"] == ["sat"]
    assert null_offering["location_lat"] is None
    assert null_offering["location_lon"] is None

    # Verify populated-location branch.
    pop_offering = populated_location_enrollment["offering"]
    assert pop_offering["name"] == "Swimming Lessons"
    assert pop_offering["site_name"] == "X"
    assert pop_offering["program_type"] == "swim"
    assert pop_offering["days_of_week"] == ["sun"]
    assert pop_offering["location_lat"] == 40.71
    assert pop_offering["location_lon"] == -74.01
