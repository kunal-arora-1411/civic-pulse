"""Notification delivery: preferences, Web Push subscriptions, dead letters.

Every in-app notification now also becomes an outbox event
(`notification.created`), written by a trigger in the same transaction as the
notification, so the email, SMS and Web Push channels see exactly what the
inbox sees, and nothing is sent for a change that rolled back.

Delivery failures back off (`next_attempt_at`) and, once out of attempts,
the event is parked as a dead letter (`dead_lettered_at`) instead of being
marked dispatched: an administrator can inspect it and send it again.

One-time passwords leave the request too. A platform administrator signs in
without a tenant, so an OTP event can have no tenant; `tenant_id` becomes
nullable on the outbox tables. Such rows match no tenant policy and are only
reachable through the explicit RLS bypass, like the audit log's platform rows.

Revision ID: 0016
Revises: 0013
Create Date: 2026-11-26
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR current_setting('app.bypass_rls', true) = 'on'"
)
KINDS = (
    "report_new_issue",
    "report_linked",
    "issue_status",
    "review_task",
    "assignment",
    "sla_breach",
)
CHANNELS = ("email", "sms", "push")
APP_GRANTS = {
    "notification_preferences": "SELECT, INSERT, UPDATE, DELETE",
    "push_subscriptions": "SELECT, INSERT, UPDATE, DELETE",
}

QUEUE_FUNCTION = r"""
CREATE FUNCTION queue_notification_delivery() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    INSERT INTO outbox_events (tenant_id, event_type, aggregate_type, aggregate_id, payload)
    VALUES (NEW.tenant_id, 'notification.created', 'notification', NEW.id,
            jsonb_build_object('notification_id', NEW.id, 'user_id', NEW.user_id,
                               'kind', NEW.kind, 'issue_id', NEW.issue_id));
    RETURN NULL;
END
$fn$
"""


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", "civicpulse_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"Refusing to use unexpected role name {role!r}")
    return role


def _tenant(table: str) -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT", name=f"fk_{table}_tenant_id_tenants"),
        nullable=False,
    )


def _now(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("clock_timestamp()"),
        nullable=False,
    )


def upgrade() -> None:
    # --- outbox: backoff, dead letters, tenant-less events ------------------------------
    op.add_column(
        "outbox_events", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "outbox_events", sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("outbox_events", sa.Column("last_error", sa.String(300), nullable=True))
    op.alter_column("outbox_events", "tenant_id", nullable=True)
    op.alter_column("outbox_deliveries", "tenant_id", nullable=True)
    # The composite key does not hold a row whose tenant is NULL (MATCH
    # SIMPLE), so the event id alone carries the cascade for those.
    op.create_foreign_key(
        "fk_outbox_deliveries_event_id_outbox_events",
        "outbox_deliveries",
        "outbox_events",
        ["event_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("ix_outbox_events_undispatched", "outbox_events")
    op.create_index(
        "ix_outbox_events_undispatched",
        "outbox_events",
        ["created_at"],
        postgresql_where=sa.text("dispatched_at IS NULL AND dead_lettered_at IS NULL"),
    )
    op.create_index(
        "ix_outbox_events_dead_lettered",
        "outbox_events",
        ["dead_lettered_at"],
        postgresql_where=sa.text("dead_lettered_at IS NOT NULL"),
    )

    # --- per-user channel preferences ---------------------------------------------------
    op.create_table(
        "notification_preferences",
        _tenant("notification_preferences"),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        _now("updated_at"),
        sa.PrimaryKeyConstraint("user_id", "kind", "channel", name="pk_notification_preferences"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_notification_preferences_tenant_user",
        ),
        sa.CheckConstraint(
            f"kind IN ({_in(KINDS)})", name="ck_notification_preferences_kind_values"
        ),
        sa.CheckConstraint(
            f"channel IN ({_in(CHANNELS)})", name="ck_notification_preferences_channel_values"
        ),
    )

    # --- Web Push subscriptions (one per browser) ---------------------------------------
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant("push_subscriptions"),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.String(1000), nullable=False),
        sa.Column("p256dh", sa.String(200), nullable=False),
        sa.Column("auth", sa.String(100), nullable=False),
        sa.Column("user_agent", sa.String(400), nullable=True),
        _now("created_at"),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_push_subscriptions_tenant_user",
        ),
        sa.UniqueConstraint("tenant_id", "endpoint", name="uq_push_subscriptions_tenant_endpoint"),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])

    for table in APP_GRANTS:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )
    role = _app_role()
    grants = "\n".join(
        f"EXECUTE format('GRANT {privileges} ON {table} TO %I', '{role}');"
        for table, privileges in APP_GRANTS.items()
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                {grants}
            ELSE
                RAISE NOTICE 'role {role} does not exist; skipping grants';
            END IF;
        END
        $$;
        """
    )

    # --- every notification is offered to the external channels -------------------------
    op.execute(QUEUE_FUNCTION)
    op.execute(
        "CREATE TRIGGER queue_notification_delivery AFTER INSERT ON notifications "
        "FOR EACH ROW EXECUTE FUNCTION queue_notification_delivery()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS queue_notification_delivery ON notifications")
    op.execute("DROP FUNCTION IF EXISTS queue_notification_delivery()")
    op.drop_table("push_subscriptions")
    op.drop_table("notification_preferences")
    op.drop_index("ix_outbox_events_dead_lettered", "outbox_events")
    op.drop_index("ix_outbox_events_undispatched", "outbox_events")
    op.create_index(
        "ix_outbox_events_undispatched",
        "outbox_events",
        ["created_at"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )
    op.drop_constraint(
        "fk_outbox_deliveries_event_id_outbox_events", "outbox_deliveries", type_="foreignkey"
    )
    op.execute("DELETE FROM outbox_events WHERE tenant_id IS NULL")
    op.alter_column("outbox_deliveries", "tenant_id", nullable=False)
    op.alter_column("outbox_events", "tenant_id", nullable=False)
    op.drop_column("outbox_events", "last_error")
    op.drop_column("outbox_events", "dead_lettered_at")
    op.drop_column("outbox_events", "next_attempt_at")
