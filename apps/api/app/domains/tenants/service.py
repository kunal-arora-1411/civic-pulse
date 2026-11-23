from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.tenants.models import Tenant


async def get_active_by_slug(db: AsyncSession, slug: str) -> Tenant | None:
    return await db.scalar(select(Tenant).where(Tenant.slug == slug, Tenant.is_active.is_(True)))


async def get_by_id(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant | None:
    return await db.get(Tenant, tenant_id)
