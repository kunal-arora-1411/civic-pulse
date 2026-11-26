from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin

if TYPE_CHECKING:
    from app.domains.rbac.models import UserRole


class User(TimestampMixin, Base):
    """A citizen, staff member or platform administrator.

    Platform administrators have no tenant (tenant_id IS NULL); everyone else
    belongs to exactly one tenant. Phone numbers are unique per tenant, and
    NULLS NOT DISTINCT makes them unique among platform administrators too.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone", postgresql_nulls_not_distinct=True),
        # Target for composite foreign keys that pin child rows to the same tenant.
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{6,14}$'", name="phone_e164"),
        Index(
            "uq_users_tenant_id_email",
            "tenant_id",
            func.lower(text("email")),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    phone: Mapped[str] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(100))
    locale: Mapped[str] = mapped_column(String(10), default="en", server_default="en")
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Fernet-encrypted TOTP secret. Present (but not yet enabled) during setup.
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    # Last accepted TOTP time step, so a code can't be replayed in its window.
    mfa_last_used_step: Mapped[int | None] = mapped_column(BigInteger)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the owner had their personal data wiped (P6-12). The row
    # stays so reports and history keep their references.
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
        primaryjoin="User.id == UserRole.user_id",
        foreign_keys="UserRole.user_id",
        order_by="UserRole.created_at",
    )
