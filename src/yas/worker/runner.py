"""Worker runner — heartbeat + crawl scheduler + daily sweep + geocode
enricher + alert delivery + digest + detector, all concurrent tasks inside
one TaskGroup."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.alerts.channels.base import Notifier
from yas.alerts.routing import seed_default_routing
from yas.config import Settings
from yas.crawl.fetcher import DefaultFetcher, Fetcher
from yas.crawl.scheduler import crawl_scheduler_loop
from yas.db.models import HouseholdSettings
from yas.db.session import session_scope
from yas.geo.client import Geocoder, NominatimClient
from yas.geo.enricher import geocode_enricher_loop
from yas.llm.client import AnthropicClient, LLMClient
from yas.logging import get_logger
from yas.worker.delivery_loop import alert_delivery_loop
from yas.worker.detector_loop import daily_detector_loop
from yas.worker.digest_loop import daily_digest_loop
from yas.worker.heartbeat import beat_once
from yas.worker.sweep import daily_sweep_loop

log = get_logger("yas.worker")


def _build_notifiers(
    household: HouseholdSettings | None,
    settings: Settings,
) -> dict[str, Notifier]:
    """Backwards-compat shim that delegates to the shared builder.

    Kept so external callers don't break; new code should import from
    ``yas.alerts.notifier_builder`` directly. The delivery loop now
    rebuilds notifiers per tick rather than relying on a startup-time
    snapshot, so saving config in Settings takes effect within ~60s
    without a worker restart.
    """
    from yas.alerts.notifier_builder import build_notifiers, log_constructed

    notifiers = build_notifiers(household, settings)
    log_constructed(notifiers)
    return notifiers


async def _heartbeat_loop(engine: AsyncEngine, settings: Settings) -> None:
    log.info("heartbeat.start", interval_s=settings.worker_heartbeat_interval_s)
    try:
        while True:
            ts = await beat_once(engine)
            log.debug("worker.heartbeat", ts=ts.isoformat())
            await asyncio.sleep(settings.worker_heartbeat_interval_s)
    except asyncio.CancelledError:
        log.info("heartbeat.stop")
        raise


async def run_worker(
    engine: AsyncEngine,
    settings: Settings,
    *,
    fetcher: Fetcher | None = None,
    llm: LLMClient | None = None,
    geocoder: Geocoder | None = None,
    notifiers: dict[str, Notifier] | None = None,
) -> None:
    own_fetcher = fetcher is None
    own_geocoder = geocoder is None
    fetcher = fetcher or DefaultFetcher()
    llm = llm or AnthropicClient(
        api_key=settings.anthropic_api_key,
        model=settings.llm_extraction_model,
    )
    geocoder = geocoder or NominatimClient(
        min_interval_s=settings.geocode_nominatim_min_interval_s,
    )

    # Seed alert routing once at startup; notifiers are now built per
    # tick inside alert_delivery_loop so config changes take effect
    # without requiring a worker restart.
    if settings.alerts_enabled:
        async with session_scope(engine) as s:
            await seed_default_routing(s)
    own_notifiers = notifiers is None

    log.info("worker.start")
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_heartbeat_loop(engine, settings))
            if settings.crawl_scheduler_enabled:
                tg.create_task(
                    crawl_scheduler_loop(engine=engine, settings=settings, fetcher=fetcher, llm=llm)
                )
            if settings.sweep_enabled:
                tg.create_task(daily_sweep_loop(engine, settings))
            if settings.geocode_enabled:
                tg.create_task(
                    geocode_enricher_loop(engine=engine, settings=settings, geocoder=geocoder)
                )
            if settings.alerts_enabled:
                tg.create_task(alert_delivery_loop(engine, settings))
                tg.create_task(daily_digest_loop(engine, settings, llm))
                tg.create_task(daily_detector_loop(engine, settings))
    finally:
        if own_fetcher:
            await fetcher.aclose()
        if own_geocoder and hasattr(geocoder, "aclose"):
            await geocoder.aclose()
        if own_notifiers and notifiers is not None:
            for n in notifiers.values():
                await n.aclose()
        log.info("worker.stop")
