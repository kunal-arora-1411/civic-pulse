from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.domains.auth.dependencies import RequestTenantId
from app.domains.categories import service
from app.domains.categories.schemas import (
    CategoryCreate,
    CategoryOut,
    CategoryPage,
    CategoryUpdate,
)
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

router = APIRouter(tags=["categories"])


@router.get(
    "/categories",
    operation_id="categories_list",
    response_model=list[CategoryOut],
    responses=error_responses(401, 403, 404),
)
async def list_categories(_: RequestTenantId, db: DbSession) -> list[CategoryOut]:
    """Active categories as a flat array ordered by `sort_order`, for the report form."""
    return await service.list_active(db)


@router.get(
    "/admin/categories",
    operation_id="admin_list_categories",
    response_model=CategoryPage,
    tags=["admin"],
    responses=error_responses(401, 403, 422),
)
async def admin_list_categories(
    _: Annotated[Principal, require(Permission.CONFIG_READ)],
    db: DbSession,
    page: PageParamsDep,
    is_active: bool | None = None,
    sort: Annotated[
        str | None,
        Query(description="`sort_order` (default), `code` or `created_at`; prefix `-`."),
    ] = None,
) -> CategoryPage:
    items, total = await service.list_all(db, page, is_active=is_active, sort=sort)
    return CategoryPage(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post(
    "/admin/categories",
    operation_id="admin_create_category",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
    tags=["admin"],
    responses=error_responses(401, 403, 409, 422),
)
async def admin_create_category(
    principal: Annotated[Principal, require(Permission.CONFIG_MANAGE)],
    db: DbSession,
    body: CategoryCreate,
) -> CategoryOut:
    return await service.create(db, principal, body)


@router.patch(
    "/admin/categories/{category_id}",
    operation_id="admin_update_category",
    response_model=CategoryOut,
    tags=["admin"],
    responses=error_responses(401, 403, 404, 409, 422),
)
async def admin_update_category(
    principal: Annotated[Principal, require(Permission.CONFIG_MANAGE)],
    db: DbSession,
    category_id: uuid.UUID,
    body: CategoryUpdate,
) -> CategoryOut:
    return await service.update(db, principal, category_id, body)
