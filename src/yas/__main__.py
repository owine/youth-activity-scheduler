"""CLI entrypoint: `python -m yas {api|worker|all}`."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys

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
        choices=["api", "worker", "all"],
        help="which process to run: api (FastAPI), worker (crawler+alerts), all (both)",
    )
    return p


async def _run_all(settings, engine) -> None:  # type: ignore[no-untyped-def]
    """Run worker in a task alongside uvicorn in-process."""
    config = uvicorn.Config(
        create_app(engine=engine, settings=settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
    )
    server = uvicorn.Server(config)
    worker_task = asyncio.create_task(run_worker(engine, settings))
    try:
        await server.serve()
    finally:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(level=settings.log_level)
    log = get_logger("yas.main")
    engine = create_engine_for(settings.database_url)

    if args.mode == "api":
        log.info("mode.api", host=settings.host, port=settings.port)
        uvicorn.run(
            create_app(engine=engine, settings=settings),
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
