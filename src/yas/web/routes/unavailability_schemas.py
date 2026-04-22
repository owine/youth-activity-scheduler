"""Pydantic models for /api/kids/{id}/unavailability endpoints."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

_ALLOWED_SOURCES = {"manual", "custom"}


class UnavailabilityCreate(BaseModel):
    """Create a manual/custom unavailability block via the CRUD endpoint.

    Only `manual` and `custom` sources are accepted here. School and
    enrollment blocks are derived from their sources of truth and must be
    edited via /api/kids/{id} or /api/enrollments/{id} respectively."""

    model_config = ConfigDict(extra="forbid")
    source: str = "manual"
    label: str | None = None
    days_of_week: list[str] = Field(default_factory=list)
    time_start: time | None = None
    time_end: time | None = None
    date_start: date | None = None
    date_end: date | None = None
    active: bool = True


class UnavailabilityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = None
    days_of_week: list[str] | None = None
    time_start: time | None = None
    time_end: time | None = None
    date_start: date | None = None
    date_end: date | None = None
    active: bool | None = None


class UnavailabilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kid_id: int
    source: str
    label: str | None
    days_of_week: list[str]
    time_start: time | None
    time_end: time | None
    date_start: date | None
    date_end: date | None
    source_enrollment_id: int | None
    active: bool
    created_at: datetime
