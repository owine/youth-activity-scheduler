"""Compose the crawl stages into one end-to-end function + CrawlRun bookkeeping."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.crawl.extractor import extract
from yas.crawl.fetcher import Fetcher, FetchError
from yas.crawl.reconciler import reconcile
from yas.db.models import CrawlRun, Page, Site
from yas.db.models._types import CrawlStatus
from yas.db.session import session_scope
from yas.llm.client import ExtractionError, LLMClient
from yas.logging import get_logger

log = get_logger("yas.crawl.pipeline")

_MAX_BACKOFF_MULTIPLIER = 4


@dataclass(frozen=True)
class CrawlResult:
    status: CrawlStatus
    pages_fetched: int
    changes_detected: int
    llm_calls: int
    llm_cost_usd: float
    error_text: str | None


async def crawl_page(
    *,
    engine: AsyncEngine,
    fetcher: Fetcher,
    llm: LLMClient,
    page: Page,
    site: Site,
) -> CrawlResult:
    started = datetime.now(UTC)

    async with session_scope(engine) as s:
        run = CrawlRun(site_id=site.id, started_at=started, status=CrawlStatus.ok)
        s.add(run)
        await s.flush()
        run_id = run.id

    try:
        result = await _do_crawl(engine=engine, fetcher=fetcher, llm=llm, page=page, site=site)
    except Exception as exc:  # pragma: no cover — defensive
        tb = traceback.format_exc()
        log.error("pipeline.unexpected", error=str(exc), traceback=tb[:2000])
        result = CrawlResult(
            status=CrawlStatus.failed,
            pages_fetched=0,
            changes_detected=0,
            llm_calls=0,
            llm_cost_usd=0.0,
            error_text=f"unexpected: {exc}",
        )

    # Finalize the run row.
    finished = datetime.now(UTC)
    async with session_scope(engine) as s:
        run = (await s.execute(select(CrawlRun).where(CrawlRun.id == run_id))).scalar_one()
        run.finished_at = finished
        run.status = result.status
        run.pages_fetched = result.pages_fetched
        run.changes_detected = result.changes_detected
        run.llm_calls = result.llm_calls
        run.llm_cost_usd = result.llm_cost_usd
        run.error_text = result.error_text

    return result


async def _do_crawl(
    *,
    engine: AsyncEngine,
    fetcher: Fetcher,
    llm: LLMClient,
    page: Page,
    site: Site,
) -> CrawlResult:
    try:
        fetched = await fetcher.fetch(page, site)
    except FetchError as exc:
        await _apply_failure(engine, page, site, error_text=str(exc))
        return CrawlResult(
            status=CrawlStatus.failed,
            pages_fetched=0,
            changes_detected=0,
            llm_calls=0,
            llm_cost_usd=0.0,
            error_text=str(exc),
        )

    # Short-circuit when content hasn't changed.
    from yas.crawl.change_detector import content_hash, normalize

    new_hash = content_hash(normalize(fetched.html))
    if page.content_hash is not None and page.content_hash == new_hash:
        await _apply_unchanged(engine, page, site)
        return CrawlResult(
            status=CrawlStatus.ok,
            pages_fetched=1,
            changes_detected=0,
            llm_calls=0,
            llm_cost_usd=0.0,
            error_text=None,
        )

    # Extract + reconcile.
    try:
        ex = await extract(
            engine=engine, llm=llm, html=fetched.html, url=fetched.url, site_name=site.name
        )
    except ExtractionError as exc:
        await _apply_next_check(engine, page, site)
        return CrawlResult(
            status=CrawlStatus.failed,
            pages_fetched=1,
            changes_detected=0,
            llm_calls=1,
            llm_cost_usd=0.0,
            error_text=f"extraction_failed: {exc.detail[:500]}",
        )

    # Local import to avoid a module-level cycle; the matcher imports
    # extractor/reconciler-adjacent types.
    from yas.matching.matcher import rematch_offering

    async with session_scope(engine) as s:
        page_row = (await s.execute(select(Page).where(Page.id == page.id))).scalar_one()
        reconcile_result = await reconcile(s, page_row, ex.offerings)
        page_row.content_hash = new_hash
        page_row.last_fetched = datetime.now(UTC)
        page_row.last_changed = datetime.now(UTC)
        page_row.consecutive_failures = 0
        page_row.next_check_at = _schedule_next(site)
        # Rematch each new/updated offering in the same session so matches land
        # atomically with the reconcile. Withdrawn offerings don't need a
        # rematch call — they're filtered out by the matcher's active status
        # check and any stale match rows become invisible on read.
        for oid in reconcile_result.new + reconcile_result.updated:
            await rematch_offering(s, oid)

    for oid in reconcile_result.new:
        log.info("offering.new", offering_id=oid, site_id=site.id)
    for oid in reconcile_result.updated:
        log.info("offering.updated", offering_id=oid, site_id=site.id)
    for oid in reconcile_result.withdrawn:
        log.info("offering.withdrawn", offering_id=oid, site_id=site.id)
    log.info("page.changed", page_id=page.id, site_id=site.id, new_hash=new_hash)

    changes = (
        len(reconcile_result.new) + len(reconcile_result.updated) + len(reconcile_result.withdrawn)
    )
    return CrawlResult(
        status=CrawlStatus.ok,
        pages_fetched=1,
        changes_detected=changes,
        llm_calls=0 if ex.from_cache else 1,
        llm_cost_usd=ex.cost_usd,
        error_text=None,
    )


async def _apply_failure(engine: AsyncEngine, page: Page, site: Site, *, error_text: str) -> None:
    async with session_scope(engine) as s:
        row = (await s.execute(select(Page).where(Page.id == page.id))).scalar_one()
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
        row.last_fetched = datetime.now(UTC)
        backoff_mul = min(2**row.consecutive_failures, _MAX_BACKOFF_MULTIPLIER)
        row.next_check_at = datetime.now(UTC) + timedelta(
            seconds=site.default_cadence_s * backoff_mul
        )


async def _apply_unchanged(engine: AsyncEngine, page: Page, site: Site) -> None:
    async with session_scope(engine) as s:
        row = (await s.execute(select(Page).where(Page.id == page.id))).scalar_one()
        row.last_fetched = datetime.now(UTC)
        row.consecutive_failures = 0
        row.next_check_at = _schedule_next(site)


async def _apply_next_check(engine: AsyncEngine, page: Page, site: Site) -> None:
    async with session_scope(engine) as s:
        row = (await s.execute(select(Page).where(Page.id == page.id))).scalar_one()
        row.last_fetched = datetime.now(UTC)
        row.next_check_at = _schedule_next(site)


def _schedule_next(site: Site) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=site.default_cadence_s)
