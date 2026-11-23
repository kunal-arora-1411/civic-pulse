"""A self-contained city for Phase 1 tests.

Each call makes a fresh tenant laid out like the dev seed (a 0.08-degree
city split into two zones and four wards around central Bengaluru), with
two categories, the default workflow and signed-in users for each role.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.tenancy import system_session
from app.domains.workflow.service import install_default_transitions
from tests.factories import (
    TenantRow,
    UserRow,
    create_category,
    create_department,
    create_jurisdiction,
    create_tenant,
    create_user,
    square_wkt,
)
from tests.helpers import RecordingSms, Session, login

WEST, MID_LNG, EAST = 77.55, 77.59, 77.63
SOUTH, MID_LAT, NORTH = 12.93, 12.97, 13.01

# Points well inside each ward.
NW = (77.57, 12.99)
NE = (77.61, 12.99)
SW = (77.57, 12.95)
SE = (77.61, 12.95)
OUTSIDE = (77.70, 12.80)


@dataclass
class City:
    tenant: TenantRow
    city_id: uuid.UUID
    zones: dict[str, uuid.UUID]
    wards: dict[str, uuid.UUID]
    roads: uuid.UUID
    pothole: uuid.UUID  # 1-3 photos, fields road_name (text) and size (select, required)
    waste: uuid.UUID  # 0-3 photos, no fields
    citizen_row: UserRow
    citizen: Session
    operator: Session
    admin: Session
    supervisor: Session
    extra: dict[str, Session] = field(default_factory=dict)


POTHOLE_FIELDS = [
    {"key": "road_name", "type": "text", "required": False, "label_i18n": {"en": "Road"}},
    {
        "key": "size",
        "type": "select",
        "required": True,
        "label_i18n": {"en": "Size", "hi": "आकार"},
        "options": [
            {"value": "small", "label_i18n": {"en": "Small"}},
            {"value": "large", "label_i18n": {"en": "Large"}},
        ],
    },
]


async def make_city(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> City:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn, name="Phase One City")
        city_id = await create_jurisdiction(
            conn, tenant.id, kind="city", code="CITY", wkt=square_wkt(WEST, SOUTH, EAST, NORTH)
        )
        zones = {
            "N": await create_jurisdiction(
                conn,
                tenant.id,
                kind="zone",
                code="ZN",
                parent_id=city_id,
                wkt=square_wkt(WEST, MID_LAT, EAST, NORTH),
            ),
            "S": await create_jurisdiction(
                conn,
                tenant.id,
                kind="zone",
                code="ZS",
                parent_id=city_id,
                wkt=square_wkt(WEST, SOUTH, EAST, MID_LAT),
            ),
        }
        boxes = {
            "NW": ("N", (WEST, MID_LAT, MID_LNG, NORTH)),
            "NE": ("N", (MID_LNG, MID_LAT, EAST, NORTH)),
            "SW": ("S", (WEST, SOUTH, MID_LNG, MID_LAT)),
            "SE": ("S", (MID_LNG, SOUTH, EAST, MID_LAT)),
        }
        wards = {
            name: await create_jurisdiction(
                conn,
                tenant.id,
                kind="ward",
                code=f"W-{name}",
                name=f"Ward {name}",
                parent_id=zones[zone],
                wkt=square_wkt(*box),
            )
            for name, (zone, box) in boxes.items()
        }
        roads = await create_department(conn, tenant.id, code="ROADS", name="Roads")
        pothole = await create_category(
            conn,
            tenant.id,
            code="pothole",
            min_photos=1,
            max_photos=3,
            fields=POTHOLE_FIELDS,
            sort_order=10,
        )
        waste = await create_category(conn, tenant.id, code="waste", min_photos=0, max_photos=3)
        citizen = await create_user(conn, tenant.id, "citizen", display_name="Asha Citizen")
        operator = await create_user(conn, tenant.id, "operator", display_name="Omar Operator")
        admin = await create_user(conn, tenant.id, "municipal_admin", display_name="Ada Admin")
        supervisor = await create_user(conn, tenant.id, "supervisor", display_name="Sam Supervisor")

    async with system_session(reason="test setup: default workflow") as db:
        await install_default_transitions(db, tenant.id)

    return City(
        tenant=tenant,
        city_id=city_id,
        zones=zones,
        wards=wards,
        roads=roads,
        pothole=pothole,
        waste=waste,
        citizen_row=citizen,
        citizen=await login(client, sms, citizen.phone, tenant.slug),
        operator=await login(client, sms, operator.phone, tenant.slug),
        admin=await login(client, sms, admin.phone, tenant.slug),
        supervisor=await login(client, sms, supervisor.phone, tenant.slug),
    )


async def login_new(
    client: httpx.AsyncClient,
    sms: RecordingSms,
    owner_engine: AsyncEngine,
    city: City,
    *roles: str,
    jurisdiction_id: uuid.UUID | None = None,
    display_name: str = "Extra User",
) -> Session:
    async with owner_engine.begin() as conn:
        user = await create_user(
            conn, city.tenant.id, *roles, jurisdiction_id=jurisdiction_id, display_name=display_name
        )
    return await login(client, sms, user.phone, city.tenant.slug)
