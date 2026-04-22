"""geocode_attempts

Revision ID: 0002_geocode_attempts
Revises: 0001_initial
Create Date: 2026-04-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_geocode_attempts"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "geocode_attempts",
        sa.Column("address_norm", sa.String(), primary_key=True),
        sa.Column("last_tried", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("geocode_attempts")
