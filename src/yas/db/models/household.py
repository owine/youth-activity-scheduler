"""Single-row household-wide settings."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base


class HouseholdSettings(Base):
    __tablename__ = "household_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    home_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), nullable=True
    )
    default_max_distance_mi: Mapped[float | None] = mapped_column(nullable=True)
    digest_time: Mapped[str] = mapped_column(String, default="07:00")
    quiet_hours_start: Mapped[str | None] = mapped_column(String, nullable=True)
    quiet_hours_end: Mapped[str | None] = mapped_column(String, nullable=True)
    daily_llm_cost_cap_usd: Mapped[float] = mapped_column(default=1.0)
    smtp_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ha_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ntfy_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
