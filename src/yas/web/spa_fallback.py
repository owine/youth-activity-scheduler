"""SPA fallback for GET requests not matched by API routes or the assets mount."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def _static_dir() -> Path:
    """Return the static-files root.

    In production this is /app/static (set by the Dockerfile). In tests and
    local dev it can be overridden via YAS_STATIC_DIR.
    """
    return Path(os.environ.get("YAS_STATIC_DIR", "/app/static"))


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

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        return FileResponse(
            static / "index.html",
            headers={"Cache-Control": "no-cache"},
        )
