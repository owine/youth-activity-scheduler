"""Pydantic models for /api/sites/{id}/discover."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)
    max_candidates: int | None = Field(default=None, ge=1, le=50)


class CandidateOut(BaseModel):
    url: str
    title: str
    kind: Literal["html", "pdf"]
    score: float
    reason: str


class DiscoveryStatsOut(BaseModel):
    sitemap_urls: int
    link_urls: int
    filtered_junk: int
    fetched_heads: int
    classified: int
    returned: int


class DiscoveryResultOut(BaseModel):
    site_id: int
    seed_url: str
    stats: DiscoveryStatsOut
    candidates: list[CandidateOut]
