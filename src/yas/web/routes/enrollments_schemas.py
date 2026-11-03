"""Pydantic models for /api/enrollments endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from yas.db.models._types import EnrollmentStatus
from yas.web.routes._types import UtcDatetime
from yas.web.routes.matches_schemas import OfferingSummary


class EnrollmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kid_id: int
    offering_id: int
    status: EnrollmentStatus = EnrollmentStatus.interested
    enrolled_at: datetime | None = None
    notes: str | None = None


class EnrollmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: EnrollmentStatus | None = None
    enrolled_at: datetime | None = None
    notes: str | None = None


class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kid_id: int
    offering_id: int
    status: EnrollmentStatus
    enrolled_at: UtcDatetime | None
    notes: str | None
    created_at: UtcDatetime
    offering: OfferingSummary
