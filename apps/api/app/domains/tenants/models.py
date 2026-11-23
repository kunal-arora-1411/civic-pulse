from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"


class Tenant(TimestampMixin, Base):
    """A municipality. Not tenant-scoped itself, so it has no RLS policy."""

    __tablename__ = "tenants"
    __table_args__ = (CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name="slug_format"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    default_locale: Mapped[str] = mapped_column(String(10), server_default="en")
    supported_locales: Mapped[list[str]] = mapped_column(
        ARRAY(String(10)), server_default=text("'{en,hi}'::varchar[]")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
