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
