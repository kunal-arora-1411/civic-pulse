"""User management for municipal administrators.

Everything runs under the administrator's tenant (RLS), so a user ID from
another tenant behaves exactly like one that doesn't exist: 404, never 403,
and nothing about the other tenant leaks.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.core.pagination import PageParams, paginate, sort_clauses
from app.domains.audit import service as audit
from app.domains.auth import service as auth_service
from app.domains.rbac.models import UserRole
from app.domains.rbac.permissions import Permission, permissions_for
from app.domains.rbac.principal import Principal
from app.domains.rbac.roles import Role
from app.domains.rbac.service import validate_assignments
from app.domains.users.models import User
from app.domains.users.schemas import (
    AdminUser,
    AdminUserCreate,
    AdminUserUpdate,
    RoleAssignment,
)
from app.domains.users.service import email_taken, to_admin

SORTS = {
    "created_at": User.created_at,
    "display_name": User.display_name,
    "phone": User.phone,
    "last_login_at": User.last_login_at,
}


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _snapshot(user: User) -> dict[str, Any]:
    return to_admin(user).model_dump(
        mode="json", include={"display_name", "email", "is_active", "roles"}
    )


async def list_users(
    db: AsyncSession,
    params: PageParams,
    *,
    q: str | None,
    role: Role | None,
    is_active: bool | None,
    sort: str | None,
) -> tuple[list[AdminUser], int]:
    stmt = select(User)
    if q:
        pattern = _like(q.strip())
        stmt = stmt.where(
            or_(
                User.display_name.ilike(pattern, escape="\\"),
                User.phone.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
            )
        )
    if role is not None:
        stmt = stmt.where(User.id.in_(select(UserRole.user_id).where(UserRole.role == role)))
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    stmt = stmt.order_by(*sort_clauses(sort, SORTS, default="-created_at", tiebreaker=User.id))
    rows, total = await paginate(db, stmt, params)
    return [to_admin(row[0]) for row in rows], total


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFound("User not found.")
    return user


def _role_rows(
    actor: Principal, user_id: uuid.UUID, assignments: list[RoleAssignment]
) -> list[UserRole]:
    return [
        UserRole(
            tenant_id=actor.tenant_id,
            user_id=user_id,
            role=a.role,
            department_id=a.department_id,
            jurisdiction_id=a.jurisdiction_id,
            granted_by=actor.user_id,
        )
        for a in assignments
    ]


async def create_user(db: AsyncSession, actor: Principal, body: AdminUserCreate) -> User:
    assert actor.tenant_id is not None
    assignments = await validate_assignments(db, body.roles)

    if await db.scalar(select(User.id).where(User.phone == body.phone)) is not None:
        raise Conflict("A user with this phone number already exists.")
    if body.email and await email_taken(db, body.email):
        raise Conflict("That email address is already in use.")

    user = User(
        id=uuid.uuid4(),
        tenant_id=actor.tenant_id,
        phone=body.phone,
        display_name=body.display_name,
        email=body.email,
    )
    user.roles = _role_rows(actor, user.id, assignments)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:  # a concurrent create won the unique index
        raise Conflict("A user with this phone number or email already exists.") from exc

    await audit.record(
        db,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        after=_snapshot(user),
    )
    return user


async def update_user(
    db: AsyncSession, actor: Principal, user_id: uuid.UUID, body: AdminUserUpdate
) -> User:
    user = await get_user(db, user_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("is_active") is False and user.id == actor.user_id:
        raise Conflict("You can't deactivate your own account.")
    if changes.get("email") and await email_taken(db, changes["email"], exclude_user_id=user.id):
        raise Conflict("That email address is already in use.")

    before = _snapshot(user)
    for field in ("display_name", "email", "is_active"):
        if field in changes and not (field != "email" and changes[field] is None):
            setattr(user, field, changes[field])
    try:
        await db.flush()
    except IntegrityError as exc:
        raise Conflict("That email address is already in use.") from exc

    after = _snapshot(user)
    if before == after:
        return user
    await audit.record(
        db,
        action="user.updated",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        before=before,
        after=after,
    )
    if before["is_active"] and not after["is_active"]:
        # Deactivation must lock the user out now, not when tokens expire.
        await auth_service.revoke_all_sessions(
            db, user.id, user.tenant_id, reason="deactivated", actor=actor
        )
    return user


async def replace_roles(
    db: AsyncSession, actor: Principal, user_id: uuid.UUID, roles: list[RoleAssignment]
) -> User:
    user = await get_user(db, user_id)
    assignments = await validate_assignments(db, roles)
    if user.id == actor.user_id and Permission.USER_MANAGE not in permissions_for(
        a.role for a in assignments
    ):
        raise Conflict("You can't remove your own user-management access.")

    before = _snapshot(user)
    wanted = {(a.role, a.department_id, a.jurisdiction_id): a for a in assignments}
    current = {(r.role, r.department_id, r.jurisdiction_id): r for r in user.roles}

    # Apply the difference rather than delete-all-then-insert: unchanged
    # grants keep their identity and history, and the unique index never
    # sees a transient duplicate.
    for key, row in current.items():
        if key not in wanted:
            user.roles.remove(row)
    added = [a for key, a in wanted.items() if key not in current]
    user.roles.extend(_role_rows(actor, user.id, added))
    await db.flush()

    after = _snapshot(user)
    if before != after:
        await audit.record(
            db,
            action="user.roles_changed",
            entity_type="user",
            entity_id=user.id,
            actor=actor,
            before={"roles": before["roles"]},
            after={"roles": after["roles"]},
        )
    return user
