"""Pydantic models for /api/sites/{id}/crawls."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from yas.web.routes._types import UtcDatetime


class CrawlRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    site_id: int
    started_at: UtcDatetime
    finished_at: UtcDatetime | None
    status: str
    pages_fetched: int
    changes_detected: int
    llm_calls: int
    llm_cost_usd: float
    error_text: str | None
