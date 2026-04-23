"""Worker runner — heartbeat + crawl scheduler + daily sweep + geocode
enricher + alert delivery + digest + detector, all concurrent tasks inside
one TaskGroup."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.alerts.channels.base import Notifier
from yas.alerts.channels.email import EmailChannel
from yas.alerts.channels.ntfy import NtfyChannel
from yas.alerts.channels.pushover import PushoverChannel
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
    """Construct channel notifiers from household config JSON + env secrets.

    For each channel config present in ``household``, attempt to construct
    the corresponding channel object.  If the config is absent (None) the
    channel is skipped.  If the constructor raises ``ValueError`` (e.g.
    a required env-var secret is missing) the channel is logged as disabled
    and skipped.

    The api-only worker path does NOT call this helper; it is only invoked
    when ``settings.alerts_enabled`` is True and a worker is starting.
    """
    notifiers: dict[str, Notifier] = {}

    if household is None:
        return notifiers

    channel_specs: list[tuple[str, dict[str, Any] | None, type[Any]]] = [
        ("email", household.smtp_config_json, EmailChannel),
        ("ntfy", household.ntfy_config_json, NtfyChannel),
        ("pushover", household.pushover_config_json, PushoverChannel),
    ]

    for channel_name, config, channel_cls in channel_specs:
        if config is None:
            continue
        try:
            notifiers[channel_name] = channel_cls(config)
        except ValueError as exc:
            log.warning("channel.disabled", channel=channel_name, reason=str(exc))

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

    # Build notifiers from household config unless the caller already injected them.
    own_notifiers = notifiers is None
    if settings.alerts_enabled and notifiers is None:
        async with session_scope(engine) as s:
            await seed_default_routing(s)
            household = (
                await s.execute(select(HouseholdSettings).limit(1))
            ).scalar_one_or_none()
        notifiers = _build_notifiers(household, settings)

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
                assert notifiers is not None  # guaranteed by the block above
                tg.create_task(alert_delivery_loop(engine, settings, notifiers))
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
