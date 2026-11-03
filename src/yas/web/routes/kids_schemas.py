"""Pydantic models for the /api/kids endpoints."""

from __future__ import annotations

from datetime import date, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yas.web.routes._types import UtcDatetime
from yas.web.routes.watchlist_schemas import WatchlistCreate


class UnavailabilityCreate(BaseModel):
    """Minimal inline nested create for atomic kid-create.

    Only manual/custom sources are allowed via this path — school and
    enrollment blocks are materialized by dedicated services.
    """

    model_config = ConfigDict(extra="forbid")
    source: str = "manual"
    label: str | None = None
    days_of_week: list[str] = Field(default_factory=list)
    time_start: time | None = None
    time_end: time | None = None
    date_start: date | None = None
    date_end: date | None = None
    active: bool = True


class SchoolYearRange(BaseModel):
    """One school-year span; stored on the kid as {"start": ISO, "end": ISO}."""

    model_config = ConfigDict(extra="forbid")
    start: date
    end: date

    @model_validator(mode="after")
    def _end_not_before_start(self) -> SchoolYearRange:
        if self.end < self.start:
            raise ValueError("end must not be before start")
        return self


def school_year_ranges_json(ranges: list[SchoolYearRange] | None) -> list[dict[str, Any]] | None:
    """The stored JSON shape, which the materializer parses with date.fromisoformat."""
    if ranges is None:
        return None
    return [r.model_dump(mode="json") for r in ranges]


__all__ = [
    "KidCreate",
    "KidDetailOut",
    "KidOut",
    "KidUpdate",
    "SchoolYearRange",
    "UnavailabilityCreate",
    "WatchlistCreate",
]


class KidCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    dob: date
    interests: list[str] = Field(default_factory=list)
    availability: dict[str, Any] = Field(default_factory=dict)
    max_distance_mi: float | None = None
    max_drive_minutes: int | None = None
    alert_score_threshold: float = 0.6
    alert_on: dict[str, Any] = Field(default_factory=dict)
    school_weekdays: list[str] = Field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
    school_time_start: time | None = None
    school_time_end: time | None = None
    school_year_ranges: list[SchoolYearRange] = Field(default_factory=list)
    school_holidays: list[str] = Field(default_factory=list)
    notes: str | None = None
    active: bool = True
    # Nested atomic-create arrays
    unavailability: list[UnavailabilityCreate] = Field(default_factory=list)
    watchlist: list[WatchlistCreate] = Field(default_factory=list)


class KidUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    dob: date | None = None
    interests: list[str] | None = None
    availability: dict[str, Any] | None = None
    max_distance_mi: float | None = None
    max_drive_minutes: int | None = None
    alert_score_threshold: float | None = None
    alert_on: dict[str, Any] | None = None
    school_weekdays: list[str] | None = None
    school_time_start: time | None = None
    school_time_end: time | None = None
    school_year_ranges: list[SchoolYearRange] | None = None
    school_holidays: list[str] | None = None
    notes: str | None = None
    active: bool | None = None

    # Omitted means "unchanged", so these are optional here, but their columns
    # are NOT NULL: an explicit null would otherwise reach the DB and 500.
    @field_validator("name", "dob", "active", "alert_score_threshold")
    @classmethod
    def _not_null(cls, v: object) -> object:
        if v is None:
            raise ValueError("may not be null")
        return v


class KidOut(BaseModel):
    """Brief kid row for list endpoints."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    dob: date
    interests: list[str]
    active: bool


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


class WatchlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kid_id: int
    site_id: int | None
    pattern: str
    priority: str
    notes: str | None
    active: bool
    ignore_hard_gates: bool


class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kid_id: int
    offering_id: int
    status: str
    enrolled_at: UtcDatetime | None
    notes: str | None


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    kid_id: int
    offering_id: int
    score: float
    reasons: dict[str, Any]
    computed_at: UtcDatetime


class KidDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    dob: date
    interests: list[str]
    availability: dict[str, Any]
    max_distance_mi: float | None
    max_drive_minutes: int | None = None
    alert_score_threshold: float
    alert_on: dict[str, Any]
    school_weekdays: list[str]
    school_time_start: time | None
    school_time_end: time | None
    school_year_ranges: list[dict[str, Any]]
    school_holidays: list[str]
    notes: str | None
    active: bool
    unavailability: list[UnavailabilityOut] = Field(default_factory=list)
    watchlist: list[WatchlistOut] = Field(default_factory=list)
    enrollments: list[EnrollmentOut] = Field(default_factory=list)
    matches: list[MatchOut] = Field(default_factory=list)
