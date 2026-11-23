from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.pagination import Page
from app.core.phone import PhoneNumber
from app.domains.rbac.roles import Role


class RoleAssignment(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

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


class AdminUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: PhoneNumber
    display_name: str = Field(min_length=1, max_length=100)
    email: EmailStr | None = None
    roles: list[RoleAssignment] = Field(min_length=1, max_length=20)


class AdminUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    is_active: bool | None = None


class RolesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: list[RoleAssignment] = Field(min_length=1, max_length=20)


class AdminUser(UserMe):
    """The /users/me shape plus account status, as seen by administrators."""

    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class AdminUserPage(Page[AdminUser]):
    pass
