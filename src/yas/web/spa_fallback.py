"""SPA fallback for GET requests not matched by API routes or the assets mount."""

from __future__ import annotations

import html
import os
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from yas.config import Settings
from yas.observability import browser_sentry_dsn


def _static_dir() -> Path:
    """Return the static-files root.

    In production this is /app/static (set by the Dockerfile). In tests and
    local dev it can be overridden via YAS_STATIC_DIR.
    """
    return Path(os.environ.get("YAS_STATIC_DIR", "/app/static"))


def _sentry_meta(settings: Settings) -> str:
    """<meta> tags handing the SPA its Sentry config, or "" when browser reporting is off.

    Rendered at request time rather than inlined by Vite so one published image
    serves any deployment (frontend/src/lib/sentry.ts reads them).
    """
    dsn = browser_sentry_dsn(settings.sentry_browser_dsn)
    if dsn is None:
        return ""
    tags = [
        f'<meta name="sentry-browser-dsn" content="{html.escape(dsn)}">',
        f'<meta name="sentry-environment" content="{html.escape(settings.sentry_environment)}">',
    ]
    if settings.git_sha != "unknown":
        tags.append(f'<meta name="sentry-release" content="{html.escape(settings.git_sha)}">')
    return "".join(tags)


def install_spa_fallback(app: FastAPI) -> None:
    """Mount /assets, install API 404 guard, add SPA catch-all. MUST be called LAST in app setup."""
    static = _static_dir()

    if (static / "assets").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets", html=False), name="assets")

    # API 404 guard: registered BEFORE the SPA catch-all so unknown /api/*
    # paths return JSON 404 instead of being swallowed by the SPA fallback.
    # Without this, /api/nonexistent would match /{full_path:path} and return
    # index.html with status 200.
    @app.get("/api/{path:path}", include_in_schema=False)
    async def api_not_found(path: str) -> JSONResponse:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    sentry_meta = _sentry_meta(app.state.yas.settings)
    index_with_meta: str | None = None

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> Response:
        nonlocal index_with_meta
        headers = {"Cache-Control": "no-cache"}
        if not sentry_meta:
            return FileResponse(static / "index.html", headers=headers)
        if index_with_meta is None:
            # index.html is immutable within an image, so render it once.
            index = (static / "index.html").read_text(encoding="utf-8")
            index_with_meta = index.replace("</head>", f"{sentry_meta}</head>", 1)
        return HTMLResponse(index_with_meta, headers=headers)
