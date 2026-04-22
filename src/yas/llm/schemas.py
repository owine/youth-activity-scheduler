"""Pydantic schemas for LLM-extracted offerings.

Strict — `extra="forbid"` so drift in model output surfaces loudly instead of
silently poisoning the `offerings` table. Field names mirror the ORM columns
we can actually extract; location is split into name+address so the reconciler
can get_or_create the Location row."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict

from yas.db.models._types import DayOfWeek, ProgramType


class ExtractedOffering(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    program_type: ProgramType
    start_date: date | None = None
    end_date: date | None = None
    days_of_week: list[DayOfWeek] = []
    time_start: time | None = None
    time_end: time | None = None
    location_name: str | None = None
    location_address: str | None = None
    price_cents: int | None = None
    registration_opens_at: datetime | None = None
    registration_url: str | None = None


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offerings: list[ExtractedOffering]
