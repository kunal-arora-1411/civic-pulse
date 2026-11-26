"""In-app notifications (created by database triggers, migration 0008, and
by the SLA scanner)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.domains.workflow.statuses import sql_in


class NotificationKind(StrEnum):
    REPORT_NEW_ISSUE = "report_new_issue"  # your report started an issue
    REPORT_LINKED = "report_linked"  # your report joined an existing issue
    ISSUE_STATUS = "issue_status"  # the issue your report is on moved
    REVIEW_TASK = "review_task"  # a report waits for a duplicate decision
    ASSIGNMENT = "assignment"  # an issue was assigned to you
    SLA_BREACH = "sla_breach"  # an issue you oversee is past its SLA


class Notification(Base):
    """One message for one user. Text is an i18n key plus `params`."""

    __tablename__ = "notifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_notifications_tenant_user",
        ),
        CheckConstraint(f"kind IN ({sql_in(NotificationKind)})", name="kind_values"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_user_unread", "user_id", postgresql_where=text("read_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    user_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(32))
    title_key: Mapped[str] = mapped_column(String(100))
    body_key: Mapped[str] = mapped_column(String(100))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    link: Mapped[str | None] = mapped_column(String(300))
    issue_id: Mapped[uuid.UUID | None] = mapped_column()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class DeliveryChannel(StrEnum):
    """External channels a notification can also go out on. The in-app inbox
    is not one of them: it always gets every notification."""

    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class NotificationPreference(Base):
    """One person's choice for one kind on one channel.

    Only choices that were saved are stored; anything absent falls back to
    the default in `app/domains/notifications/preferences.py`.
    """

    __tablename__ = "notification_preferences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_notification_preferences_tenant_user",
        ),
        CheckConstraint(f"kind IN ({sql_in(NotificationKind)})", name="kind_values"),
        CheckConstraint(f"channel IN ({sql_in(DeliveryChannel)})", name="channel_values"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class PushSubscription(Base):
    """A browser that agreed to receive Web Push for one signed-in person.

    The endpoint is the push service's URL for that browser; `p256dh` and
    `auth` are the browser's keys the payload is encrypted to (RFC 8291).
    """

    __tablename__ = "push_subscriptions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_push_subscriptions_tenant_user",
        ),
        UniqueConstraint("tenant_id", "endpoint", name="uq_push_subscriptions_tenant_endpoint"),
        Index("ix_push_subscriptions_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    user_id: Mapped[uuid.UUID] = mapped_column()
    endpoint: Mapped[str] = mapped_column(String(1000))
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
