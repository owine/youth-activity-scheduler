"""Structured program offerings extracted from pages."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import OfferingStatus, ProgramType, timestamp_column


class Offering(Base):
    __tablename__ = "offerings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    age_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    program_type: Mapped[ProgramType] = mapped_column(String, default=ProgramType.unknown.value)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    days_of_week: Mapped[list[str]] = mapped_column(JSON, default=list)
    time_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    time_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registration_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registration_url: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen: Mapped[datetime] = timestamp_column()
    last_seen: Mapped[datetime] = timestamp_column()
    status: Mapped[OfferingStatus] = mapped_column(String, default=OfferingStatus.active.value)
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
