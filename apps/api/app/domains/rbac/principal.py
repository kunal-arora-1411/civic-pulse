"""The authenticated caller, as resolved for one request."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domains.rbac.permissions import ROLE_PERMISSIONS, Permission, permissions_for
from app.domains.rbac.roles import STAFF_ROLES, Role


@dataclass(frozen=True, slots=True)
class RoleGrant:
    role: Role
    department_id: uuid.UUID | None = None
    jurisdiction_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    session_id: uuid.UUID
    grants: tuple[RoleGrant, ...]
    mfa_verified: bool = False

    @property
    def roles(self) -> frozenset[Role]:
        return frozenset(grant.role for grant in self.grants)

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_for(self.roles)

    @property
    def is_staff(self) -> bool:
        return bool(self.roles & STAFF_ROLES)

    @property
    def is_platform_admin(self) -> bool:
        return Role.PLATFORM_ADMIN in self.roles and self.tenant_id is None

    def has(self, *permissions: Permission) -> bool:
        return set(permissions) <= self.permissions

    def grants_for(self, permission: Permission) -> tuple[RoleGrant, ...]:
        """The role grants that confer `permission`, with their scopes."""
        return tuple(g for g in self.grants if permission in ROLE_PERMISSIONS[g.role])
