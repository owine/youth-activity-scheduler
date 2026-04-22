"""Worker runner — heartbeat + crawl scheduler + daily sweep + geocode
enricher, all concurrent tasks inside one TaskGroup."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings
from yas.crawl.fetcher import DefaultFetcher, Fetcher
from yas.crawl.scheduler import crawl_scheduler_loop
from yas.geo.client import Geocoder, NominatimClient
from yas.geo.enricher import geocode_enricher_loop
from yas.llm.client import AnthropicClient, LLMClient
from yas.logging import get_logger
from yas.worker.heartbeat import beat_once
from yas.worker.sweep import daily_sweep_loop

log = get_logger("yas.worker")


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
    finally:
        if own_fetcher:
            await fetcher.aclose()
        if own_geocoder and hasattr(geocoder, "aclose"):
            await geocoder.aclose()
        log.info("worker.stop")
