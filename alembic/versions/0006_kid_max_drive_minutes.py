"""add kids.max_drive_minutes for drive-time gate.

Revision ID: 0006_kid_max_drive_minutes
Revises: 0005_drive_time_cache
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_kid_max_drive_minutes"
down_revision: str | Sequence[str] | None = "0005_drive_time_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "kids",
        sa.Column("max_drive_minutes", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("kids", "max_drive_minutes")
