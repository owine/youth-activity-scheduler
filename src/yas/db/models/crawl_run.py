"""Per-crawl observability row."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import CrawlStatus


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[CrawlStatus] = mapped_column(String, default=CrawlStatus.ok.value)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    changes_detected: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    llm_cost_usd: Mapped[float] = mapped_column(default=0.0)
    error_text: Mapped[str | None] = mapped_column(String, nullable=True)
