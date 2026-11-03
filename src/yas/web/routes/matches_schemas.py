"""Pydantic models for the read-only /api/matches endpoint."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict

from yas.web.routes._types import UtcDatetime


class OfferingSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    program_type: str
    age_min: int | None
    age_max: int | None
    start_date: date | None
    end_date: date | None
    days_of_week: list[str]
    attends_one_day: bool = False
    time_start: time | None
    time_end: time | None
    price_cents: int | None
    registration_url: str | None
    site_id: int
    # Deliberately plain datetime: the LLM extracts this as a naive wall-clock
    # time in the site's own zone (often T00:00 for a date-only "opens Mar 1"),
    # so reading it as UTC would move it to the previous evening in the US.
    registration_opens_at: datetime | None = None
    site_name: str
    muted_until: UtcDatetime | None = None
    location_lat: float | None = None
    location_lon: float | None = None


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    kid_id: int
    offering_id: int
    score: float
    reasons: dict[str, Any]
    computed_at: UtcDatetime
    offering: OfferingSummary
