"""Pydantic models for /api/enrollments endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from yas.db.models._types import DayOfWeek, EnrollmentStatus
from yas.web.routes._types import UtcDatetime, UtcDatetimeIn
from yas.web.routes.matches_schemas import OfferingSummary


class EnrollmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kid_id: int
    offering_id: int
    status: EnrollmentStatus = EnrollmentStatus.interested
    enrolled_at: UtcDatetimeIn | None = None
    notes: str | None = None
    # The day(s) attended, for a pick-one-day offering. Must be days the
    # offering lists; None means all of them.
    days_of_week: list[DayOfWeek] | None = None


class EnrollmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: EnrollmentStatus | None = None
    enrolled_at: UtcDatetimeIn | None = None
    notes: str | None = None
    days_of_week: list[DayOfWeek] | None = None


class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kid_id: int
    offering_id: int
    status: EnrollmentStatus
    enrolled_at: UtcDatetime | None
    notes: str | None
    days_of_week: list[str] | None = None
    created_at: UtcDatetime
    offering: OfferingSummary
