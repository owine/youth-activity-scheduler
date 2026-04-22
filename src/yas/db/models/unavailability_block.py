"""Per-kid unavailability: school, enrollments, manual, custom."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import JSON, Date, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import UnavailabilitySource, timestamp_column


class UnavailabilityBlock(Base):
    __tablename__ = "unavailability_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kid_id: Mapped[int] = mapped_column(ForeignKey("kids.id", ondelete="CASCADE"), index=True)
    source: Mapped[UnavailabilitySource] = mapped_column(
        String, default=UnavailabilitySource.manual.value
    )
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    days_of_week: Mapped[list[str]] = mapped_column(JSON, default=list)
    time_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    time_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    date_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_enrollment_id: Mapped[int | None] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=True
    )
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = timestamp_column()
