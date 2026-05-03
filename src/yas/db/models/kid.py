"""Per-kid profile."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import JSON, Date, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import timestamp_column


class Kid(Base):
    __tablename__ = "kids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    dob: Mapped[date] = mapped_column(Date, nullable=False)
    interests: Mapped[list[str]] = mapped_column(JSON, default=list)
    availability: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    max_distance_mi: Mapped[float | None] = mapped_column(nullable=True)
    # Drive-time cap (minutes). When set AND the household has
    # YAS_DRIVE_TIME_ENABLED=true, the matcher uses this cap instead of
    # max_distance_mi. Nullable so existing kids (great-circle only)
    # keep working.
    max_drive_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alert_score_threshold: Mapped[float] = mapped_column(default=0.6)
    alert_on: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # School schedule — source of truth; unavailability_blocks with source=school
    # are materialized from these fields by the matcher layer (Phase 3).
    school_weekdays: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["mon", "tue", "wed", "thu", "fri"]
    )
    school_time_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    school_time_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    school_year_ranges: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    school_holidays: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = timestamp_column()
