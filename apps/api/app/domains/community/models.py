"""Community support for an issue ("I face this too"), and citizen comments
held for moderation (FR-017, FR-086)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.domains.workflow.statuses import sql_in


class IssueSupport(Base):
    """One citizen's "+1" on an issue. Supporting also follows it."""

    __tablename__ = "issue_supports"
    __table_args__ = (
        UniqueConstraint("issue_id", "user_id"),
        ForeignKeyConstraint(
            ["tenant_id", "issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="CASCADE",
            name="fk_issue_supports_tenant_issue",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_issue_supports_tenant_user",
        ),
        Index("ix_issue_supports_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    issue_id: Mapped[uuid.UUID] = mapped_column()
    user_id: Mapped[uuid.UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommentState(StrEnum):
    PENDING = "pending"  # waiting for a moderator; only its author sees it
    APPROVED = "approved"  # public on the issue
    REJECTED = "rejected"  # removed by a moderator, with a reason


class IssueComment(Base):
    """A citizen's comment on an issue (FR-017). Nothing is public until a
    moderator approves it; enough flags send it back for another look."""

    __tablename__ = "issue_comments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "issue_id"],
            ["civic_issues.tenant_id", "civic_issues.id"],
            ondelete="CASCADE",
            name="fk_issue_comments_tenant_issue",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "author_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_issue_comments_tenant_author",
        ),
        CheckConstraint(f"state IN ({sql_in(CommentState)})", name="state_values"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 1000", name="body_length"),
        CheckConstraint("flag_count >= 0", name="flag_count_non_negative"),
        Index("ix_issue_comments_issue_created", "issue_id", "created_at"),
        Index("ix_issue_comments_state_created", "state", "created_at"),
        Index("ix_issue_comments_author_created", "author_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    issue_id: Mapped[uuid.UUID] = mapped_column()
    author_id: Mapped[uuid.UUID] = mapped_column()
    body: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(
        String(10), default=CommentState.PENDING, server_default=text("'pending'")
    )
    flag_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    moderated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    moderation_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommentFlag(Base):
    """One citizen reporting a comment as abusive or misleading (FR-086)."""

    __tablename__ = "comment_flags"
    __table_args__ = (
        UniqueConstraint("comment_id", "user_id"),
        ForeignKeyConstraint(
            ["tenant_id", "comment_id"],
            ["issue_comments.tenant_id", "issue_comments.id"],
            ondelete="CASCADE",
            name="fk_comment_flags_tenant_comment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_comment_flags_tenant_user",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    comment_id: Mapped[uuid.UUID] = mapped_column()
    user_id: Mapped[uuid.UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
