"""Resolving the tenant named by the X-Tenant header (unauthenticated requests)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from app.core.db import DbSession
from app.core.errors import NotFound
from app.core.tenancy import set_tenant
from app.domains.tenants import service
from app.domains.tenants.models import Tenant

_HEADER_DESCRIPTION = "Tenant slug, e.g. `demo-city`. Required for unauthenticated requests."


async def get_optional_header_tenant(
    db: DbSession,
    x_tenant: Annotated[
        str | None, Header(alias="X-Tenant", max_length=63, description=_HEADER_DESCRIPTION)
    ] = None,
) -> Tenant | None:
    if x_tenant is None:
        return None
    tenant = await service.get_active_by_slug(db, x_tenant)
    if tenant is None:
        raise NotFound("Unknown tenant.")
    await set_tenant(db, tenant.id)
    return tenant


async def get_header_tenant(
    db: DbSession,
    x_tenant: Annotated[
        str, Header(alias="X-Tenant", max_length=63, description=_HEADER_DESCRIPTION)
    ],
) -> Tenant:
    tenant = await get_optional_header_tenant(db, x_tenant)
    assert tenant is not None
    return tenant


OptionalHeaderTenant = Annotated[Tenant | None, Depends(get_optional_header_tenant)]
HeaderTenant = Annotated[Tenant, Depends(get_header_tenant)]
