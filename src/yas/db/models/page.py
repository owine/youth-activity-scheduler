"""Per-URL tracked pages within a site."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import PageKind


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[PageKind] = mapped_column(String, default=PageKind.schedule.value)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    last_fetched: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_changed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
