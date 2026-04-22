"""Worker runner — heartbeat loop + crawl scheduler loop in a TaskGroup."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings
from yas.crawl.fetcher import DefaultFetcher, Fetcher
from yas.crawl.scheduler import crawl_scheduler_loop
from yas.llm.client import AnthropicClient, LLMClient
from yas.logging import get_logger
from yas.worker.heartbeat import beat_once

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
) -> None:
    own_fetcher = fetcher is None
    fetcher = fetcher or DefaultFetcher()
    llm = llm or AnthropicClient(
        api_key=settings.anthropic_api_key,
        model=settings.llm_extraction_model,
    )
    log.info("worker.start")
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_heartbeat_loop(engine, settings))
            if settings.crawl_scheduler_enabled:
                tg.create_task(
                    crawl_scheduler_loop(engine=engine, settings=settings, fetcher=fetcher, llm=llm)
                )
    finally:
        if own_fetcher:
            await fetcher.aclose()
        log.info("worker.stop")
