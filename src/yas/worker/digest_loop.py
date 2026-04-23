"""Daily digest loop — builds and enqueues one digest alert per active kid.

Fires once per day at the configured UTC time (``settings.alert_digest_time_utc``).
Respects ``settings.alert_digest_empty_skip``: when True, days with no
actionable content are silently skipped without enqueuing.

Watchlist-hit tracking note: ``DigestPayload`` does not currently surface
watchlist hits as a distinct list.  The empty-day check therefore omits that
condition.  This is a known gap; a future task can extend ``DigestPayload``
with ``watchlist_hits`` and update this check accordingly."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.alerts.digest.builder import gather_digest_payload, render_digest
from yas.alerts.digest.llm_summary import generate_top_line
from yas.alerts.enqueuer import enqueue_digest
from yas.config import Settings
from yas.db.models import HouseholdSettings
from yas.db.models.kid import Kid
from yas.db.session import session_scope
from yas.llm.client import LLMClient
from yas.logging import get_logger
from yas.worker.sweep import _parse_hhmm

log = get_logger("yas.worker.digest")

_DEFAULT_COST_CAP_USD = 1.0


async def daily_digest_loop(
    engine: AsyncEngine,
    settings: Settings,
    llm: LLMClient | None,
) -> None:
    """Every 60 s check whether it is time to send the daily digest.

    At most one run per calendar day; skips days with no actionable content
    when ``settings.alert_digest_empty_skip`` is True.
    """
    target = _parse_hhmm(settings.alert_digest_time_utc)
    last_run: date | None = None
    log.info("digest.start", time_utc=settings.alert_digest_time_utc)
    try:
        while True:
            now = datetime.now(UTC)
            today = now.date()
            if now.time() >= target and last_run != today:
                async with session_scope(engine) as session:
                    kids = (
                        await session.execute(
                            select(Kid).where(Kid.active.is_(True))
                        )
                    ).scalars().all()

                    # Load cost cap from household settings (falls back to default).
                    household = (
                        await session.execute(
                            select(HouseholdSettings).limit(1)
                        )
                    ).scalar_one_or_none()
                    cost_cap = (
                        household.daily_llm_cost_cap_usd
                        if household is not None
                        else _DEFAULT_COST_CAP_USD
                    )

                    for kid in kids:
                        window_start = now - timedelta(hours=24)
                        window_end = now

                        payload = await gather_digest_payload(
                            session,
                            kid,
                            window_start=window_start,
                            window_end=window_end,
                            alert_no_matches_kid_days=settings.alert_no_matches_kid_days,
                            now=now,
                        )

                        # Empty-day skip: omit the digest entirely when there is
                        # nothing to report and the kid is not under the
                        # no-matches threshold.
                        # Checked: new_matches, starting_soon,
                        # registration_calendar, delivery_failures,
                        # silent_schedule_posts (digest-only surface per
                        # routing spec), under_no_matches_threshold.
                        # NOT checked: watchlist_hits (not surfaced by
                        # DigestPayload); site_stagnant_ids (delivered
                        # separately by the detector loop — their absence on
                        # an otherwise-empty day is acceptable).
                        if settings.alert_digest_empty_skip:
                            has_content = (
                                bool(payload.new_matches)
                                or bool(payload.starting_soon)
                                or bool(payload.registration_calendar)
                                or bool(payload.delivery_failures)
                                or bool(payload.silent_schedule_posts)
                                or payload.under_no_matches_threshold
                            )
                            if not has_content:
                                log.debug(
                                    "digest.skipped.empty",
                                    kid_id=kid.id,
                                    kid_name=kid.name,
                                    for_date=today.isoformat(),
                                )
                                continue

                        top_line = await generate_top_line(
                            payload,
                            llm,
                            cost_cap_remaining_usd=cost_cap,
                        )
                        body_plain, body_html = render_digest(payload, top_line)
                        subject = f"Daily digest — {kid.name} — {today.isoformat()}"

                        await enqueue_digest(
                            session,
                            kid_id=kid.id,
                            for_date=today,
                            payload={
                                "subject": subject,
                                "body_plain": body_plain,
                                "body_html": body_html,
                                "top_line": top_line,
                            },
                        )
                        log.info(
                            "digest.enqueued",
                            kid_id=kid.id,
                            kid_name=kid.name,
                            for_date=today.isoformat(),
                        )

                last_run = today
                log.info("digest.ran", kids=len(kids), for_date=today.isoformat())

            await asyncio.sleep(60)
    except asyncio.CancelledError:
        log.info("digest.stop")
        raise
