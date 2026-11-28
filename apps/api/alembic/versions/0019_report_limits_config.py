"""Let a tenant configure its own citizen report submission limits.

`report_max_per_hour` and `report_max_per_day` have been process-wide
settings since Phase 1 (PRD §12.3), so every tenant shares one city's idea
of a reasonable burst. This adds `report_limits` to the existing per-tenant
configuration document (`tenant_configs`, from 0004) alongside matching,
priority and closure, so a tenant can tighten or loosen its own citizens'
limits without a code change or a restart. A tenant with no row keeps the
process-wide defaults, same as the other three keys.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_tenant_configs_key_values", "tenant_configs", type_="check")
    op.create_check_constraint(
        "ck_tenant_configs_key_values",
        "tenant_configs",
        "key IN ('matching', 'priority', 'closure', 'report_limits')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM tenant_configs WHERE key = 'report_limits'")
    op.drop_constraint("ck_tenant_configs_key_values", "tenant_configs", type_="check")
    op.create_check_constraint(
        "ck_tenant_configs_key_values",
        "tenant_configs",
        "key IN ('matching', 'priority', 'closure')",
    )
