"""Precomputed kid↔offering matches."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import timestamp_column


class Match(Base):
    __tablename__ = "matches"

    kid_id: Mapped[int] = mapped_column(ForeignKey("kids.id", ondelete="CASCADE"), primary_key=True)
    offering_id: Mapped[int] = mapped_column(
        ForeignKey("offerings.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[float] = mapped_column(nullable=False)
    reasons: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = timestamp_column()
