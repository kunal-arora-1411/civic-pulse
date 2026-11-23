from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.domains.org import service
from app.domains.org.models import JurisdictionKind
from app.domains.org.schemas import (
    DepartmentCreate,
    DepartmentOut,
    DepartmentPage,
    JurisdictionPage,
)
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/departments",
    operation_id="admin_list_departments",
    response_model=DepartmentPage,
    responses=error_responses(401, 403, 422),
)
async def list_departments(
    _: Annotated[Principal, require(Permission.CONFIG_READ)],
    db: DbSession,
    page: PageParamsDep,
    is_active: bool | None = None,
    sort: Annotated[
        str | None, Query(description="`name` (default), `code` or `created_at`; prefix `-`.")
    ] = None,
) -> DepartmentPage:
    items, total = await service.list_departments(db, page, is_active=is_active, sort=sort)
    return DepartmentPage(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post(
    "/departments",
    operation_id="admin_create_department",
    response_model=DepartmentOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 409, 422),
)
async def create_department(
    principal: Annotated[Principal, require(Permission.CONFIG_MANAGE)],
    db: DbSession,
    body: DepartmentCreate,
) -> DepartmentOut:
    return await service.create_department(db, principal, body)


@router.get(
    "/jurisdictions",
    operation_id="admin_list_jurisdictions",
    response_model=JurisdictionPage,
    responses=error_responses(401, 403, 422),
)
async def list_jurisdictions(
    _: Annotated[Principal, require(Permission.CONFIG_READ)],
    db: DbSession,
    page: PageParamsDep,
    kind: JurisdictionKind | None = None,
    parent_id: uuid.UUID | None = None,
    include_geometry: Annotated[
        bool, Query(description="Include each jurisdiction's GeoJSON geometry.")
    ] = False,
    sort: Annotated[
        str | None, Query(description="`code` (default) or `name`; prefix `-`.")
    ] = None,
) -> JurisdictionPage:
    items, total = await service.list_jurisdictions(
        db, page, kind=kind, parent_id=parent_id, include_geometry=include_geometry, sort=sort
    )
    return JurisdictionPage(items=items, total=total, limit=page.limit, offset=page.offset)
