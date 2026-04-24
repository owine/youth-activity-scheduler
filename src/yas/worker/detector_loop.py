"""Daily detector loop — runs stagnant-site and no-matches-kid detectors.

Fires once per day at the configured UTC time
(``settings.alert_detector_time_utc``) and enqueues one alert per detected
anomaly."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.alerts.detectors.no_matches_for_kid import detect_kids_without_matches
from yas.alerts.detectors.site_stagnant import detect_stagnant_sites
from yas.alerts.enqueuer import enqueue_no_matches_for_kid, enqueue_site_stagnant
from yas.config import Settings
from yas.db.session import session_scope
from yas.logging import get_logger
from yas.worker.sweep import _parse_hhmm

log = get_logger("yas.worker.detector")


async def daily_detector_loop(
    engine: AsyncEngine,
    settings: Settings,
) -> None:
    """Every 60 s check whether it is time to run the detector sweep.

    At most one run per calendar day.
    """
    target = _parse_hhmm(settings.alert_detector_time_utc)
    last_run: date | None = None
    log.info("detector.start", time_utc=settings.alert_detector_time_utc)
    try:
        while True:
            now = datetime.now(UTC)
            today = now.date()
            if now.time() >= target and last_run != today:
                async with session_scope(engine) as session:
                    stagnant_ids = await detect_stagnant_sites(
                        session,
                        threshold_days=settings.alert_stagnant_site_days,
                        now=now,
                    )
                    for site_id in stagnant_ids:
                        await enqueue_site_stagnant(
                            session,
                            site_id=site_id,
                            days_silent=settings.alert_stagnant_site_days,
                        )
                    if stagnant_ids:
                        log.info(
                            "detector.stagnant_sites",
                            count=len(stagnant_ids),
                        )

                    kid_ids = await detect_kids_without_matches(
                        session,
                        threshold_days=settings.alert_no_matches_kid_days,
                        now=now,
                    )
                    for kid_id in kid_ids:
                        await enqueue_no_matches_for_kid(
                            session,
                            kid_id=kid_id,
                            days_since_created=settings.alert_no_matches_kid_days,
                        )
                    if kid_ids:
                        log.info(
                            "detector.no_matches_kids",
                            count=len(kid_ids),
                        )

                last_run = today
                log.info(
                    "detector.ran",
                    stagnant_sites=len(stagnant_ids),
                    no_matches_kids=len(kid_ids),
                    for_date=today.isoformat(),
                )

            await asyncio.sleep(60)
    except asyncio.CancelledError:
        log.info("detector.stop")
        raise
