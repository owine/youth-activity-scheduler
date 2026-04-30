"""Pydantic models for GET /api/kids/{kid_id}/calendar."""

from __future__ import annotations

from datetime import date, time
from typing import Literal

from pydantic import BaseModel, Field


class CalendarEventOut(BaseModel):
    id: str
    kind: Literal["enrollment", "unavailability", "match"]
    date: date
    time_start: time | None = None
    time_end: time | None = None
    all_day: bool
    title: str
    enrollment_id: int | None = None
    offering_id: int | None = None
    location_id: int | None = None
    status: str | None = None
    block_id: int | None = None
    source: str | None = None
    from_enrollment_id: int | None = None
    score: float | None = None
    registration_url: str | None = None


class KidCalendarOut(BaseModel):
    """Python's `from` keyword conflict resolved via Pydantic alias.

    `from_` is the Python attribute; FastAPI emits `from` on the wire
    because the route handler uses `response_model_by_alias=True`.
    """

    model_config = {"populate_by_name": True}

    kid_id: int
    from_: date = Field(alias="from")
    to: date
    events: list[CalendarEventOut]
