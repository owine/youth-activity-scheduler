"""add pushover_config_json to household_settings.

Revision ID: 0003_pushover_config_json
Revises: 0002_geocode_attempts
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_pushover_config_json"
down_revision: str | Sequence[str] | None = "0002_geocode_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("household_settings", sa.Column("pushover_config_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("household_settings", "pushover_config_json")
