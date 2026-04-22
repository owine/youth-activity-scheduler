"""Shared FastAPI dependencies."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings


class AppState:
    def __init__(self, engine: AsyncEngine, settings: Settings) -> None:
        self.engine = engine
        self.settings = settings
