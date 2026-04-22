"""Negative-cache row for addresses Nominatim couldn't resolve."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base


class GeocodeAttempt(Base):
    __tablename__ = "geocode_attempts"

    address_norm: Mapped[str] = mapped_column(String, primary_key=True)
    last_tried: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[str] = mapped_column(String, nullable=False)       # "ok" | "not_found" | "error"
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
