"""Crawl targets."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import timestamp_column


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    adapter: Mapped[str] = mapped_column(String, default="llm")
    needs_browser: Mapped[bool] = mapped_column(default=False)
    crawl_hints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(default=True)
    default_cadence_s: Mapped[int] = mapped_column(Integer, default=6 * 3600)
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_column()
