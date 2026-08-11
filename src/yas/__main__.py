"""CLI entrypoint: `python -m yas {api|worker|all}`."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Coroutine
from typing import Any

import uvicorn

from yas.config import get_settings
from yas.db.session import create_engine_for
from yas.logging import configure_logging, get_logger
from yas.web.app import create_app
from yas.worker.runner import run_worker


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="yas", description="Youth Activity Scheduler")
    p.add_argument(
        "mode",
        choices=["api", "worker", "all", "migrate"],
        help="which process to run: api (FastAPI), worker (crawler+alerts), all (both), migrate (apply schema and exit)",
    )
    return p


async def _supervise(
    server_coro: Coroutine[Any, Any, Any],
    worker_coro: Coroutine[Any, Any, Any],
) -> None:
    """Run the API server and the worker as siblings; either dying kills both.

    In the two-container layout a worker crash exited its container and the
    restart policy revived it. Collapsed into one container we need the same
    outcome, so a TaskGroup is used rather than a bare create_task: it cancels
    the surviving sibling and re-raises, the process exits non-zero, and Docker
    restarts the container. A bare create_task would leave a dead worker
    unobserved behind a healthy-looking API — visible only as /readyz reporting
    heartbeat_fresh: false, with nothing to act on it.
    """
    async with asyncio.TaskGroup() as tg:
        tg.create_task(server_coro)
        tg.create_task(worker_coro)


async def _run_all(settings, engine) -> None:  # type: ignore[no-untyped-def]
    """Run worker in a task alongside uvicorn in-process. One fetcher, one LLM
    client, and one geocoder are constructed at startup and shared across the
    api and worker."""
    from yas.crawl.fetcher import DefaultFetcher
    from yas.geo.client import NominatimClient
    from yas.llm.client import AnthropicClient

    fetcher = DefaultFetcher()
    llm = AnthropicClient(api_key=settings.anthropic_api_key, model=settings.llm_extraction_model)
    geocoder = NominatimClient(min_interval_s=settings.geocode_nominatim_min_interval_s)
    try:
        config = uvicorn.Config(
            create_app(
                engine=engine,
                settings=settings,
                fetcher=fetcher,
                llm=llm,
                geocoder=geocoder,
            ),
            host=settings.host,
            port=settings.port,
            log_config=None,
        )
        server = uvicorn.Server(config)
        await _supervise(
            server.serve(),
            run_worker(engine, settings, fetcher=fetcher, llm=llm, geocoder=geocoder),
        )
    finally:
        await fetcher.aclose()
        await geocoder.aclose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(level=settings.log_level)
    log = get_logger("yas.main")

    from yas.db.migrations import upgrade_to_head

    upgrade_to_head(settings.database_url)

    if args.mode == "migrate":
        log.info("mode.migrate.done")
        return 0

    engine = create_engine_for(settings.database_url)

    if args.mode == "api":
        log.info("mode.api", host=settings.host, port=settings.port)
        # Construct the API-side LLM and geocoder so endpoints that need them
        # (e.g. /api/sites/{id}/discover, /api/household immediate-geocode)
        # work in api-only mode. The worker has its own instances in worker mode.
        from yas.geo.client import NominatimClient
        from yas.llm.client import AnthropicClient

        api_llm = AnthropicClient(
            api_key=settings.anthropic_api_key,
            model=settings.llm_extraction_model,
        )
        api_geocoder = NominatimClient(
            min_interval_s=settings.geocode_nominatim_min_interval_s,
        )
        uvicorn.run(
            create_app(
                engine=engine,
                settings=settings,
                llm=api_llm,
                geocoder=api_geocoder,
            ),
            host=settings.host,
            port=settings.port,
            log_config=None,
        )
    elif args.mode == "worker":
        log.info("mode.worker")
        asyncio.run(run_worker(engine, settings))
    elif args.mode == "all":
        log.info("mode.all")
        asyncio.run(_run_all(settings, engine))
    return 0


if __name__ == "__main__":
    sys.exit(main())
