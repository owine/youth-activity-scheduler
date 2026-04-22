"""Single-row worker liveness marker used by /readyz."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeat"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    worker_name: Mapped[str] = mapped_column(String, default="main")
    last_beat: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
