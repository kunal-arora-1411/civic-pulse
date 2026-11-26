"""Seed development data (idempotent). Synthetic data only, never production.

    uv run python scripts/seed.py                         # on the host
    docker compose -f infra/docker-compose.yml exec api python scripts/seed.py

Creates the data in docs/api/phase-0-contract.md (tenants demo-city and
other-city, four departments, the city boundary with two zones and four
wards for demo-city, one user per role) and, from scripts/seed_phase1.py,
the Phase 1 additions: five categories, the default workflow for both
tenants and about 60 synthetic issues with processed placeholder photos.
scripts/seed_phase2.py then adds severity rules, places of interest, the
matching and priority configs, duplicate clusters and two open review
tasks, and computes severity and priority for every issue.
scripts/seed_analytics.py adds about 90 days of varied history (360 more
issues across the lifecycle, duplicates and match decisions) so the
analytics dashboard looks real.
Running it again converges on the same state: names, geometry, roles and
categories are reset to these values, and existing issues are left alone.
Resolution SLA targets are set for every category (tighter for critical
issues); the trigger schedules issues against them as they are written.

The ward polygons are SYNTHETIC rectangles around central Bengaluru
(~12.97 N, 77.59 E). A second synthetic area around Ramesh Nagar in West
Delhi (~28.65 N, 77.13 E) gives Demo City a city boundary, a zone and four
wards there too, so the report flow can be tried from Delhi with a real
GPS fix. The seeded issues all stay in Bengaluru. None of these are real
municipal boundaries.
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
from app.domains.org.models import (
    Department,
    Jurisdiction,
    JurisdictionKind,
    Team,
    TeamCategory,
    TeamJurisdiction,
    TeamMember,
)
from app.domains.priority.service import recompute_tenant
from app.domains.rbac.models import UserRole
from app.domains.rbac.roles import Role
from app.domains.sla.models import SlaTarget
from app.domains.tenants.models import Tenant
from app.domains.users.models import User
from app.domains.workflow.service import install_default_transitions
from scripts import seed_analytics as analytics
from scripts import seed_phase1 as phase1
from scripts import seed_phase2 as phase2

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


# Synthetic grid around Ramesh Nagar, West Delhi.
D_WEST, D_MID_LON, D_EAST = 77.09, 77.13, 77.17
D_SOUTH, D_MID_LAT, D_NORTH = 28.62, 28.65, 28.68


@dataclass(frozen=True)
class Area:
    code: str
    name: str
    kind: JurisdictionKind
    bbox: tuple[float, float, float, float]
    parent: str | None = None


AREAS = [
    # The city boundary decides what is "in jurisdiction" for reports and
    # where the map starts (Phase 1).
    Area("SYN-CITY", "Demo City (synthetic)", JurisdictionKind.CITY, (WEST, SOUTH, EAST, NORTH)),
    Area(
        "SYN-ZN",
        "Synthetic Zone North",
        JurisdictionKind.ZONE,
        (WEST, MID_LAT, EAST, NORTH),
        "SYN-CITY",
    ),
    Area(
        "SYN-ZS",
        "Synthetic Zone South",
        JurisdictionKind.ZONE,
        (WEST, SOUTH, EAST, MID_LAT),
        "SYN-CITY",
    ),
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

# A second, separate piece of Demo City in West Delhi. Any of the tenant's
# city boundaries counts as "in jurisdiction" (geo.place), so reports there
# get a ward and a zone like anywhere else. Kept out of AREAS so the seeded
# issues and their wards stay exactly as before.
DELHI_AREAS = [
    Area(
        "DEL-CITY",
        "Demo City, West Delhi (synthetic)",
        JurisdictionKind.CITY,
        (D_WEST, D_SOUTH, D_EAST, D_NORTH),
    ),
    Area(
        "DEL-ZW",
        "Synthetic Zone West Delhi",
        JurisdictionKind.ZONE,
        (D_WEST, D_SOUTH, D_EAST, D_NORTH),
        "DEL-CITY",
    ),
    Area(
        "DEL-W01",
        "Synthetic Ward D1 (Rajouri Garden)",
        JurisdictionKind.WARD,
        (D_WEST, D_MID_LAT, D_MID_LON, D_NORTH),
        "DEL-ZW",
    ),
    Area(
        "DEL-W02",
        "Synthetic Ward D2 (Ramesh Nagar)",
        JurisdictionKind.WARD,
        (D_MID_LON, D_MID_LAT, D_EAST, D_NORTH),
        "DEL-ZW",
    ),
    Area(
        "DEL-W03",
        "Synthetic Ward D3 (Tagore Garden)",
        JurisdictionKind.WARD,
        (D_WEST, D_SOUTH, D_MID_LON, D_MID_LAT),
        "DEL-ZW",
    ),
    Area(
        "DEL-W04",
        "Synthetic Ward D4 (Kirti Nagar)",
        JurisdictionKind.WARD,
        (D_MID_LON, D_SOUTH, D_EAST, D_MID_LAT),
        "DEL-ZW",
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
    # Phase 2: more reporters, so duplicate clusters have distinct people.
    SeedUser("+919000000006", "Demo Citizen Two", Role.CITIZEN, "demo-city"),
    SeedUser("+919000000007", "Demo Citizen Three", Role.CITIZEN, "demo-city"),
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


async def _upsert_team(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    department_id: uuid.UUID,
    *,
    jurisdiction_id: uuid.UUID,
    category_ids: list[uuid.UUID],
    lead_id: uuid.UUID,
) -> uuid.UUID:
    """Phase 3: a field team in Roads covering Zone North, with the seeded
    field worker as its lead."""
    team_id = await db.scalar(
        pg_insert(Team)
        .values(
            tenant_id=tenant_id,
            department_id=department_id,
            name="Roads North",
            schedule={
                "timezone": "Asia/Kolkata",
                "days": [{"weekday": d, "start": "09:00", "end": "18:00"} for d in range(6)],
            },
        )
        .on_conflict_do_update(
            constraint="uq_teams_tenant_id_department_id_name", set_={"is_active": True}
        )
        .returning(Team.id)
    )
    assert team_id is not None
    for model, values in (
        (TeamMember, {"user_id": lead_id, "team_role": "lead"}),
        (TeamJurisdiction, {"jurisdiction_id": jurisdiction_id}),
        *((TeamCategory, {"category_id": c}) for c in category_ids),
    ):
        await db.execute(
            pg_insert(model)
            .values(tenant_id=tenant_id, team_id=team_id, **values)
            .on_conflict_do_nothing()
        )
    return team_id


# Resolution targets in hours per category: (any band, critical, escalate
# to the admins this long after a breach).
SLA_TARGETS: dict[str, tuple[int, int, int]] = {
    "pothole": (168, 48, 48),
    "waste": (48, 12, 24),
    "waterlogging": (72, 12, 24),
    "streetlight": (96, 24, 48),
    "drainage": (120, 24, 48),
}


async def _upsert_sla_targets(
    db: AsyncSession, tenant_id: uuid.UUID, categories: dict[str, uuid.UUID]
) -> None:
    for code, (any_band, critical, escalate) in SLA_TARGETS.items():
        for band, hours in ((None, any_band), ("critical", critical)):
            values = {"resolve_hours": hours, "escalate_after_hours": escalate}
            await db.execute(
                pg_insert(SlaTarget)
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    category_id=categories[code],
                    priority_band=band,
                    **values,
                )
                .on_conflict_do_update(
                    constraint="uq_sla_targets_tenant_id_category_id_priority_band", set_=values
                )
            )


async def run() -> dict[str, int]:
    if get_settings().is_production:
        raise SystemExit("Refusing to seed synthetic data into a production environment.")
    await phase2.check_vision_model()

    async with system_session(reason="development seed") as db:
        tenant_ids = {slug: await _upsert_tenant(db, slug, name) for slug, name in TENANTS.items()}
        demo = tenant_ids["demo-city"]

        departments = {
            code: await _upsert_department(db, demo, code, name) for code, name in DEPARTMENTS
        }
        areas: dict[str, uuid.UUID] = {}
        for area in [*AREAS, *DELHI_AREAS]:  # parents are listed before their children
            parent_id = areas[area.parent] if area.parent else None
            areas[area.code] = await _upsert_area(db, demo, area, parent_id)

        user_ids: dict[str, uuid.UUID] = {}
        for seed in USERS:
            tenant_id = tenant_ids[seed.tenant] if seed.tenant else None
            department_id = departments[seed.department] if seed.department else None
            user_ids[seed.phone] = await _upsert_user(db, seed, tenant_id, department_id)

        categories = await phase1.seed_categories(db, demo, departments)
        await _upsert_sla_targets(db, demo, categories)
        for tenant_id in tenant_ids.values():
            await install_default_transitions(db, tenant_id)
        await _upsert_team(
            db,
            demo,
            departments["ROADS"],
            jurisdiction_id=areas["SYN-ZN"],
            category_ids=[categories["pothole"]],
            lead_id=user_ids["+919000000004"],
        )

    wards = {areas[area.code]: area.bbox for area in AREAS if area.kind is JurisdictionKind.WARD}
    issues = await phase1.seed_issues(
        tenant_id=demo,
        categories=categories,
        wards=wards,
        citizen_id=user_ids["+919000000005"],
        operator_id=user_ids["+919000000002"],
    )
    places = await phase2.seed_rules_places_configs(demo, wards)
    matching = await phase2.seed_matching_examples(
        tenant_id=demo,
        categories=categories,
        wards=wards,
        reporters=[user_ids[p] for p in ("+919000000005", "+919000000006", "+919000000007")],
    )
    # After the matching examples, so the extra issues can't change what
    # those reports match.
    history = await analytics.seed_history(
        tenant_id=demo,
        categories=categories,
        wards=wards,
        reporters=[user_ids[p] for p in ("+919000000005", "+919000000006", "+919000000007")],
        operator_id=user_ids["+919000000002"],
    )
    await recompute_tenant(demo)
    return {
        "tenants": len(tenant_ids),
        "departments": len(departments),
        "jurisdictions": len(areas),
        "users": len(USERS),
        "categories": len(categories),
        "sla targets": 2 * len(SLA_TARGETS),
        "issues": issues,
        "places": places,
        "analytics issues": history,
        **{f"extra reports {status}": count for status, count in sorted(matching.items())},
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
