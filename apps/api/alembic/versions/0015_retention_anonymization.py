"""Retention and account anonymization (P6-12, PRD 12.2 and 16).

`users.anonymized_at` marks an account whose personal data was wiped at the
owner's request; the row stays so reports, issues and audit history keep
their references. `media_assets.original_purged_at` marks a photo whose
original object (with its full EXIF, GPS included) was deleted by the
retention job; the stripped, face-checked variants stay.

Numbered 0015 to leave room for branches built in parallel; it follows
0014 (analytics extras), the latest on main when this branch merged it.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("anonymized_at", sa.DateTime(timezone=True)))
    op.add_column("media_assets", sa.Column("original_purged_at", sa.DateTime(timezone=True)))
    # The retention job looks for ready photos whose originals are still
    # stored, oldest first.
    op.create_index(
        "ix_media_assets_retention",
        "media_assets",
        ["processed_at"],
        postgresql_where=sa.text("original_purged_at IS NULL AND status = 'ready'"),
    )


def downgrade() -> None:
    op.drop_index("ix_media_assets_retention", table_name="media_assets")
    op.drop_column("media_assets", "original_purged_at")
    op.drop_column("users", "anonymized_at")
