from datetime import date, time

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import (
    Enrollment,
    Kid,
    Offering,
    Page,
    Site,
    UnavailabilityBlock,
)
from yas.db.models._types import (
    EnrollmentStatus,
    ProgramType,
    UnavailabilitySource,
)
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    url = f"sqlite+aiosqlite:///{tmp_path}/u.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_scope(engine) as s:
        s.add(Kid(id=1, name="Sam", dob=date(2019, 5, 1), interests=["soccer"]))
    app = create_app(engine=engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_manual_block(client):
    c, _ = client
    r = await c.post(
        "/api/kids/1/unavailability",
        json={
            "label": "Grandma visit",
            "date_start": "2026-07-01",
            "date_end": "2026-07-07",
            "source": "manual",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "manual"
    assert body["label"] == "Grandma visit"


@pytest.mark.asyncio
async def test_create_custom_block_with_days_and_times(client):
    c, _ = client
    r = await c.post(
        "/api/kids/1/unavailability",
        json={
            "source": "custom",
            "label": "Piano lessons",
            "days_of_week": ["tue"],
            "time_start": "16:00",
            "time_end": "17:00",
        },
    )
    assert r.status_code == 201
    assert r.json()["days_of_week"] == ["tue"]


@pytest.mark.asyncio
async def test_patch_manual_block(client):
    c, _ = client
    created = await c.post(
        "/api/kids/1/unavailability",
        json={"label": "old", "source": "manual"},
    )
    bid = created.json()["id"]
    r = await c.patch(
        f"/api/kids/1/unavailability/{bid}", json={"label": "new"}
    )
    assert r.status_code == 200
    assert r.json()["label"] == "new"


@pytest.mark.asyncio
async def test_delete_manual_block(client):
    c, _ = client
    created = await c.post(
        "/api/kids/1/unavailability", json={"label": "x", "source": "manual"}
    )
    bid = created.json()["id"]
    r = await c.delete(f"/api/kids/1/unavailability/{bid}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_patch_school_block_returns_409(client, engine=None):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(
            UnavailabilityBlock(
                id=100,
                kid_id=1,
                source=UnavailabilitySource.school.value,
                days_of_week=["mon"],
                time_start=time(8, 0),
                time_end=time(15, 0),
                date_start=date(2026, 9, 1),
                date_end=date(2027, 6, 14),
            )
        )
    r = await c.patch("/api/kids/1/unavailability/100", json={"label": "oops"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_patch_enrollment_block_returns_409(client, engine=None):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(Site(id=1, name="X", base_url="https://x"))
        await s.flush()
        s.add(Page(id=1, site_id=1, url="https://x/p"))
        await s.flush()
        s.add(
            Offering(
                id=1, site_id=1, page_id=1, name="Sat Soccer",
                normalized_name="sat soccer",
                program_type=ProgramType.soccer.value,
            )
        )
        await s.flush()
        s.add(Enrollment(id=1, kid_id=1, offering_id=1, status=EnrollmentStatus.enrolled.value))
        await s.flush()
        s.add(
            UnavailabilityBlock(
                id=200,
                kid_id=1,
                source=UnavailabilitySource.enrollment.value,
                source_enrollment_id=1,
            )
        )
    r = await c.delete("/api/kids/1/unavailability/200")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_get_lists_all_sources(client, engine=None):
    c, engine = client
    async with session_scope(engine) as s:
        s.add(
            UnavailabilityBlock(
                kid_id=1,
                source=UnavailabilitySource.school.value,
                days_of_week=["mon"],
            )
        )
        s.add(
            UnavailabilityBlock(
                kid_id=1,
                source=UnavailabilitySource.manual.value,
                label="Custom",
            )
        )
    r = await c.get("/api/kids/1/unavailability")
    assert r.status_code == 200
    sources = {row["source"] for row in r.json()}
    assert sources == {"school", "manual"}


@pytest.mark.asyncio
async def test_rejects_school_source_on_create(client):
    c, _ = client
    r = await c.post(
        "/api/kids/1/unavailability",
        json={"source": "school", "label": "nope"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_rejects_unknown_fields(client):
    c, _ = client
    r = await c.post(
        "/api/kids/1/unavailability",
        json={"source": "manual", "label": "x", "garbage": 1},
    )
    assert r.status_code == 422
