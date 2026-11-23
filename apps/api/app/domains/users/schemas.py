from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domains.rbac.roles import Role


class RoleAssignment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: Role
    department_id: uuid.UUID | None = None
    jurisdiction_id: uuid.UUID | None = None


class UserMe(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    phone: str
    email: str | None
    display_name: str | None
    locale: str
    preferences: dict[str, Any]
    mfa_enabled: bool
    is_staff: bool
    roles: list[RoleAssignment]
    permissions: list[str]


class UserMeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    locale: str | None = Field(default=None, min_length=2, max_length=10)
    preferences: dict[str, Any] | None = None


class AdminUser(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    phone: str
    email: str | None
    display_name: str | None
    locale: str
    is_active: bool
    is_staff: bool
    mfa_enabled: bool
    roles: list[RoleAssignment]
    created_at: datetime
    last_login_at: datetime | None
