"""add alert close columns.

Revision ID: 0004_alert_close
Revises: 0003_pushover_config_json
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_alert_close"
down_revision: str | Sequence[str] | None = "0003_pushover_config_json"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("close_reason", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_alerts_closed_at"),
        "alerts",
        ["closed_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_alerts_closed_at"), table_name="alerts")
    op.drop_column("alerts", "close_reason")
    op.drop_column("alerts", "closed_at")
