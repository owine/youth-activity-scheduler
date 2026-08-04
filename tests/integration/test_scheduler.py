from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import structlog.testing
from sqlalchemy import select

from tests.fakes.llm import FakeLLMClient
from tests.fixtures.server import fixture_site
from yas.config import Settings
from yas.crawl.fetcher import DefaultFetcher
from yas.crawl.scheduler import _tick, crawl_scheduler_loop
from yas.db.base import Base
from yas.db.models import Offering, Page, Site
from yas.db.models._types import ProgramType
from yas.db.session import create_engine_for, session_scope
from yas.llm.schemas import ExtractedOffering

PAGE = "<html><body><main><h1>Baseball</h1></main></body></html>"


async def _init(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/sched.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_scheduler_picks_due_page_and_runs_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    settings = Settings(_env_file=None, crawl_scheduler_tick_s=1, crawl_scheduler_batch_size=5)  # type: ignore[call-arg]
    engine = await _init(tmp_path)

    async with fixture_site(pages={"/p": PAGE}) as fx:
        async with session_scope(engine) as s:
            site = Site(name="Test", base_url=fx.base_url, default_cadence_s=3600)
            s.add(site)
            await s.flush()
            s.add(
                Page(
                    site_id=site.id,
                    url=fx.url("/p"),
                    next_check_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )

        fetcher = DefaultFetcher()
        llm = FakeLLMClient(
            default=[ExtractedOffering(name="Baseball", program_type=ProgramType.multisport)]
        )
        task = asyncio.create_task(
            crawl_scheduler_loop(engine=engine, settings=settings, fetcher=fetcher, llm=llm)
        )
        try:
            # Wait until an offering shows up OR timeout.
            for _ in range(60):
                async with session_scope(engine) as s:
                    offerings = (await s.execute(select(Offering))).scalars().all()
                if offerings:
                    break
                await asyncio.sleep(0.2)
            assert offerings and offerings[0].name == "Baseball"
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await fetcher.aclose()
    await engine.dispose()


@pytest.mark.asyncio
async def test_scheduler_logs_exceptions_escaping_crawl_page(tmp_path, monkeypatch):
    """A task that raises out of crawl_page must be logged, not swallowed.

    `_tick` gathers with return_exceptions=True and discards the results.
    crawl_page catches internally on the _do_crawl path, but its run-finalizing
    DB writes sit outside that try — so a failure there vanished with no log
    and no traceback.
    """
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    settings = Settings(_env_file=None, crawl_scheduler_tick_s=1, crawl_scheduler_batch_size=5)  # type: ignore[call-arg]
    engine = await _init(tmp_path)

    async with session_scope(engine) as s:
        site = Site(name="Test", base_url="https://example.com", default_cadence_s=3600)
        s.add(site)
        await s.flush()
        page = Page(
            site_id=site.id,
            url="https://example.com/p",
            next_check_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        s.add(page)
        await s.flush()
        page_id = page.id

    async def _boom(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("finalize blew up")

    monkeypatch.setattr("yas.crawl.scheduler.crawl_page", _boom)

    fetcher = DefaultFetcher()
    llm = FakeLLMClient(default=[])
    try:
        with structlog.testing.capture_logs() as logs:
            await _tick(engine=engine, settings=settings, fetcher=fetcher, llm=llm)
    finally:
        await fetcher.aclose()

    failed = [entry for entry in logs if entry.get("event") == "scheduler.page_failed"]
    assert failed, (
        f"exception escaping crawl_page must be logged, got: {[e.get('event') for e in logs]}"
    )
    assert failed[0]["log_level"] == "error"
    assert "finalize blew up" in failed[0]["error"]
    # The exception type is logged separately from its message. str(exc) can be
    # empty — the ForwardEmail timeouts that motivated this work surfaced as
    # "timeout: " with nothing after the colon — so the type is sometimes the
    # only thing identifying the failure, and it is what aggregates cleanly.
    assert failed[0]["error_type"] == "RuntimeError"
    # Pin the rest of the debugging contract so these fields can't quietly go.
    assert failed[0]["page_id"] == page_id
    assert "RuntimeError: finalize blew up" in failed[0]["traceback"]
    assert "_boom" in failed[0]["traceback"], "traceback must retain the raising frame"
    await engine.dispose()


@pytest.mark.asyncio
async def test_scheduler_skips_inactive_and_muted_sites(tmp_path, monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    settings = Settings(_env_file=None, crawl_scheduler_tick_s=1)  # type: ignore[call-arg]
    engine = await _init(tmp_path)

    async with fixture_site(pages={"/p": PAGE}) as fx:
        async with session_scope(engine) as s:
            inactive = Site(
                name="Inactive", base_url=fx.base_url, active=False, default_cadence_s=3600
            )
            muted = Site(
                name="Muted",
                base_url=fx.base_url,
                muted_until=datetime.now(UTC) + timedelta(hours=1),
                default_cadence_s=3600,
            )
            s.add_all([inactive, muted])
            await s.flush()
            s.add(
                Page(
                    site_id=inactive.id,
                    url=fx.url("/p"),
                    next_check_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
            s.add(
                Page(
                    site_id=muted.id,
                    url=fx.url("/p"),
                    next_check_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )

        fetcher = DefaultFetcher()
        llm = FakeLLMClient()
        task = asyncio.create_task(
            crawl_scheduler_loop(engine=engine, settings=settings, fetcher=fetcher, llm=llm)
        )
        try:
            await asyncio.sleep(3)  # enough for ~3 ticks
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await fetcher.aclose()
    # Nothing crawled — active-site filter held.
    # Note: muted sites DO still have pages crawled when they are the alert-mute
    # case in spec §3; but the scheduler here is gated by the site.muted_until
    # row condition per spec §3.6 → so neither site gets crawled.
    assert llm.call_count == 0
    await engine.dispose()
