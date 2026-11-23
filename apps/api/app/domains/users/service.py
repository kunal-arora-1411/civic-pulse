from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.tenancy import acting_as
from app.domains.rbac.permissions import permissions_for
from app.domains.rbac.roles import STAFF_ROLES
from app.domains.tenants.models import Tenant
from app.domains.users.models import User
from app.domains.users.schemas import AdminUser, RoleAssignment, UserMe, UserMeUpdate

MAX_PREFERENCES_BYTES = 4096
PLATFORM_LOCALES = ("en", "hi")


def is_staff(user: User) -> bool:
    return any(r.role in STAFF_ROLES for r in user.roles)


def role_assignments(user: User) -> list[RoleAssignment]:
    return [RoleAssignment.model_validate(r) for r in user.roles]


def to_me(user: User) -> UserMe:
    return UserMe(
        id=user.id,
        tenant_id=user.tenant_id,
        phone=user.phone,
        email=user.email,
        display_name=user.display_name,
        locale=user.locale,
        preferences=user.preferences,
        mfa_enabled=user.mfa_enabled,
        is_staff=is_staff(user),
        roles=role_assignments(user),
        permissions=sorted(permissions_for(r.role for r in user.roles)),
    )


def to_admin(user: User) -> AdminUser:
    return AdminUser(
        **to_me(user).model_dump(),
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


async def get_self(db: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID | None) -> User:
    """Load the caller's own user row (platform admins need the bypass)."""
    async with acting_as(db, tenant_id, reason="platform admin reading own profile"):
        user = await db.get(User, user_id)
    if user is None:
        raise NotFound()
    return user


async def email_taken(
    db: AsyncSession, email: str, *, exclude_user_id: uuid.UUID | None = None
) -> bool:
    # RLS limits this to the current tenant, matching the unique index.
    stmt = select(User.id).where(func.lower(User.email) == email.lower())
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return (await db.scalar(stmt.limit(1))) is not None


async def update_self(
    db: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID | None, changes: UserMeUpdate
) -> User:
    async with acting_as(db, tenant_id, reason="platform admin updating own profile"):
        user = await db.get(User, user_id)
        if user is None:
            raise NotFound()
        data = changes.model_dump(exclude_unset=True)

        if "locale" in data and data["locale"] is not None:
            tenant = await db.get(Tenant, tenant_id) if tenant_id else None
            allowed = tenant.supported_locales if tenant else list(PLATFORM_LOCALES)
            if data["locale"] not in allowed:
                raise ValidationFailed(
                    "This locale is not supported.", details={"supported_locales": allowed}
                )
        preferences = data.get("preferences")
        if preferences is not None and len(json.dumps(preferences)) > MAX_PREFERENCES_BYTES:
            raise ValidationFailed("Preferences are too large.")
        email = data.get("email")
        if email and await email_taken(db, email, exclude_user_id=user.id):
            raise Conflict("That email address is already in use.")

        for field in ("display_name", "email", "locale", "preferences"):
            if field in data:
                if data[field] is None and field in ("locale", "preferences"):
                    continue  # not nullable; null means "leave unchanged"
                setattr(user, field, data[field])
        try:
            await db.flush()
        except IntegrityError as exc:  # lost a race on the email index
            raise Conflict("That email address is already in use.") from exc
    return user
