from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import error_responses
from app.domains.tenants.dependencies import HeaderTenant
from app.domains.tenants.schemas import TenantOut

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get(
    "/current",
    operation_id="tenants_get_current",
    response_model=TenantOut,
    responses=error_responses(404, 422),
)
async def get_current_tenant(tenant: HeaderTenant) -> TenantOut:
    return TenantOut.model_validate(tenant)
