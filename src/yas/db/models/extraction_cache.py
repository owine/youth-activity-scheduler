"""LLM extraction cache keyed by content hash."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import timestamp_column


class ExtractionCache(Base):
    __tablename__ = "extraction_cache"

    content_hash: Mapped[str] = mapped_column(String, primary_key=True)
    extracted_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    llm_model: Mapped[str] = mapped_column(String, nullable=False)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    extracted_at: Mapped[datetime] = timestamp_column()
