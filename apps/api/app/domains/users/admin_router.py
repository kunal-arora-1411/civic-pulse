from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.core import idempotency
from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.idempotency import IdempotencyKeyHeader
from app.core.pagination import PageParamsDep
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.rbac.roles import Role
from app.domains.users import admin_service
from app.domains.users.schemas import (
    AdminUser,
    AdminUserCreate,
    AdminUserPage,
    AdminUserUpdate,
    RolesUpdate,
)
from app.domains.users.service import to_admin

router = APIRouter(prefix="/admin/users", tags=["admin"])

UserManager = Annotated[Principal, require(Permission.USER_MANAGE)]


@router.get(
    "",
    operation_id="admin_list_users",
    response_model=AdminUserPage,
    responses=error_responses(401, 403, 422),
)
async def list_users(
    _: UserManager,
    db: DbSession,
    page: PageParamsDep,
    q: Annotated[
        str | None, Query(max_length=100, description="Matches name, phone or email.")
    ] = None,
    role: Role | None = None,
    is_active: bool | None = None,
    sort: Annotated[
        str | None,
        Query(
            description="`created_at`, `display_name`, `phone` or `last_login_at`; prefix `-` "
            "for descending. Default `-created_at`."
        ),
    ] = None,
) -> AdminUserPage:
    items, total = await admin_service.list_users(
        db, page, q=q, role=role, is_active=is_active, sort=sort
    )
    return AdminUserPage(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post(
    "",
    operation_id="admin_create_user",
    response_model=AdminUser,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 409, 422),
)
async def create_user(
    principal: UserManager,
    db: DbSession,
    body: AdminUserCreate,
    idempotency_key: IdempotencyKeyHeader = None,
) -> Any:
    claim = await idempotency.begin(
        db,
        key=idempotency_key,
        scope="POST /admin/users",
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        body=body,
    )
    if isinstance(claim, Response):
        return claim
    user = to_admin(await admin_service.create_user(db, principal, body))
    await idempotency.complete(db, claim, status.HTTP_201_CREATED, user)
    return user


@router.get(
    "/{user_id}",
    operation_id="admin_get_user",
    response_model=AdminUser,
    responses=error_responses(401, 403, 404, 422),
)
async def get_user(_: UserManager, db: DbSession, user_id: uuid.UUID) -> AdminUser:
    return to_admin(await admin_service.get_user(db, user_id))


@router.patch(
    "/{user_id}",
    operation_id="admin_update_user",
    response_model=AdminUser,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def update_user(
    principal: UserManager, db: DbSession, user_id: uuid.UUID, body: AdminUserUpdate
) -> AdminUser:
    return to_admin(await admin_service.update_user(db, principal, user_id, body))


@router.put(
    "/{user_id}/roles",
    operation_id="admin_replace_user_roles",
    response_model=AdminUser,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def replace_roles(
    principal: UserManager, db: DbSession, user_id: uuid.UUID, body: RolesUpdate
) -> AdminUser:
    return to_admin(await admin_service.replace_roles(db, principal, user_id, body.roles))
