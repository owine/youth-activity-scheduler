"""Shared FastAPI dependencies."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from yas.config import Settings
from yas.crawl.fetcher import Fetcher
from yas.llm.client import LLMClient


class AppState:
    def __init__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        fetcher: Fetcher | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.fetcher = fetcher
        self.llm = llm
