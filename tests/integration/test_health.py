from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from yas.db.base import Base
from yas.db.models import WorkerHeartbeat
from yas.db.session import create_engine_for, session_scope
from yas.web.app import create_app


@pytest.fixture
async def app_with_db(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path}/h.db"
    monkeypatch.setenv("YAS_DATABASE_URL", url)
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    engine = create_engine_for(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(engine=engine)
    yield app, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_healthz_returns_ok(app_with_db):
    app, _ = app_with_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "git_sha" in body  # default "unknown" outside CI; SHA in CI builds
    assert body["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_healthz_reports_git_sha_when_set(app_with_db, monkeypatch):
    monkeypatch.setenv("YAS_GIT_SHA", "abc1234")
    app, _ = app_with_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/healthz")
    assert r.json()["git_sha"] == "abc1234"


@pytest.mark.asyncio
async def test_readyz_503_when_no_heartbeat(app_with_db):
    app, _ = app_with_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/readyz")
    assert r.status_code == 503
    assert r.json()["heartbeat_fresh"] is False


@pytest.mark.asyncio
async def test_readyz_200_when_fresh_heartbeat(app_with_db):
    app, engine = app_with_db
    async with session_scope(engine) as s:
        s.add(WorkerHeartbeat(id=1, worker_name="main", last_beat=datetime.now(UTC)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["heartbeat_fresh"] is True
    assert body["db_reachable"] is True


@pytest.mark.asyncio
async def test_readyz_503_when_stale_heartbeat(app_with_db):
    app, engine = app_with_db
    async with session_scope(engine) as s:
        s.add(
            WorkerHeartbeat(
                id=1,
                worker_name="main",
                last_beat=datetime.now(UTC) - timedelta(seconds=600),
            )
        )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/readyz")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_readyz_503_when_db_unreachable(app_with_db):
    """If the DB connection itself fails, /readyz must fail closed (503)."""
    app, engine = app_with_db
    await engine.dispose()  # any further connection attempt will try (and may fail)

    # Replace the app's engine with one pointed at a file that doesn't exist
    # and can't be created (a directory path with a nested nonexistent parent).
    from yas.db.session import create_engine_for

    broken = create_engine_for("sqlite+aiosqlite:///nonexistent_dir/does/not/exist.db")
    app.state.yas.engine = broken

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["db_reachable"] is False
    assert body["heartbeat_fresh"] is False
    await broken.dispose()


@pytest.mark.asyncio
async def test_failing_readiness_probe_sends_no_events(sentry_events, app_with_db):
    """An unreachable DB is an operational state the probe reports, not an error to page on.

    Probes poll every few seconds; if each 503 raised an event, one outage
    would bury GlitchTip.
    """
    app, engine = app_with_db
    await engine.dispose()
    broken = create_engine_for("sqlite+aiosqlite:///nonexistent_dir/does/not/exist.db")
    app.state.yas.engine = broken

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for _ in range(3):
            assert (await c.get("/readyz")).status_code == 503
            assert (await c.get("/healthz")).status_code == 200

    assert sentry_events == []
    await broken.dispose()


@pytest.mark.asyncio
async def test_crashing_readiness_check_is_reported(sentry_events, app_with_db, monkeypatch):
    """Positive control for the test above: the FastAPI integration is live, so a
    probe that *raises* (a bug, not an outage) still reaches GlitchTip."""
    app, _ = app_with_db

    async def _broken_check(*_args, **_kwargs):
        raise RuntimeError("readiness check bug")

    monkeypatch.setattr("yas.web.app.check_readiness", _broken_check)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/readyz")).status_code == 500

    [event] = sentry_events
    assert event["exception"]["values"][-1]["type"] == "RuntimeError"
