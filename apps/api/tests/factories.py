"""Test data, written through the owner connection (which bypasses RLS).

Every helper generates unique slugs and phone numbers, so tests don't need to
clean up after each other.
"""

from __future__ import annotations

import itertools
import random
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_phone_counter = itertools.count(random.randint(0, 10_000) * 10_000)


def unique_phone() -> str:
    # +91 8xxxxxxxxx: valid Indian mobile numbers, never the seeded 90000/91000 range.
    return f"+918{next(_phone_counter) % 1_000_000_000:09d}"


def unique_slug(prefix: str = "t") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@dataclass
class TenantRow:
    id: uuid.UUID
    slug: str


@dataclass
class UserRow:
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    phone: str
    roles: list[str] = field(default_factory=list)


async def create_tenant(conn: AsyncConnection, *, name: str = "Test City") -> TenantRow:
    slug = unique_slug()
    tenant_id = (
        await conn.execute(
            text("INSERT INTO tenants (slug, name) VALUES (:slug, :name) RETURNING id"),
            {"slug": slug, "name": name},
        )
    ).scalar_one()
    return TenantRow(id=tenant_id, slug=slug)


async def create_user(
    conn: AsyncConnection,
    tenant_id: uuid.UUID | None,
    *roles: str,
    phone: str | None = None,
    display_name: str | None = "Test User",
    department_id: uuid.UUID | None = None,
    jurisdiction_id: uuid.UUID | None = None,
    is_active: bool = True,
) -> UserRow:
    phone = phone or unique_phone()
    user_id = (
        await conn.execute(
            text(
                "INSERT INTO users (tenant_id, phone, display_name, is_active) "
                "VALUES (:tenant_id, :phone, :display_name, :is_active) RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "phone": phone,
                "display_name": display_name,
                "is_active": is_active,
            },
        )
    ).scalar_one()
    for role in roles:
        await conn.execute(
            text(
                "INSERT INTO user_roles (tenant_id, user_id, role, department_id, jurisdiction_id) "
                "VALUES (:tenant_id, :user_id, :role, :department_id, :jurisdiction_id)"
            ),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "role": role,
                "department_id": department_id,
                "jurisdiction_id": jurisdiction_id,
            },
        )
    return UserRow(id=user_id, tenant_id=tenant_id, phone=phone, roles=list(roles))


async def create_department(
    conn: AsyncConnection, tenant_id: uuid.UUID, *, code: str = "ROADS", name: str = "Roads"
) -> uuid.UUID:
    return (
        await conn.execute(
            text(
                "INSERT INTO departments (tenant_id, name, code) "
                "VALUES (:tenant_id, :name, :code) RETURNING id"
            ),
            {"tenant_id": tenant_id, "name": name, "code": code},
        )
    ).scalar_one()


async def create_jurisdiction(
    conn: AsyncConnection,
    tenant_id: uuid.UUID,
    *,
    kind: str,
    code: str,
    name: str | None = None,
    parent_id: uuid.UUID | None = None,
    wkt: str | None = None,
) -> uuid.UUID:
    return (
        await conn.execute(
            text(
                "INSERT INTO jurisdictions (tenant_id, parent_id, kind, name, code, geom) "
                "VALUES (:tenant_id, :parent_id, :kind, :name, :code, "
                "        CASE WHEN CAST(:wkt AS text) IS NULL THEN NULL "
                "             ELSE ST_Multi(ST_GeomFromText(:wkt, 4326)) END) "
                "RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "parent_id": parent_id,
                "kind": kind,
                "name": name or code,
                "code": code,
                "wkt": wkt,
            },
        )
    ).scalar_one()
