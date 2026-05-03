"""Memoized routed driving distance/duration between geocoded points."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from yas.db.base import Base


class DriveTimeCache(Base):
    __tablename__ = "drive_time_cache"

    # Coordinates are rounded to 4 decimals (~11 m) before write so
    # geocode jitter doesn't fragment the cache. The four-column
    # primary key avoids needing a secondary id.
    home_lat: Mapped[float] = mapped_column(Float, primary_key=True)
    home_lon: Mapped[float] = mapped_column(Float, primary_key=True)
    dest_lat: Mapped[float] = mapped_column(Float, primary_key=True)
    dest_lon: Mapped[float] = mapped_column(Float, primary_key=True)

    drive_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    drive_meters: Mapped[float] = mapped_column(Float, nullable=False)
    # "osrm" today; future providers (mapbox, google) reuse the same table.
    provider: Mapped[str] = mapped_column(String, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
