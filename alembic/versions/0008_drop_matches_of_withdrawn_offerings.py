"""drop match rows whose offering has been withdrawn.

The reconciler withdrew offerings without touching their match rows, and the
daily sweep only visits active offerings, so those rows were never recomputed or
removed. /api/matches, kid detail and the digest read Match without checking
offering status, so withdrawn programs kept showing as matches. The reconciler now
deletes a row's matches when it withdraws it; this clears the ones left from
before.

Revision ID: 0008_drop_matches_of_withdrawn_offerings
Revises: 0007_retry_not_found_geocodes
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_drop_matches_of_withdrawn_offerings"
down_revision: str | Sequence[str] | None = "0007_retry_not_found_geocodes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM matches WHERE offering_id IN "
        "(SELECT id FROM offerings WHERE status = 'withdrawn')"
    )


def downgrade() -> None:
    # Data-only and one-way: matches are derived, and a withdrawn offering has none.
    pass
