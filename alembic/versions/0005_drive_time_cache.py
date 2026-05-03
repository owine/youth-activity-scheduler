"""add drive_time_cache table for routed-driving distance/duration.

Revision ID: 0005_drive_time_cache
Revises: 0004_alert_close
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_drive_time_cache"
down_revision: str | Sequence[str] | None = "0004_alert_close"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Composite primary key on rounded coordinates: 4-decimal precision
    # is ~11 meters, plenty of granularity. Rounding before storage
    # makes "same trip" cache hits robust against geocode jitter.
    op.create_table(
        "drive_time_cache",
        sa.Column("home_lat", sa.Float, primary_key=True),
        sa.Column("home_lon", sa.Float, primary_key=True),
        sa.Column("dest_lat", sa.Float, primary_key=True),
        sa.Column("dest_lon", sa.Float, primary_key=True),
        sa.Column("drive_minutes", sa.Float, nullable=False),
        sa.Column("drive_meters", sa.Float, nullable=False),
        sa.Column("provider", sa.String, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("drive_time_cache")
