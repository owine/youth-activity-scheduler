from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.fakes.llm import FakeLLMClient
from tests.fixtures.server import fixture_site
from yas.crawl.fetcher import DefaultFetcher
from yas.crawl.pipeline import crawl_page
from yas.db.base import Base
from yas.db.models import CrawlRun, Offering, Page, Site
from yas.db.models._types import CrawlStatus, ProgramType
from yas.db.session import create_engine_for, session_scope
from yas.llm.schemas import ExtractedOffering

PAGE = """<!doctype html><html><body><main>
<h1>Tots Baseball</h1><p>Ages 2-3. Sat 9am.</p>
</main></body></html>"""


async def _init_db(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/pipe.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _register(engine, site_url, page_url):
    async with session_scope(engine) as s:
        site = Site(name="Test", base_url=site_url)
        s.add(site)
        await s.flush()
        page = Page(site_id=site.id, url=page_url)
        s.add(page)
        await s.flush()
        return site.id, page.id


@pytest.mark.asyncio
async def test_crawl_page_happy_path(tmp_path):
    engine = await _init_db(tmp_path)
    async with fixture_site(pages={"/p": PAGE}) as fx:
        fetcher = DefaultFetcher()
        llm = FakeLLMClient(
            default=[
                ExtractedOffering(
                    name="Tots Baseball", program_type=ProgramType.multisport, age_min=2, age_max=3
                )
            ]
        )
        site_id, page_id = await _register(engine, fx.base_url, fx.url("/p"))
        try:
            async with session_scope(engine) as s:
                site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one()
                page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
            await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)
        finally:
            await fetcher.aclose()
    async with session_scope(engine) as s:
        offerings = (await s.execute(select(Offering))).scalars().all()
        runs = (await s.execute(select(CrawlRun))).scalars().all()
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        assert [o.name for o in offerings] == ["Tots Baseball"]
        assert len(runs) == 1
        assert runs[0].status == CrawlStatus.ok
        assert runs[0].pages_fetched == 1
        assert runs[0].changes_detected == 1
        assert runs[0].llm_calls == 1
        assert page.content_hash is not None
        assert page.last_fetched is not None
        assert page.next_check_at is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_crawl_page_cache_hit_on_repeat(tmp_path):
    engine = await _init_db(tmp_path)
    async with fixture_site(pages={"/p": PAGE}) as fx:
        fetcher = DefaultFetcher()
        llm = FakeLLMClient(
            default=[ExtractedOffering(name="Tots Baseball", program_type=ProgramType.multisport)]
        )
        site_id, page_id = await _register(engine, fx.base_url, fx.url("/p"))
        try:
            async with session_scope(engine) as s:
                site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one()
                page1 = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
            await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page1, site=site)
            async with session_scope(engine) as s:
                page2 = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
                site2 = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one()
            await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page2, site=site2)
        finally:
            await fetcher.aclose()
    assert llm.call_count == 1  # cache hit on second crawl
    async with session_scope(engine) as s:
        runs = (await s.execute(select(CrawlRun).order_by(CrawlRun.id))).scalars().all()
        assert len(runs) == 2
        assert runs[1].status == CrawlStatus.ok
        assert runs[1].llm_calls == 0  # short-circuited by unchanged hash
        assert runs[1].changes_detected == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_crawl_page_records_fetch_failure(tmp_path):
    engine = await _init_db(tmp_path)
    # Fixture server returns 500 for anything.

    async def server():
        from aiohttp import web

        app = web.Application()

        async def handler(_req):
            return web.Response(status=500)

        app.router.add_get("/{tail:.*}", handler)
        from aiohttp.test_utils import TestServer

        s = TestServer(app, port=0)
        await s.start_server()
        return s

    srv = await server()
    try:
        fetcher = DefaultFetcher()
        llm = FakeLLMClient()
        site_id, page_id = await _register(engine, str(srv.make_url("/")), str(srv.make_url("/p")))
        try:
            async with session_scope(engine) as s:
                site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one()
                page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
            await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)
        finally:
            await fetcher.aclose()
    finally:
        await srv.close()
    async with session_scope(engine) as s:
        runs = (await s.execute(select(CrawlRun))).scalars().all()
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        assert len(runs) == 1
        assert runs[0].status == CrawlStatus.failed
        assert runs[0].error_text and "500" in runs[0].error_text
        assert page.consecutive_failures == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_crawl_page_applies_backoff_when_extraction_raises_unexpectedly(tmp_path):
    """An SDK-level failure (rate limit, connection error) must still advance next_check_at.

    Otherwise the page stays due and the scheduler re-fetches and re-calls the API
    on every tick.
    """
    engine = await _init_db(tmp_path)

    def _boom(_html, _url, _site):
        raise RuntimeError("simulated anthropic.RateLimitError")

    async with fixture_site(pages={"/p": PAGE}) as fx:
        fetcher = DefaultFetcher()
        llm = FakeLLMClient(on_call=_boom)
        site_id, page_id = await _register(engine, fx.base_url, fx.url("/p"))
        try:
            async with session_scope(engine) as s:
                site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one()
                page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
            result = await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)
        finally:
            await fetcher.aclose()

    assert result.status == CrawlStatus.failed
    async with session_scope(engine) as s:
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
        assert page.consecutive_failures == 1
        assert page.next_check_at is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_crawl_page_survives_and_reports_a_failing_backoff_write(tmp_path):
    """If the backoff write itself fails, log *that* error — not the one that caused it.

    Reusing the outer traceback here would hide the unhealthy-DB stack behind the
    original crawl error, exactly when the real one is needed.
    """
    import structlog

    from yas.crawl import pipeline as pipeline_mod

    engine = await _init_db(tmp_path)

    def _boom(_html, _url, _site):
        raise RuntimeError("ORIGINAL_CRAWL_ERROR")

    async def _failing_backoff(*_args, **_kwargs):
        raise RuntimeError("BACKOFF_WRITE_FAILED")

    async with fixture_site(pages={"/p": PAGE}) as fx:
        fetcher = DefaultFetcher()
        llm = FakeLLMClient(on_call=_boom)
        site_id, page_id = await _register(engine, fx.base_url, fx.url("/p"))
        try:
            async with session_scope(engine) as s:
                site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one()
                page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
            orig = pipeline_mod._apply_failure
            pipeline_mod._apply_failure = _failing_backoff
            try:
                with structlog.testing.capture_logs() as logs:
                    result = await crawl_page(
                        engine=engine, fetcher=fetcher, llm=llm, page=page, site=site
                    )
            finally:
                pipeline_mod._apply_failure = orig
        finally:
            await fetcher.aclose()

    # The crawl still completes rather than propagating into the scheduler.
    assert result.status == CrawlStatus.failed

    backoff_logs = [entry for entry in logs if entry.get("event") == "pipeline.backoff_failed"]
    assert len(backoff_logs) == 1
    assert backoff_logs[0]["error"] == "BACKOFF_WRITE_FAILED"
    # The backoff failure is the primary error; the crawl error that triggered it
    # survives below as chained context, which is worth keeping.
    tb = backoff_logs[0]["traceback"]
    assert tb.rstrip().endswith("RuntimeError: BACKOFF_WRITE_FAILED")
    assert "During handling of the above exception" in tb
    await engine.dispose()


# --- Error reporting ---------------------------------------------------------
# Which crawl failures reach GlitchTip. Expected per-site trouble (a 404) must
# not; failures that mean the page can no longer be read, or that the code is
# broken, must — tagged by site so GlitchTip can filter and break down by it.


async def _crawl(engine, fetcher, llm, site_id, page_id):
    async with session_scope(engine) as s:
        site = (await s.execute(select(Site).where(Site.id == site_id))).scalar_one()
        page = (await s.execute(select(Page).where(Page.id == page_id))).scalar_one()
    return await crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)


def _exception_type(event):
    return event["exception"]["values"][-1]["type"]


@pytest.mark.asyncio
async def test_unexpected_crawl_failure_reports_an_event_tagged_with_the_site(
    tmp_path, sentry_events
):
    engine = await _init_db(tmp_path)

    def _boom(_html, _url, _site):
        raise RuntimeError("reconciler blew up")

    async with fixture_site(pages={"/p": PAGE}) as fx:
        fetcher = DefaultFetcher()
        site_id, page_id = await _register(engine, fx.base_url, fx.url("/p"))
        try:
            await _crawl(engine, fetcher, FakeLLMClient(on_call=_boom), site_id, page_id)
        finally:
            await fetcher.aclose()

    [event] = sentry_events
    assert _exception_type(event) == "RuntimeError"
    assert event["tags"]["site"] == "Test"
    assert event["tags"]["site_id"] == str(site_id)
    assert event["tags"]["page_id"] == str(page_id)
    assert event["contexts"]["crawl"]["page_url"] == fx.url("/p")
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_404_does_not_report(tmp_path, sentry_events):
    """One site's page going away is expected; the in-app crawl_failed alert covers it."""
    engine = await _init_db(tmp_path)
    async with fixture_site(pages={}) as fx:
        fetcher = DefaultFetcher()
        site_id, page_id = await _register(engine, fx.base_url, fx.url("/gone"))
        try:
            result = await _crawl(engine, fetcher, FakeLLMClient(), site_id, page_id)
        finally:
            await fetcher.aclose()

    assert result.status == CrawlStatus.failed
    assert sentry_events == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_extraction_error_reports_a_warning_grouped_per_site(tmp_path, sentry_events):
    """The page could not be read into offerings — the markup-changed case."""
    from yas.llm.client import ExtractionError

    engine = await _init_db(tmp_path)

    def _invalid(_html, _url, _site):
        raise ExtractionError(raw="{}", detail="offerings: field required")

    async with fixture_site(pages={"/p": PAGE}) as fx:
        fetcher = DefaultFetcher()
        site_id, page_id = await _register(engine, fx.base_url, fx.url("/p"))
        try:
            await _crawl(engine, fetcher, FakeLLMClient(on_call=_invalid), site_id, page_id)
        finally:
            await fetcher.aclose()

    [event] = sentry_events
    assert _exception_type(event) == "ExtractionError"
    assert event["level"] == "warning"
    assert event["tags"]["site_id"] == str(site_id)
    # One GlitchTip issue per site, regardless of which page or detail message.
    assert event["fingerprint"] == ["crawl.extraction_failed", str(site_id)]
    await engine.dispose()


@pytest.mark.asyncio
async def test_page_that_suddenly_extracts_nothing_reports_a_warning(tmp_path, sentry_events):
    """A markup change usually yields a *valid* empty extraction, not an error.

    The reconciler then withdraws every offering on the page, which is otherwise
    indistinguishable from "the program list really emptied".
    """
    engine = await _init_db(tmp_path)
    offering = ExtractedOffering(name="Tots Baseball", program_type=ProgramType.multisport)
    async with fixture_site(pages={"/p": PAGE}) as fx:
        fetcher = DefaultFetcher()
        site_id, page_id = await _register(engine, fx.base_url, fx.url("/p"))
        try:
            await _crawl(engine, fetcher, FakeLLMClient(default=[offering]), site_id, page_id)
            assert sentry_events == []

            fx.set_page("/p", "<html><body><div id=app></div></body></html>")
            await _crawl(engine, fetcher, FakeLLMClient(default=[]), site_id, page_id)
        finally:
            await fetcher.aclose()

    [event] = sentry_events
    assert event["level"] == "warning"
    assert "no offerings" in event["message"]
    assert event["tags"]["site_id"] == str(site_id)
    assert event["fingerprint"] == ["crawl.extraction_empty", str(site_id)]
    assert event["extra"]["withdrawn_count"] == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_page_that_never_had_offerings_extracting_nothing_does_not_report(
    tmp_path, sentry_events
):
    engine = await _init_db(tmp_path)
    async with fixture_site(pages={"/p": PAGE}) as fx:
        fetcher = DefaultFetcher()
        site_id, page_id = await _register(engine, fx.base_url, fx.url("/p"))
        try:
            await _crawl(engine, fetcher, FakeLLMClient(default=[]), site_id, page_id)
        finally:
            await fetcher.aclose()

    assert sentry_events == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_failing_backoff_write_reports_its_own_error(tmp_path, sentry_events):
    from yas.crawl import pipeline as pipeline_mod

    engine = await _init_db(tmp_path)

    def _boom(_html, _url, _site):
        raise RuntimeError("ORIGINAL_CRAWL_ERROR")

    async def _failing_backoff(*_args, **_kwargs):
        raise OSError("BACKOFF_WRITE_FAILED")

    async with fixture_site(pages={"/p": PAGE}) as fx:
        fetcher = DefaultFetcher()
        site_id, page_id = await _register(engine, fx.base_url, fx.url("/p"))
        orig = pipeline_mod._apply_failure
        pipeline_mod._apply_failure = _failing_backoff
        try:
            await _crawl(engine, fetcher, FakeLLMClient(on_call=_boom), site_id, page_id)
        finally:
            pipeline_mod._apply_failure = orig
            await fetcher.aclose()

    assert sorted(_exception_type(e) for e in sentry_events) == ["OSError", "RuntimeError"]
    assert all(e["tags"]["site_id"] == str(site_id) for e in sentry_events)
    await engine.dispose()
