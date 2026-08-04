"""Poll for due pages and dispatch them through the pipeline."""

from __future__ import annotations

import asyncio
import traceback
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings
from yas.crawl.fetcher import Fetcher
from yas.crawl.pipeline import crawl_page
from yas.db.models import Page, Site
from yas.db.session import session_scope
from yas.llm.client import LLMClient
from yas.logging import get_logger

log = get_logger("yas.crawl.scheduler")


async def crawl_scheduler_loop(
    *,
    engine: AsyncEngine,
    settings: Settings,
    fetcher: Fetcher,
    llm: LLMClient,
) -> None:
    """Forever: every tick, find due pages, run them, await completion."""
    log.info(
        "scheduler.start",
        tick_s=settings.crawl_scheduler_tick_s,
        batch_size=settings.crawl_scheduler_batch_size,
    )
    try:
        while True:
            await _tick(engine=engine, settings=settings, fetcher=fetcher, llm=llm)
            await asyncio.sleep(settings.crawl_scheduler_tick_s)
    except asyncio.CancelledError:
        log.info("scheduler.stop")
        raise


async def _tick(
    *,
    engine: AsyncEngine,
    settings: Settings,
    fetcher: Fetcher,
    llm: LLMClient,
) -> None:
    now = datetime.now(UTC)
    async with session_scope(engine) as s:
        rows = (
            await s.execute(
                select(Page, Site)
                .join(Site, Page.site_id == Site.id)
                .where(
                    Site.active.is_(True),
                    or_(Site.muted_until.is_(None), Site.muted_until < now),
                    or_(Page.next_check_at.is_(None), Page.next_check_at <= now),
                )
                .order_by(Page.next_check_at.nulls_first())
                .limit(settings.crawl_scheduler_batch_size)
            )
        ).all()
        # Detach so we can use across sessions without lazy-load surprises.
        s.expunge_all()

    if not rows:
        return

    log.info("scheduler.tick", due=len(rows))
    tasks = [
        asyncio.create_task(
            crawl_page(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)
        )
        for page, site in rows
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # return_exceptions keeps one bad page from cancelling its siblings, but the
    # results must still be inspected — discarding them means an exception that
    # escapes crawl_page (its run-finalizing writes sit outside the internal
    # try) disappears with no log and no traceback.
    for (page, _site), result in zip(rows, results, strict=True):
        if isinstance(result, BaseException):
            log.error(
                "scheduler.page_failed",
                page_id=page.id,
                # Logged apart from the message because str(exc) is empty for
                # some exceptions — httpx timeouts among them — leaving the type
                # as the only identifying detail. It also aggregates cleanly.
                error_type=type(result).__name__,
                error=str(result),
                traceback="".join(
                    traceback.format_exception(type(result), result, result.__traceback__)
                )[:2000],
            )
