"""drop not_found geocode attempts so each address is re-checked once.

Before this revision the Nominatim client reported outages (429, 5xx, transport,
non-JSON bodies) as "no match", so the enricher stored them as permanent
not_found (#456). Those rows can't be told apart from genuine misses; deleting
them all costs one rate-limited request per address, and genuine misses are
simply recorded again.

Revision ID: 0007_retry_not_found_geocodes
Revises: 0006_kid_max_drive_minutes
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_retry_not_found_geocodes"
down_revision: str | Sequence[str] | None = "0006_kid_max_drive_minutes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM geocode_attempts WHERE result = 'not_found'")


def downgrade() -> None:
    # Data-only and one-way: the deleted rows are re-created by the enricher.
    pass
