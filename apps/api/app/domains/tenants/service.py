from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.core.pagination import PageParams, paginate, sort_clauses
from app.core.tenancy import rls_bypass
from app.domains.audit import service as audit
from app.domains.rbac.principal import Principal
from app.domains.tenants.models import Tenant
from app.domains.tenants.schemas import PlatformTenant, TenantCreate
from app.domains.workflow.service import install_default_transitions

SORTS = {"slug": Tenant.slug, "name": Tenant.name, "created_at": Tenant.created_at}


async def get_active_by_slug(db: AsyncSession, slug: str) -> Tenant | None:
    return await db.scalar(select(Tenant).where(Tenant.slug == slug, Tenant.is_active.is_(True)))


async def get_by_id(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant | None:
    return await db.get(Tenant, tenant_id)


async def list_tenants(
    db: AsyncSession, params: PageParams, *, sort: str | None
) -> tuple[list[PlatformTenant], int]:
    stmt = select(Tenant).order_by(*sort_clauses(sort, SORTS, default="slug", tiebreaker=Tenant.id))
    rows, total = await paginate(db, stmt, params)
    return [PlatformTenant.model_validate(row[0]) for row in rows], total


async def create_tenant(db: AsyncSession, actor: Principal, body: TenantCreate) -> PlatformTenant:
    if await db.scalar(select(Tenant.id).where(Tenant.slug == body.slug)) is not None:
        raise Conflict("A tenant with this slug already exists.", details={"slug": body.slug})
    tenant = Tenant(slug=body.slug, name=body.name)
    db.add(tenant)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise Conflict("A tenant with this slug already exists.") from exc
    await db.refresh(tenant)  # pick up server defaults (locales, flags)
    # A tenant without transitions can't move any issue, so it starts with
    # the defaults. The platform admin has no tenant context of its own.
    async with rls_bypass(db, reason="default workflow for a new tenant"):
        await install_default_transitions(db, tenant.id)
    out = PlatformTenant.model_validate(tenant)
    await audit.record(
        db,
        action="tenant.created",
        entity_type="tenant",
        entity_id=tenant.id,
        actor=actor,
        tenant_id=None,  # a platform event, not an event inside the new tenant
        after=out.model_dump(mode="json"),
    )
    return out
