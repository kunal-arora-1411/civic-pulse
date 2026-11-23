from __future__ import annotations

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from scripts import seed
from tests.helpers import RecordingSms, login


async def _counts(engine: AsyncEngine) -> dict[str, int]:
    queries = {
        "tenants": "SELECT count(*) FROM tenants WHERE slug IN ('demo-city', 'other-city')",
        "departments": "SELECT count(*) FROM departments d JOIN tenants t ON t.id = d.tenant_id "
        "WHERE t.slug = 'demo-city'",
        "zones": "SELECT count(*) FROM jurisdictions WHERE code LIKE 'SYN-Z%'",
        "wards": "SELECT count(*) FROM jurisdictions WHERE code LIKE 'SYN-W%' "
        "AND parent_id IS NOT NULL AND ST_GeometryType(geom) = 'ST_MultiPolygon'",
        "seed_users": "SELECT count(*) FROM users WHERE phone LIKE '+9190000000%' "
        "OR phone = '+919100000001'",
        "seed_roles": "SELECT count(*) FROM user_roles r JOIN users u ON u.id = r.user_id "
        "WHERE u.phone LIKE '+9190000000%' OR u.phone = '+919100000001'",
    }
    async with engine.connect() as conn:
        return {name: (await conn.execute(text(sql))).scalar_one() for name, sql in queries.items()}


async def test_seed_is_idempotent_and_usable(
    owner_engine: AsyncEngine, client: httpx.AsyncClient, sms: RecordingSms
) -> None:
    await seed.run()
    first = await _counts(owner_engine)
    await seed.run()
    assert await _counts(owner_engine) == first
    assert first == {
        "tenants": 2,
        "departments": 4,
        "zones": 2,
        "wards": 4,
        "seed_users": 7,
        "seed_roles": 7,
    }

    # Wards sit inside their zone, around central Bengaluru.
    async with owner_engine.connect() as conn:
        contained = (
            await conn.execute(
                text(
                    "SELECT bool_and(ST_Within(w.geom, z.geom)) FROM jurisdictions w "
                    "JOIN jurisdictions z ON z.id = w.parent_id WHERE w.code LIKE 'SYN-W%'"
                )
            )
        ).scalar_one()
        centre_ward = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM jurisdictions WHERE code LIKE 'SYN-W%' "
                    "AND ST_Intersects(geom, ST_SetSRID(ST_Point(77.59, 12.97), 4326))"
                )
            )
        ).scalar_one()
    assert contained is True
    assert centre_ward == 4  # the four wards meet at the centre point

    supervisor = await login(client, sms, "+919000000003", "demo-city")
    assert supervisor.user["roles"][0]["role"] == "supervisor"
    assert supervisor.user["roles"][0]["department_id"] is not None
    platform = await login(client, sms, "+919000000000", None)
    assert platform.user["permissions"] == ["tenant:manage"]
