from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.domains.rbac.roles import Role

if TYPE_CHECKING:
    from app.domains.users.models import User

role_enum = Enum(
    Role,
    name="user_role",
    values_callable=lambda enum: [member.value for member in enum],
)


class UserRole(Base):
    """A role granted to a user, optionally scoped to a department and/or a
    jurisdiction. No scope means the whole tenant.

    The composite foreign keys on (tenant_id, ...) make it impossible, at the
    database level, to scope a role to another tenant's department or
    jurisdiction.
    """

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "role",
            "department_id",
            "jurisdiction_id",
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
            name="fk_user_roles_tenant_user",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            ondelete="RESTRICT",
            name="fk_user_roles_tenant_department",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "jurisdiction_id"],
            ["jurisdictions.tenant_id", "jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_user_roles_tenant_jurisdiction",
        ),
        # Platform administrators are exactly the tenant-less role holders.
        CheckConstraint(
            "(role = 'platform_admin') = (tenant_id IS NULL)", name="platform_admin_has_no_tenant"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(role_enum)
    department_id: Mapped[uuid.UUID | None] = mapped_column()
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column()
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(
        back_populates="roles", primaryjoin="User.id == UserRole.user_id", foreign_keys=[user_id]
    )
