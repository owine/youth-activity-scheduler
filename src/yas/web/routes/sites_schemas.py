"""Pydantic models for the /api/sites endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class PageIn(BaseModel):
    url: HttpUrl
    kind: str = "schedule"


class PageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    url: str
    kind: str
    content_hash: str | None = None
    last_fetched: datetime | None = None
    next_check_at: datetime | None = None


class SiteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    base_url: HttpUrl
    needs_browser: bool = False
    default_cadence_s: int = 6 * 3600
    crawl_hints: dict[str, Any] = {}
    pages: list[PageIn] = []


class SiteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool | None = None
    muted_until: datetime | None = None
    default_cadence_s: int | None = None
    needs_browser: bool | None = None
    crawl_hints: dict[str, Any] | None = None


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    base_url: str
    adapter: str
    needs_browser: bool
    active: bool
    default_cadence_s: int
    muted_until: datetime | None
    pages: list[PageOut] = []
