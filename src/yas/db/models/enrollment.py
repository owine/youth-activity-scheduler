"""Committing to an offering: drives unavailability block materialization."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import EnrollmentStatus, timestamp_column


class Enrollment(Base):
    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kid_id: Mapped[int] = mapped_column(ForeignKey("kids.id", ondelete="CASCADE"), index=True)
    offering_id: Mapped[int] = mapped_column(
        ForeignKey("offerings.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[EnrollmentStatus] = mapped_column(
        String, default=EnrollmentStatus.interested.value
    )
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = timestamp_column()
