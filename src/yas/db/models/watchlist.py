"""Per-kid watchlist entries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import WatchlistPriority, timestamp_column


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kid_id: Mapped[int] = mapped_column(ForeignKey("kids.id", ondelete="CASCADE"))
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=True
    )
    pattern: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[WatchlistPriority] = mapped_column(
        String, default=WatchlistPriority.normal.value
    )
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    # Reserved for a future "strict mode" opt-in. Not consulted by the matcher
    # in Phase 3 — watchlist hits unconditionally bypass all hard gates because
    # the user has already manually verified the program's details.
    ignore_hard_gates: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = timestamp_column()
