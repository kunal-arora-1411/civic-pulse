from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.db import DbSession
from app.core.errors import error_responses
from app.core.pagination import PageParamsDep
from app.domains.rbac.dependencies import require
from app.domains.rbac.permissions import Permission
from app.domains.rbac.principal import Principal
from app.domains.tenants import service
from app.domains.tenants.dependencies import HeaderTenant
from app.domains.tenants.schemas import PlatformTenant, PlatformTenantPage, TenantCreate, TenantOut

router = APIRouter(prefix="/tenants", tags=["tenants"])
platform_router = APIRouter(prefix="/platform/tenants", tags=["platform"])

TenantManager = Annotated[Principal, require(Permission.TENANT_MANAGE)]


@router.get(
    "/current",
    operation_id="tenants_get_current",
    response_model=TenantOut,
    responses=error_responses(404, 422),
)
async def get_current_tenant(tenant: HeaderTenant) -> TenantOut:
    return TenantOut.model_validate(tenant)


@platform_router.get(
    "",
    operation_id="platform_list_tenants",
    response_model=PlatformTenantPage,
    responses=error_responses(401, 403, 422),
)
async def list_tenants(
    _: TenantManager,
    db: DbSession,
    page: PageParamsDep,
    sort: Annotated[
        str | None, Query(description="`slug` (default), `name` or `created_at`; prefix `-`.")
    ] = None,
) -> PlatformTenantPage:
    items, total = await service.list_tenants(db, page, sort=sort)
    return PlatformTenantPage(items=items, total=total, limit=page.limit, offset=page.offset)


@platform_router.post(
    "",
    operation_id="platform_create_tenant",
    response_model=PlatformTenant,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 409, 422),
)
async def create_tenant(
    principal: TenantManager, db: DbSession, body: TenantCreate
) -> PlatformTenant:
    return await service.create_tenant(db, principal, body)
