"""In-app notifications, written by triggers on the events they report.

Triggers, rather than service code, create notifications so that every path
that writes an issue event, a review task or an assignment (API, workers,
consolidation, the seed) notifies the same way and in the same transaction.
Titles and bodies are i18n keys plus parameters; the client renders them in
the reader's language.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-27
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = ("report_new_issue", "report_linked", "issue_status", "review_task", "assignment")
TENANT_PREDICATE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR current_setting('app.bypass_rls', true) = 'on'"
)

# Citizens hear about their own reports: where matching placed them, and
# every public status move of the issue they are on (not their own moves).
# Operators hear about new review tasks; an assignee about work given to
# them by someone else. Internal events never notify citizens.
FUNCTIONS = r"""
CREATE FUNCTION notify_issue_event() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE
    ref text;
BEGIN
    SELECT reference INTO ref FROM civic_issues WHERE id = NEW.issue_id;

    IF NEW.type IN ('created', 'report_linked') AND NEW.report_id IS NOT NULL THEN
        INSERT INTO notifications (tenant_id, user_id, kind, title_key, body_key, params, link,
                                   issue_id, created_at)
        SELECT NEW.tenant_id, r.reporter_id,
               CASE NEW.type WHEN 'created' THEN 'report_new_issue' ELSE 'report_linked' END,
               CASE NEW.type WHEN 'created' THEN 'report_new_issue.title'
                             ELSE 'report_linked.title' END,
               CASE NEW.type WHEN 'created' THEN 'report_new_issue.body'
                             ELSE 'report_linked.body' END,
               jsonb_build_object('issue', ref, 'report', r.reference),
               '/reports/' || r.id, NEW.issue_id, NEW.created_at
        FROM reports r
        WHERE r.id = NEW.report_id AND r.status <> 'withdrawn';
        RETURN NULL;
    END IF;

    IF NEW.to_status IS NOT NULL AND NEW.visibility = 'public'
       AND NEW.from_status IS DISTINCT FROM NEW.to_status THEN
        INSERT INTO notifications (tenant_id, user_id, kind, title_key, body_key, params, link,
                                   issue_id, created_at)
        SELECT NEW.tenant_id, r.reporter_id, 'issue_status', 'issue_status.title',
               'issue_status.body',
               jsonb_build_object('issue', ref, 'status', NEW.to_status),
               '/reports/' || (array_agg(r.id ORDER BY r.created_at))[1],
               NEW.issue_id, NEW.created_at
        FROM reports r
        WHERE r.issue_id = NEW.issue_id AND r.status <> 'withdrawn'
          AND r.reporter_id IS DISTINCT FROM NEW.actor_id
        GROUP BY r.reporter_id;
    END IF;
    RETURN NULL;
END
$fn$
--;;
CREATE FUNCTION notify_review_task() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.status <> 'open' THEN
        RETURN NULL;
    END IF;
    INSERT INTO notifications (tenant_id, user_id, kind, title_key, body_key, params, link,
                               created_at)
    SELECT DISTINCT NEW.tenant_id, ur.user_id, 'review_task', 'review_task.title',
           'review_task.body', jsonb_build_object('report', r.reference),
           '/admin/review', NEW.created_at
    FROM user_roles ur
    JOIN reports r ON r.id = NEW.report_id
    WHERE ur.tenant_id = NEW.tenant_id AND ur.role = 'operator';
    RETURN NULL;
END
$fn$
--;;
CREATE FUNCTION notify_assignment() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.assignee_id IS NULL OR NEW.assignee_id IS NOT DISTINCT FROM NEW.assigned_by THEN
        RETURN NULL;
    END IF;
    INSERT INTO notifications (tenant_id, user_id, kind, title_key, body_key, params, link,
                               issue_id, created_at)
    SELECT NEW.tenant_id, NEW.assignee_id, 'assignment', 'assignment.title', 'assignment.body',
           jsonb_build_object('issue', i.reference), '/field', i.id, NEW.created_at
    FROM civic_issues i WHERE i.id = NEW.issue_id;
    RETURN NULL;
END
$fn$
--;;
CREATE TRIGGER notify_issue_event AFTER INSERT ON issue_events
    FOR EACH ROW EXECUTE FUNCTION notify_issue_event()
--;;
CREATE TRIGGER notify_review_task AFTER INSERT ON review_tasks
    FOR EACH ROW EXECUTE FUNCTION notify_review_task()
--;;
CREATE TRIGGER notify_assignment AFTER INSERT ON issue_assignments
    FOR EACH ROW EXECUTE FUNCTION notify_assignment();
"""


def _app_role() -> str:
    role = os.environ.get("APP_DB_USER", "civicpulse_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"Refusing to use unexpected role name {role!r}")
    return role


def upgrade() -> None:
    kinds = ", ".join(f"'{k}'" for k in KINDS)
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(
                "tenants.id", ondelete="RESTRICT", name="fk_notifications_tenant_id_tenants"
            ),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title_key", sa.String(100), nullable=False),
        sa.Column("body_key", sa.String(100), nullable=False),
        sa.Column(
            "params", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("link", sa.String(300), nullable=True),
        sa.Column("issue_id", sa.Uuid(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_notifications_tenant_user",
        ),
        sa.CheckConstraint(f"kind IN ({kinds})", name="ck_notifications_kind_values"),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])
    op.create_index(
        "ix_notifications_user_unread",
        "notifications",
        ["user_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON notifications "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )
    role = _app_role()
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE format('GRANT SELECT, INSERT, UPDATE ON notifications TO %I', '{role}');
            ELSE
                RAISE NOTICE 'role {role} does not exist; skipping grants';
            END IF;
        END
        $$
        """
    )
    for statement in FUNCTIONS.split("--;;"):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS notify_assignment ON issue_assignments")
    op.execute("DROP TRIGGER IF EXISTS notify_review_task ON review_tasks")
    op.execute("DROP TRIGGER IF EXISTS notify_issue_event ON issue_events")
    op.execute("DROP FUNCTION IF EXISTS notify_assignment()")
    op.execute("DROP FUNCTION IF EXISTS notify_review_task()")
    op.execute("DROP FUNCTION IF EXISTS notify_issue_event()")
    op.drop_table("notifications")
