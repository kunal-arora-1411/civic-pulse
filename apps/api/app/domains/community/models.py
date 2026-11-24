"""Community support for an issue ("I face this too")."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


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
