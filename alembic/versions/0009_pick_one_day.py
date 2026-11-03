"""add offerings.attends_one_day and enrollments.days_of_week (#636).

Some programs let a family pick one weekly day ("choose a day of the week…
classes meet one day per week"). The offering records that it is pick-one, and
the enrollment records which day was picked.

Revision ID: 0009_pick_one_day
Revises: 0008_drop_matches_of_withdrawn_offerings
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_pick_one_day"
down_revision: str | Sequence[str] | None = "0008_drop_matches_of_withdrawn_offerings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain ADD COLUMN: SQLite supports it in place, where batch mode would
    # rebuild both tables.
    op.add_column(
        "offerings",
        sa.Column("attends_one_day", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column("enrollments", sa.Column("days_of_week", sa.JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("enrollments") as batch:
        batch.drop_column("days_of_week")
    with op.batch_alter_table("offerings") as batch:
        batch.drop_column("attends_one_day")
