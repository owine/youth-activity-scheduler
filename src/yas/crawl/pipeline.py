"""Compose the crawl stages into one end-to-end function + CrawlRun bookkeeping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sentry_sdk
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from yas.alerts.enqueuer import (
    enqueue_crawl_failed,
    enqueue_registration_countdowns,
)
from yas.crawl.extractor import extract
from yas.crawl.fetcher import Fetcher, FetchError
from yas.crawl.reconciler import reconcile
from yas.db.models import CrawlRun, Enrollment, Match, Offering, Page, Site
from yas.db.models._types import CrawlStatus, EnrollmentStatus
from yas.db.session import session_scope
from yas.llm.client import ExtractionError, ExtractionRefused, LLMClient
from yas.logging import get_logger, traceback_tail
from yas.observability import crawl_scope
from yas.unavailability.enrollment_materializer import apply_enrollment_block

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
    except Exception as exc:
        log.error("pipeline.unexpected", error=str(exc), traceback=traceback_tail(exc))
        # Default (stack-based) grouping: a code bug hitting every site is one
        # issue, with the site tag showing which ones.
        sentry_sdk.capture_exception(exc, **crawl_scope(site, page))
        # _do_crawl applies backoff itself on every path it *returns* from, so
        # reaching here means next_check_at was never advanced. Without this the
        # page stays due and the scheduler retries it on every tick — a hot loop
        # that re-fetches and re-calls the LLM API, which is exactly the wrong
        # response to the rate limits and connection errors that land here.
        try:
            await _apply_failure(engine, page, site, error_text=f"unexpected: {exc}")
        except Exception as backoff_exc:
            # Deliberately `backoff_exc`, not `exc` — that is the crawl error we
            # are already handling. This branch means the DB write itself
            # failed, and its own stack is the one worth having.
            log.error(
                "pipeline.backoff_failed",
                page_id=page.id,
                error=str(backoff_exc),
                traceback=traceback_tail(backoff_exc),
            )
            sentry_sdk.capture_exception(backoff_exc, **crawl_scope(site, page))
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
    except ExtractionRefused as exc:
        # The model's safety classifiers declined the page. On youth-activity
        # content that is a false positive, and nothing about the site is broken,
        # so it is handled like ExtractionError: no failure count, no backoff, no
        # crawl_failed alert, normal cadence. It gets its own issue per site so a
        # refusal can't hide inside a "markup changed" issue, since the fix differs.
        log.warning(
            "pipeline.extraction_refused",
            site_id=site.id,
            page_id=page.id,
            category=exc.category,
        )
        scope = crawl_scope(site, page)
        scope["tags"]["refusal_category"] = exc.category or "none"
        sentry_sdk.capture_exception(
            exc,
            level="warning",
            fingerprint=["crawl.extraction_refused", str(site.id)],
            **scope,
        )
        await _apply_next_check(engine, page, site)
        return CrawlResult(
            status=CrawlStatus.failed,
            pages_fetched=1,
            changes_detected=0,
            llm_calls=1,
            llm_cost_usd=exc.cost_usd,
            error_text=f"extraction_refused: category={exc.category}",
        )
    except ExtractionError as exc:
        # The page fetched fine but can't be read into offerings — most often
        # its markup changed. Grouped per site so each broken site is one issue.
        log.warning(
            "pipeline.extraction_failed",
            site_id=site.id,
            page_id=page.id,
            detail=exc.detail[:500],
        )
        sentry_sdk.capture_exception(
            exc,
            level="warning",
            fingerprint=["crawl.extraction_failed", str(site.id)],
            **crawl_scope(site, page),
        )
        await _apply_next_check(engine, page, site)
        return CrawlResult(
            status=CrawlStatus.failed,
            pages_fetched=1,
            changes_detected=0,
            llm_calls=1,
            llm_cost_usd=exc.cost_usd,
            error_text=f"extraction_failed: {exc.detail[:500]}",
        )

    # Local import to avoid a module-level cycle; the matcher imports
    # extractor/reconciler-adjacent types.
    from yas.matching.matcher import rematch_offering

    tick_start = datetime.now(UTC)
    async with session_scope(engine) as s:
        page_row = (await s.execute(select(Page).where(Page.id == page.id))).scalar_one()
        reconcile_result = await reconcile(s, page_row, ex.offerings)
        page_row.content_hash = new_hash
        page_row.last_fetched = datetime.now(UTC)
        page_row.last_changed = datetime.now(UTC)
        page_row.consecutive_failures = 0
        page_row.next_check_at = _schedule_next(site)
        # An update can move an enrolled slot, and the enrollment's
        # unavailability block copies its schedule. Rebuild those blocks, then
        # rematch the kids they belong to, since a block affects every other
        # offering those kids could match. This runs before the per-offering
        # rematch below: otherwise a new offering is matched against the old
        # block, its new_match alert is enqueued, and the kid rematch then
        # deletes the match, orphaning the alert.
        await _refresh_enrollment_blocks(s, reconcile_result.updated)
        # Rematch each new/updated offering in the same session so matches land
        # atomically with the reconcile. Withdrawn offerings don't need a
        # rematch call: reconcile() deletes their match rows, because match
        # readers don't filter on offering status and the sweep skips them.
        for oid in reconcile_result.new + reconcile_result.updated:
            await rematch_offering(s, oid)

        # --- Alert hooks ---
        # new_match and watchlist_hit alerts are enqueued by the rematch above
        # (matcher._alert_match_once: once per kid and offering). The pipeline
        # used to enqueue them again for every match recomputed this tick, so an
        # edit to an already-alerted offering re-sent "New match" once the first
        # alert had been sent. Here: registration countdowns, which an edit may
        # move.
        for oid in reconcile_result.new + reconcile_result.updated:
            offering_row = (
                await s.execute(select(Offering).where(Offering.id == oid))
            ).scalar_one()
            fresh_matches = (
                (
                    await s.execute(
                        select(Match).where(
                            Match.offering_id == oid,
                            Match.computed_at >= tick_start,
                        )
                    )
                )
                .scalars()
                .all()
            )
            # Registration countdown alerts for matched kids.
            # Normalise to UTC-aware for comparison (SQLite may return naive datetimes).
            reg_opens = offering_row.registration_opens_at
            if reg_opens is not None and reg_opens.tzinfo is None:
                reg_opens = reg_opens.replace(tzinfo=UTC)
            if reg_opens is not None and reg_opens > datetime.now(UTC):
                for match in fresh_matches:
                    await enqueue_registration_countdowns(
                        s,
                        offering_id=oid,
                        kid_id=match.kid_id,
                        opens_at=reg_opens,
                    )
        log.info(
            "pipeline.alerts_enqueued",
            site_id=site.id,
            page_id=page.id,
            affected_offerings=len(reconcile_result.new + reconcile_result.updated),
        )

    for oid in reconcile_result.new:
        log.info("offering.new", offering_id=oid, site_id=site.id)
    for oid in reconcile_result.updated:
        log.info("offering.updated", offering_id=oid, site_id=site.id)
    for oid in reconcile_result.withdrawn:
        log.info("offering.withdrawn", offering_id=oid, site_id=site.id)
    log.info("page.changed", page_id=page.id, site_id=site.id, new_hash=new_hash)

    if not ex.offerings and reconcile_result.withdrawn:
        # A markup change more often yields a valid *empty* extraction than an
        # ExtractionError, and the reconcile above has just withdrawn everything
        # the page listed. Nothing else distinguishes that from a program list
        # that really emptied, so say so.
        log.warning(
            "pipeline.extraction_empty",
            site_id=site.id,
            page_id=page.id,
            withdrawn_count=len(reconcile_result.withdrawn),
        )
        sentry_sdk.capture_message(
            f"Page extracted no offerings after listing {len(reconcile_result.withdrawn)}",
            level="warning",
            fingerprint=["crawl.extraction_empty", str(site.id)],
            extras={"withdrawn_count": len(reconcile_result.withdrawn)},
            **crawl_scope(site, page),
        )

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
        if row.consecutive_failures == 3:
            await enqueue_crawl_failed(
                s,
                site_id=site.id,
                consecutive_failures=3,
                last_error=error_text,
            )
            log.warning(
                "pipeline.crawl_failed_alert",
                site_id=site.id,
                page_id=page.id,
                consecutive_failures=3,
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


async def _refresh_enrollment_blocks(session: AsyncSession, offering_ids: list[int]) -> None:
    if not offering_ids:
        return
    from yas.matching.matcher import rematch_kid

    rows = (
        await session.execute(
            select(Enrollment.id, Enrollment.kid_id).where(
                Enrollment.offering_id.in_(offering_ids),
                Enrollment.status == EnrollmentStatus.enrolled.value,
            )
        )
    ).all()
    for enrollment_id, _ in rows:
        await apply_enrollment_block(session, enrollment_id)
    for kid_id in sorted({kid_id for _, kid_id in rows}):
        await rematch_kid(session, kid_id)


def _schedule_next(site: Site) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=site.default_cadence_s)
