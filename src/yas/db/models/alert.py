"""Outbound alert queue."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import AlertType


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[AlertType] = mapped_column(String, nullable=False, index=True)
    kid_id: Mapped[int | None] = mapped_column(
        ForeignKey("kids.id", ondelete="SET NULL"), nullable=True
    )
    offering_id: Mapped[int | None] = mapped_column(
        ForeignKey("offerings.id", ondelete="SET NULL"), nullable=True
    )
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True
    )
    channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    skipped: Mapped[bool] = mapped_column(default=False)
    dedup_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (Index("ix_alerts_unsent_due", "scheduled_for", "sent_at"),)
