"""FastAPI app factory."""

from __future__ import annotations

from fastapi import FastAPI, Response
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings, get_settings
from yas.crawl.fetcher import Fetcher
from yas.db.session import create_engine_for
from yas.geo.client import Geocoder
from yas.health import check_readiness
from yas.llm.client import LLMClient
from yas.web.deps import AppState


def create_app(
    engine: AsyncEngine | None = None,
    settings: Settings | None = None,
    *,
    fetcher: Fetcher | None = None,
    llm: LLMClient | None = None,
    geocoder: Geocoder | None = None,
) -> FastAPI:
    app = FastAPI(title="yas", version="0.1.0")
    s = settings or get_settings()
    e = engine or create_engine_for(s.database_url)
    state = AppState(engine=e, settings=s, fetcher=fetcher, llm=llm, geocoder=geocoder)
    app.state.yas = state

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(response: Response) -> dict[str, object]:
        readiness = await check_readiness(state.engine, state.settings.worker_heartbeat_staleness_s)
        response.status_code = 200 if readiness.ready else 503
        return {
            "db_reachable": readiness.db_reachable,
            "heartbeat_fresh": readiness.heartbeat_fresh,
            "heartbeat_age_s": readiness.heartbeat_age_s,
        }

    from yas.web.routes import (
        enrollments_router,
        household_router,
        kids_router,
        sites_router,
        unavailability_router,
        watchlist_router,
    )

    app.include_router(sites_router)
    app.include_router(household_router)
    app.include_router(kids_router)
    app.include_router(watchlist_router)
    app.include_router(unavailability_router)
    app.include_router(enrollments_router)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await state.engine.dispose()

    return app
