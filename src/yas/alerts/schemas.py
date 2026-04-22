"""Pydantic payload shapes for each AlertType.

Each AlertType has a small schema describing what goes into alerts.payload_json.
These are used by the enqueuer for validation + by the delivery-worker renderers
as structured inputs to channel message templates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewMatchPayload(_Base):
    score: float
    reasons: dict[str, Any]


class WatchlistHitPayload(_Base):
    watchlist_entry_id: int
    reasons: dict[str, Any]


class RegOpensPayload(_Base):
    opens_at: datetime
    offering_name: str
    registration_url: str | None = None


class SchedulePostedPayload(_Base):
    summary: str | None = None


class CrawlFailedPayload(_Base):
    consecutive_failures: int
    last_error: str


class SiteStagnantPayload(_Base):
    site_name: str
    days_silent: int


class NoMatchesForKidPayload(_Base):
    kid_name: str
    days_since_created: int


class DigestPayload(_Base):
    subject: str
    body_plain: str
    body_html: str | None = None
