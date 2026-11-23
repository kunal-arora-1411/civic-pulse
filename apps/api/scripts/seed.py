"""Seed development data (idempotent). Synthetic data only, never production.

    uv run python scripts/seed.py                         # on the host
    docker compose -f infra/docker-compose.yml exec api python scripts/seed.py

Creates exactly the data in docs/api/phase-0-contract.md: tenants demo-city
and other-city, four departments, two zones and four wards for demo-city, and
one user per role. Running it again converges on the same state: names,
geometry and role assignments are reset to these values.

The ward polygons are SYNTHETIC rectangles around central Bengaluru
(~12.97 N, 77.59 E). They are not real municipal boundaries.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.tenancy import system_session
from app.domains.org.models import Department, Jurisdiction, JurisdictionKind
from app.domains.rbac.models import UserRole
from app.domains.rbac.roles import Role
from app.domains.tenants.models import Tenant
from app.domains.users.models import User

TENANTS = {"demo-city": "Demo City", "other-city": "Other City"}

DEPARTMENTS = [
    ("ROADS", "Roads"),
    ("SOLID_WASTE", "Solid Waste"),
    ("STORM_WATER_DRAINS", "Storm Water Drains"),
    ("STREET_LIGHTING", "Street Lighting"),
]

# Synthetic grid around central Bengaluru: (min_lon, min_lat, max_lon, max_lat).
WEST, MID_LON, EAST = 77.55, 77.59, 77.63
SOUTH, MID_LAT, NORTH = 12.93, 12.97, 13.01


@dataclass(frozen=True)
class Area:
    code: str
    name: str
    kind: JurisdictionKind
    bbox: tuple[float, float, float, float]
    parent: str | None = None


AREAS = [
    Area("SYN-ZN", "Synthetic Zone North", JurisdictionKind.ZONE, (WEST, MID_LAT, EAST, NORTH)),
    Area("SYN-ZS", "Synthetic Zone South", JurisdictionKind.ZONE, (WEST, SOUTH, EAST, MID_LAT)),
    Area(
        "SYN-W01",
        "Synthetic Ward 1 (North-West)",
        JurisdictionKind.WARD,
        (WEST, MID_LAT, MID_LON, NORTH),
        "SYN-ZN",
    ),
    Area(
        "SYN-W02",
        "Synthetic Ward 2 (North-East)",
        JurisdictionKind.WARD,
        (MID_LON, MID_LAT, EAST, NORTH),
        "SYN-ZN",
    ),
    Area(
        "SYN-W03",
        "Synthetic Ward 3 (South-West)",
        JurisdictionKind.WARD,
        (WEST, SOUTH, MID_LON, MID_LAT),
        "SYN-ZS",
    ),
    Area(
        "SYN-W04",
        "Synthetic Ward 4 (South-East)",
        JurisdictionKind.WARD,
        (MID_LON, SOUTH, EAST, MID_LAT),
        "SYN-ZS",
    ),
]


@dataclass(frozen=True)
class SeedUser:
    phone: str
    name: str
    role: Role
    tenant: str | None
    department: str | None = None


USERS = [
    SeedUser("+919000000000", "Platform Admin (seed)", Role.PLATFORM_ADMIN, None),
    SeedUser("+919000000001", "Demo Municipal Admin", Role.MUNICIPAL_ADMIN, "demo-city"),
    SeedUser("+919000000002", "Demo Operator", Role.OPERATOR, "demo-city"),
    SeedUser("+919000000003", "Demo Supervisor (Roads)", Role.SUPERVISOR, "demo-city", "ROADS"),
    SeedUser("+919000000004", "Demo Field Worker (Roads)", Role.FIELD_WORKER, "demo-city", "ROADS"),
    SeedUser("+919000000005", "Demo Citizen", Role.CITIZEN, "demo-city"),
    SeedUser("+919100000001", "Other City Admin", Role.MUNICIPAL_ADMIN, "other-city"),
]


async def _upsert_tenant(db: AsyncSession, slug: str, name: str) -> uuid.UUID:
    stmt = pg_insert(Tenant).values(id=uuid.uuid4(), slug=slug, name=name)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Tenant.slug], set_={"name": name, "is_active": True}
    ).returning(Tenant.id)
    return (await db.execute(stmt)).scalar_one()


async def _upsert_department(
    db: AsyncSession, tenant_id: uuid.UUID, code: str, name: str
) -> uuid.UUID:
    stmt = pg_insert(Department).values(id=uuid.uuid4(), tenant_id=tenant_id, code=code, name=name)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_departments_tenant_id_code", set_={"name": name, "is_active": True}
    ).returning(Department.id)
    return (await db.execute(stmt)).scalar_one()


async def _upsert_area(
    db: AsyncSession, tenant_id: uuid.UUID, area: Area, parent_id: uuid.UUID | None
) -> uuid.UUID:
    geom = func.ST_Multi(func.ST_MakeEnvelope(*area.bbox, 4326))
    values = {"kind": area.kind, "name": area.name, "parent_id": parent_id, "geom": geom}
    stmt = pg_insert(Jurisdiction).values(
        id=uuid.uuid4(), tenant_id=tenant_id, code=area.code, **values
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_jurisdictions_tenant_id_code", set_=values
    ).returning(Jurisdiction.id)
    return (await db.execute(stmt)).scalar_one()


async def _upsert_user(
    db: AsyncSession, seed: SeedUser, tenant_id: uuid.UUID | None, department_id: uuid.UUID | None
) -> uuid.UUID:
    stmt = pg_insert(User).values(
        id=uuid.uuid4(), tenant_id=tenant_id, phone=seed.phone, display_name=seed.name
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_users_tenant_id_phone",
        set_={"display_name": seed.name, "is_active": True},
    ).returning(User.id)
    user_id = (await db.execute(stmt)).scalar_one()

    # Reset role assignments to exactly the seeded one.
    await db.execute(delete(UserRole).where(UserRole.user_id == user_id))
    db.add(
        UserRole(tenant_id=tenant_id, user_id=user_id, role=seed.role, department_id=department_id)
    )
    await db.flush()
    return user_id


async def run() -> dict[str, int]:
    if get_settings().is_production:
        raise SystemExit("Refusing to seed synthetic data into a production environment.")

    async with system_session(reason="development seed") as db:
        tenant_ids = {slug: await _upsert_tenant(db, slug, name) for slug, name in TENANTS.items()}
        demo = tenant_ids["demo-city"]

        departments = {
            code: await _upsert_department(db, demo, code, name) for code, name in DEPARTMENTS
        }
        areas: dict[str, uuid.UUID] = {}
        for area in AREAS:  # zones come first, so parents exist before wards
            parent_id = areas[area.parent] if area.parent else None
            areas[area.code] = await _upsert_area(db, demo, area, parent_id)

        for seed in USERS:
            tenant_id = tenant_ids[seed.tenant] if seed.tenant else None
            department_id = departments[seed.department] if seed.department else None
            await _upsert_user(db, seed, tenant_id, department_id)

        return {
            "tenants": len(tenant_ids),
            "departments": len(departments),
            "jurisdictions": len(areas),
            "users": len(USERS),
        }


async def _main() -> None:
    try:
        summary = await run()
    finally:
        await get_engine().dispose()
    print("Seeded (synthetic data):", ", ".join(f"{v} {k}" for k, v in summary.items()))
    print("Sign in with any seeded phone; with DEV_FIXED_OTP=true the code 000000 works.")
    for seed in USERS:
        where = seed.tenant or "platform (no X-Tenant)"
        print(f"  {seed.phone}  {seed.role.value:<16} {where}")


if __name__ == "__main__":
    asyncio.run(_main())
