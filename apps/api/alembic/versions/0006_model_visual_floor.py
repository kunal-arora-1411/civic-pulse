"""Let stored matching configs follow the model's auto-link visual floor.

`matching_config.thresholds.visual_min` used to default to 0.80. The
evaluation (docs/eval/phase-2-baseline.md) found that, with the shipped
CLIP model, 11% of pairs of different photos of the same category pass
0.80, and that the floor depends on the model anyway. It is now optional:
null means "the floor recorded for the active model", 0.92 for CLIP.

A stored document still holding exactly 0.80 is the old default written
out (the seed stores the defaults explicitly), not a choice, so it goes
back to null. Any other value was set by someone and is kept. The
downgrade writes 0.80 back where the value is null, since the old code
requires a number.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_DEFAULT = 0.8


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE tenant_configs
        SET value = jsonb_set(value, '{{thresholds,visual_min}}', 'null'::jsonb)
        WHERE key = 'matching'
          AND jsonb_typeof(value #> '{{thresholds,visual_min}}') = 'number'
          AND (value #>> '{{thresholds,visual_min}}')::numeric = {OLD_DEFAULT}
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE tenant_configs
        SET value = jsonb_set(value, '{{thresholds,visual_min}}', '{OLD_DEFAULT}'::jsonb)
        WHERE key = 'matching'
          AND value ? 'thresholds'
          AND coalesce(jsonb_typeof(value #> '{{thresholds,visual_min}}'), 'null') = 'null'
        """
    )
