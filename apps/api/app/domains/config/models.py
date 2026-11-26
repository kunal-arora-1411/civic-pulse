"""Per-tenant configuration documents (matching and priority rules)."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, PrimaryKeyConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.domains.workflow.statuses import sql_in


class ConfigKey(StrEnum):
    MATCHING = "matching"
    PRIORITY = "priority"
    CLOSURE = "closure"


class TenantConfig(TimestampMixin, Base):
    """One validated JSON document per tenant and key.

    A tenant without a row uses the built-in defaults, so a missing row is
    never an error. Kept out of `tenants.settings` because that table has
    no RLS (it isn't tenant-scoped) and these documents are.
    """

    __tablename__ = "tenant_configs"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "key"),
        CheckConstraint(f"key IN ({sql_in(ConfigKey)})", name="key_values"),
        CheckConstraint("jsonb_typeof(value) = 'object'", name="value_is_object"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    key: Mapped[str] = mapped_column(String(32))
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
