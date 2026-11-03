"""Worker loops must survive a failed iteration, and must not hold SQLite's write
lock across slow I/O.

In `all` mode the worker's loops share a TaskGroup with uvicorn, so an exception
escaping any loop exits the whole process. Separately, a session that has flushed
writes holds the database's only write lock until it commits; a network call made
while it does blocks every other writer (the heartbeat, API writes), and past the
5s busy_timeout those fail with `database is locked`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine

import yas.matching.matcher as matcher_mod
from tests.fakes.geocoder import FakeGeocoder
from tests.fakes.notifier import FakeNotifier
from tests.fakes.sqlite_lock import write_lock_held
from yas.alerts.channels.base import NotifierCapability, NotifierMessage, SendResult
from yas.alerts.enqueuer import enqueue_crawl_failed
from yas.alerts.routing import seed_default_routing
from yas.config import Settings
from yas.crawl.scheduler import crawl_scheduler_loop
from yas.db.base import Base
from yas.db.models import (
    Alert,
    AlertRouting,
    HouseholdSettings,
    Kid,
    Location,
    Match,
    Offering,
    Page,
    Site,
)
from yas.db.session import create_engine_for, session_scope
from yas.geo.client import GeocodeResult
from yas.geo.enricher import EnrichResult, enrich_ungeocoded_locations, geocode_enricher_loop
from yas.matching.matcher import rematch_kid, rematch_offering
from yas.worker.delivery_loop import alert_delivery_loop
from yas.worker.detector_loop import daily_detector_loop
from yas.worker.digest_loop import daily_digest_loop
from yas.worker.runner import _heartbeat_loop
from yas.worker.sweep import daily_sweep_loop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**kwargs: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        anthropic_api_key="test-key",
        # 00:00 fires on any clock reading, so the daily loops run on tick one.
        sweep_time_utc="00:00",
        alert_digest_time_utc="00:00",
        alert_detector_time_utc="00:00",
        worker_heartbeat_interval_s=1,
        crawl_scheduler_tick_s=1,
        geocode_tick_s=1,
        alert_delivery_tick_s=1,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


async def _make_engine(tmp_path: Path) -> tuple[AsyncEngine, Path]:
    db_path = tmp_path / "w.db"
    engine = create_engine_for(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, db_path


@pytest.fixture
def ticks(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], None]:
    """Make every loop's sleep instant, and cancel the loop on its Nth sleep.

    Returns a setter for N (default 3: three iterations, then cancel)."""
    real_sleep = asyncio.sleep
    state = {"limit": 3, "count": 0}

    async def fake_sleep(delay: float, *args: Any, **kwargs: Any) -> None:
        state["count"] += 1
        if state["count"] >= state["limit"]:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    def set_limit(n: int) -> None:
        state["limit"] = n

    return set_limit


def _fail_first_call(real: Callable[..., Any] | None = None, result: Any = None) -> Any:
    """An async stand-in that raises on its first call, then delegates/returns."""
    calls: list[int] = []

    async def stub(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("iteration exploded")
        if real is not None:
            return await real(*args, **kwargs)
        return result

    stub.calls = calls  # type: ignore[attr-defined]
    return stub


async def _seed_offerings(
    engine: AsyncEngine, *, kids: int, offerings: int, threshold: float = 0.6
) -> None:
    async with session_scope(engine) as s:
        home = Location(name="home", address="home", lat=40.0, lon=-75.0)
        s.add(home)
        await s.flush()
        s.add(HouseholdSettings(id=1, home_location_id=home.id, default_max_distance_mi=30))
        site = Site(name="S", base_url="https://s")
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="https://s/p")
        s.add(page)
        locs = [Location(name=f"L{i}", lat=40.0 + i / 100, lon=-75.0) for i in range(5)]
        s.add_all(locs)
        await s.flush()
        for i in range(offerings):
            s.add(
                Offering(
                    site_id=site.id,
                    page_id=page.id,
                    name=f"Soccer {i}",
                    normalized_name=f"soccer {i}",
                    program_type="soccer",
                    age_min=5,
                    age_max=10,
                    location_id=locs[i % len(locs)].id,
                    start_date=date.today() + timedelta(days=60),
                    end_date=date.today() + timedelta(days=120),
                    days_of_week=["tue"],
                )
            )
        for k in range(kids):
            s.add(
                Kid(
                    name=f"K{k}",
                    dob=date.today() - timedelta(days=365 * 7),
                    interests=["soccer"],
                    alert_score_threshold=threshold,
                )
            )


# ---------------------------------------------------------------------------
# 1. A failed iteration doesn't kill the loop
# ---------------------------------------------------------------------------


async def test_heartbeat_survives_failed_beat(tmp_path, monkeypatch, ticks):  # type: ignore[no-untyped-def]
    engine, _ = await _make_engine(tmp_path)
    import yas.worker.runner as runner_mod

    stub = _fail_first_call(runner_mod.beat_once)
    monkeypatch.setattr(runner_mod, "beat_once", stub)
    with pytest.raises(asyncio.CancelledError):
        await _heartbeat_loop(engine, _settings())
    assert len(stub.calls) == 3
    await engine.dispose()


async def test_crawl_scheduler_survives_failed_tick(tmp_path, monkeypatch, ticks):  # type: ignore[no-untyped-def]
    engine, _ = await _make_engine(tmp_path)
    import yas.crawl.scheduler as sched_mod

    stub = _fail_first_call(result=None)
    monkeypatch.setattr(sched_mod, "_tick", stub)
    with pytest.raises(asyncio.CancelledError):
        await crawl_scheduler_loop(
            engine=engine,
            settings=_settings(),
            fetcher=None,  # type: ignore[arg-type]
            llm=None,  # type: ignore[arg-type]
        )
    assert len(stub.calls) == 3
    await engine.dispose()


async def test_enricher_survives_failed_tick(tmp_path, monkeypatch, ticks):  # type: ignore[no-untyped-def]
    engine, _ = await _make_engine(tmp_path)
    import yas.geo.enricher as enricher_mod

    stub = _fail_first_call(result=EnrichResult(updated=0, not_found=0, errored=0, skipped=0))
    monkeypatch.setattr(enricher_mod, "enrich_ungeocoded_locations", stub)
    with pytest.raises(asyncio.CancelledError):
        await geocode_enricher_loop(engine, _settings(), FakeGeocoder())
    assert len(stub.calls) == 3
    await engine.dispose()


async def test_delivery_survives_failed_tick(tmp_path, monkeypatch, ticks):  # type: ignore[no-untyped-def]
    engine, _ = await _make_engine(tmp_path)
    import yas.worker.delivery_loop as delivery_mod

    # coalesce is sync, so it gets its own fail-once stand-in.
    calls: list[int] = []
    real_coalesce = delivery_mod.coalesce

    def coalesce(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("iteration exploded")
        return real_coalesce(*args, **kwargs)

    monkeypatch.setattr(delivery_mod, "coalesce", coalesce)
    with pytest.raises(asyncio.CancelledError):
        await alert_delivery_loop(engine, _settings(), {"email": FakeNotifier(name="email")})
    assert len(calls) == 3
    await engine.dispose()


async def test_sweep_failure_is_not_retried_every_tick(tmp_path, monkeypatch, ticks):  # type: ignore[no-untyped-def]
    """A failed sweep marks the day attempted: it reports once and retries
    tomorrow, rather than re-running (and re-reporting) every 60s."""
    engine, _ = await _make_engine(tmp_path)
    await _seed_offerings(engine, kids=1, offerings=1)
    stub = _fail_first_call(matcher_mod._kid_blocks)
    monkeypatch.setattr(matcher_mod, "_kid_blocks", stub)
    with pytest.raises(asyncio.CancelledError):
        await daily_sweep_loop(engine, _settings())
    assert len(stub.calls) == 1
    await engine.dispose()


async def test_digest_survives_failed_run(tmp_path, monkeypatch, ticks):  # type: ignore[no-untyped-def]
    engine, _ = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        s.add(Kid(name="A", dob=date(2018, 1, 1), created_at=datetime.now(UTC)))
    import yas.worker.digest_loop as digest_mod

    stub = _fail_first_call(digest_mod.gather_digest_payload)
    monkeypatch.setattr(digest_mod, "gather_digest_payload", stub)
    with pytest.raises(asyncio.CancelledError):
        await daily_digest_loop(engine, _settings(), None)
    assert len(stub.calls) == 1
    await engine.dispose()


async def test_detector_survives_failed_run(tmp_path, monkeypatch, ticks):  # type: ignore[no-untyped-def]
    engine, _ = await _make_engine(tmp_path)
    import yas.worker.detector_loop as detector_mod

    stub = _fail_first_call(detector_mod.detect_stagnant_sites)
    monkeypatch.setattr(detector_mod, "detect_stagnant_sites", stub)
    with pytest.raises(asyncio.CancelledError):
        await daily_detector_loop(engine, _settings())
    assert len(stub.calls) == 1
    await engine.dispose()


# ---------------------------------------------------------------------------
# 2. No network call while the session holds uncommitted writes
# ---------------------------------------------------------------------------


async def test_delivery_commits_each_group_before_sending_the_next(tmp_path, ticks):  # type: ignore[no-untyped-def]
    engine, db_path = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        await seed_default_routing(s)
        for i in (1, 2, 3):
            s.add(Site(id=i, name=f"S{i}", base_url=f"https://s{i}"))
        await s.flush()
        for i in (1, 2, 3):
            # crawl_failed never coalesces, so these are three groups.
            await enqueue_crawl_failed(s, site_id=i, consecutive_failures=3, last_error="x")

    locked_at_send: list[bool] = []

    class ProbeNotifier(FakeNotifier):
        async def send(self, msg: NotifierMessage) -> SendResult:
            locked_at_send.append(write_lock_held(db_path))
            return await super().send(msg)

    ticks(1)  # one tick
    with pytest.raises(asyncio.CancelledError):
        await alert_delivery_loop(engine, _settings(), {"email": ProbeNotifier(name="email")})
    assert locked_at_send == [False, False, False]
    async with session_scope(engine) as s:
        sent = (await s.execute(select(Alert).where(Alert.sent_at.is_not(None)))).scalars().all()
    assert len(sent) == 3
    await engine.dispose()


async def test_digest_commits_each_kid_before_the_next_llm_call(tmp_path, ticks):  # type: ignore[no-untyped-def]
    engine, db_path = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        for i in (1, 2, 3):
            # Recently created → under the no-matches threshold → has content.
            s.add(Kid(id=i, name=f"K{i}", dob=date(2018, 1, 1), created_at=datetime.now(UTC)))

    locked_at_call: list[bool] = []

    class ProbeLLM:
        async def call_tool(self, **_: Any) -> tuple[dict[str, Any], str, float]:
            locked_at_call.append(write_lock_held(db_path))
            return {"top_line": "Nothing new today."}, "fake", 0.0

    ticks(1)
    with pytest.raises(asyncio.CancelledError):
        await daily_digest_loop(engine, _settings(), ProbeLLM())  # type: ignore[arg-type]
    assert locked_at_call == [False, False, False]
    async with session_scope(engine) as s:
        digests = (await s.execute(select(Alert).where(Alert.type == "digest"))).scalars().all()
    assert len(digests) == 3
    await engine.dispose()


async def test_enricher_commits_each_geocode_before_the_next(tmp_path):  # type: ignore[no-untyped-def]
    engine, db_path = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        site = Site(name="S", base_url="https://s")
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url="https://s/p")
        s.add(page)
        for i in range(3):
            s.add(Location(id=i + 1, name=f"L{i}", address=f"{i} main st"))
        await s.flush()
        for i in range(3):
            s.add(
                Offering(
                    site_id=site.id,
                    page_id=page.id,
                    name=f"O{i}",
                    normalized_name=f"o{i}",
                    location_id=i + 1,
                )
            )
        s.add(Kid(name="K", dob=date(2018, 1, 1)))

    locked_at_call: list[bool] = []

    class ProbeGeocoder(FakeGeocoder):
        async def geocode(self, address: str) -> GeocodeResult | None:
            locked_at_call.append(write_lock_held(db_path))
            return await super().geocode(address)

    geocoder = ProbeGeocoder(
        fixtures={
            f"{i} main st": GeocodeResult(lat=40.0, lon=-75.0, display_name="x", provider="fake")
            for i in range(3)
        }
    )
    async with session_scope(engine) as s:
        result = await enrich_ungeocoded_locations(
            s, geocoder, batch_size=10, on_rematch=rematch_offering
        )
    assert result.updated == 3
    assert locked_at_call == [False, False, False]
    async with session_scope(engine) as s:
        locs = (await s.execute(select(Location).order_by(Location.id))).scalars().all()
    assert all(loc.lat == 40.0 for loc in locs)
    await engine.dispose()


async def test_sweep_commits_each_kid_before_the_next(tmp_path, monkeypatch, ticks):  # type: ignore[no-untyped-def]
    engine, db_path = await _make_engine(tmp_path)
    await _seed_offerings(engine, kids=3, offerings=4)
    locked_at_kid_start: list[bool] = []
    real_kid_blocks = matcher_mod._kid_blocks

    async def probe(session: Any, kid_id: int) -> Any:
        locked_at_kid_start.append(write_lock_held(db_path))
        return await real_kid_blocks(session, kid_id)

    monkeypatch.setattr(matcher_mod, "_kid_blocks", probe)
    ticks(1)
    with pytest.raises(asyncio.CancelledError):
        await daily_sweep_loop(engine, _settings())
    assert locked_at_kid_start == [False, False, False]
    async with session_scope(engine) as s:
        matches = (await s.execute(select(Match))).scalars().all()
    assert len(matches) == 3 * 4
    await engine.dispose()


async def test_rematch_kid_query_count_does_not_grow_per_offering(tmp_path):  # type: ignore[no-untyped-def]
    """The sweep's per-kid pass used to issue ~3 queries per offering (location,
    existing match, already-alerted check), which kept a big sweep's write
    transaction open for seconds."""

    async def count_queries(offerings: int) -> int:
        db_dir = tmp_path / str(offerings)
        db_dir.mkdir()
        engine, _ = await _make_engine(db_dir)
        # A threshold above any score keeps alert enqueueing out of the count.
        await _seed_offerings(engine, kids=1, offerings=offerings, threshold=2.0)
        statements: list[str] = []

        def on_execute(conn, cursor, statement, *a):  # type: ignore[no-untyped-def]
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", on_execute)
        # Two passes: the first inserts every match, the second updates them.
        for _ in range(2):
            async with session_scope(engine) as s:
                kid = (await s.execute(select(Kid))).scalar_one()
                await rematch_kid(s, kid.id)
        await engine.dispose()
        return len([st for st in statements if st.lstrip().upper().startswith("SELECT")])

    small = await count_queries(2)
    large = await count_queries(40)
    assert large == small


# ---------------------------------------------------------------------------
# 3. Invalid stored quiet hours don't kill delivery
# ---------------------------------------------------------------------------


async def test_delivery_survives_invalid_quiet_hours(tmp_path, ticks):  # type: ignore[no-untyped-def]
    """Quiet hours were only ever validated as \\d\\d:\\d\\d, so '24:00' could be
    stored; parsing it raised inside the delivery loop and exited the process.
    An unparseable window is treated as no quiet hours."""
    engine, _ = await _make_engine(tmp_path)
    async with session_scope(engine) as s:
        await seed_default_routing(s)
        s.add(HouseholdSettings(id=1, quiet_hours_start="22:00", quiet_hours_end="24:00"))
        s.add(Site(id=1, name="S", base_url="https://s"))
        await s.flush()
        row = (
            await s.execute(select(AlertRouting).where(AlertRouting.type == "crawl_failed"))
        ).scalar_one()
        row.channels = ["ntfy"]
        await enqueue_crawl_failed(s, site_id=1, consecutive_failures=3, last_error="x")
    notifier = FakeNotifier(name="ntfy", capabilities={NotifierCapability.push})
    ticks(1)
    with pytest.raises(asyncio.CancelledError):
        await alert_delivery_loop(engine, _settings(), {"ntfy": notifier})
    assert notifier.call_count == 1
    await engine.dispose()
