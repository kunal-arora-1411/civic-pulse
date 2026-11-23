"""Platform administration: tenant provisioning."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import create_tenant, create_user, unique_slug
from tests.helpers import RecordingSms, Session, login, request_otp, verify_otp

TENANTS = "/api/v1/platform/tenants"


@pytest.fixture
async def platform_admin(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> Session:
    async with owner_engine.begin() as conn:
        user = await create_user(conn, None, "platform_admin")
    return await login(client, sms, user.phone, None)


async def test_create_and_list_tenants(
    client: httpx.AsyncClient, platform_admin: Session, owner_engine: AsyncEngine
) -> None:
    slug = unique_slug("city")
    created = await client.post(
        TENANTS, headers=platform_admin.headers, json={"slug": slug.upper(), "name": "New City"}
    )
    assert created.status_code == 201, created.text
    tenant = created.json()
    assert tenant["slug"] == slug
    assert tenant["supported_locales"] == ["en", "hi"]
    assert tenant["is_active"] is True

    listed = await client.get(
        TENANTS, headers=platform_admin.headers, params={"limit": 100, "sort": "-created_at"}
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == tenant["id"]

    # A platform event: no tenant on the audit row.
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT tenant_id, actor_id::text FROM audit_events "
                    "WHERE action = 'tenant.created' AND entity_id = :id"
                ),
                {"id": tenant["id"]},
            )
        ).one()
    assert row == (None, platform_admin.user["id"])


async def test_new_tenant_is_usable_right_away(
    client: httpx.AsyncClient, platform_admin: Session
) -> None:
    slug = unique_slug("city")
    await client.post(TENANTS, headers=platform_admin.headers, json={"slug": slug, "name": "Fresh"})
    current = await client.get("/api/v1/tenants/current", headers={"X-Tenant": slug})
    assert current.status_code == 200
    assert current.json()["name"] == "Fresh"


async def test_duplicate_and_invalid_slugs(
    client: httpx.AsyncClient, platform_admin: Session, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        existing = await create_tenant(conn)
    duplicate = await client.post(
        TENANTS, headers=platform_admin.headers, json={"slug": existing.slug, "name": "Dup"}
    )
    assert duplicate.status_code == 409
    for slug in ("-bad", "has space", "UNDER_SCORE", "a" * 64):
        response = await client.post(
            TENANTS, headers=platform_admin.headers, json={"slug": slug, "name": "X"}
        )
        assert response.status_code == 422, slug


async def test_platform_admins_have_no_tenant_data_access(
    client: httpx.AsyncClient, platform_admin: Session
) -> None:
    # Platform administration is not a back door into municipal data.
    for path in ("/api/v1/admin/users", "/api/v1/admin/audit-events"):
        response = await client.get(path, headers=platform_admin.headers)
        assert response.status_code == 403, path
    # And sending a tenant header doesn't change that.
    response = await client.get(
        "/api/v1/admin/users", headers={**platform_admin.headers, "X-Tenant": "demo-city"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_x_tenant_is_ignored_for_platform_tokens(
    client: httpx.AsyncClient, platform_admin: Session, owner_engine: AsyncEngine
) -> None:
    # The web app sends X-Tenant on every request; platform admins must still
    # be able to use their tenant-less session.
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
    headers = {**platform_admin.headers, "X-Tenant": tenant.slug}
    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["tenant_id"] is None
    assert (await client.get(TENANTS, headers=headers)).status_code == 200


async def test_platform_admin_phone_is_never_auto_registered_in_a_tenant(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        admin = await create_user(conn, None, "platform_admin")
        tenant = await create_tenant(conn)

    requested = await request_otp(client, admin.phone, tenant.slug)
    assert requested.status_code == 200
    verified = await verify_otp(
        client, requested.json()["challenge_id"], sms.codes[admin.phone], tenant.slug
    )
    assert verified.status_code == 403
    assert verified.json()["error"]["code"] == "platform_account"
    async with owner_engine.connect() as conn:
        count = (
            await conn.execute(
                text("SELECT count(*) FROM users WHERE phone = :p AND tenant_id = :t"),
                {"p": admin.phone, "t": tenant.id},
            )
        ).scalar_one()
    assert count == 0


async def test_platform_admin_can_still_hold_a_real_tenant_account(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    # The rule only blocks auto-registration; an account an admin created
    # deliberately in the tenant works as normal.
    async with owner_engine.begin() as conn:
        admin = await create_user(conn, None, "platform_admin")
        tenant = await create_tenant(conn)
        await create_user(conn, tenant.id, "operator", phone=admin.phone)
    session = await login(client, sms, admin.phone, tenant.slug)
    assert session.user["tenant_id"] == str(tenant.id)
    assert [r["role"] for r in session.user["roles"]] == ["operator"]
