"""Editable alert routing config."""

from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base
from yas.db.models._types import AlertType


class AlertRouting(Base):
    __tablename__ = "alert_routing"

    type: Mapped[AlertType] = mapped_column(String, primary_key=True)
    channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(default=True)
