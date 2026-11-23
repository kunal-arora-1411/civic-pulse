"""The audit trail: what gets written, who can read it, and that it can't be
changed."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import get_session_factory
from app.core.tenancy import set_tenant
from tests.factories import TenantRow, create_tenant, create_user, unique_phone
from tests.helpers import RecordingSms, Session, login

AUDIT = "/api/v1/admin/audit-events"


@pytest.fixture
async def tenant(owner_engine: AsyncEngine) -> TenantRow:
    async with owner_engine.begin() as conn:
        return await create_tenant(conn)


@pytest.fixture
async def admin(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, tenant: TenantRow
) -> Session:
    async with owner_engine.begin() as conn:
        user = await create_user(conn, tenant.id, "municipal_admin", display_name="Admin Asha")
    return await login(client, sms, user.phone, tenant.slug)


async def test_login_and_registration_are_audited(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, admin: Session
) -> None:
    citizen = await login(client, sms, unique_phone(), tenant.slug)
    response = await client.get(
        AUDIT,
        headers=admin.headers,
        params={"entity_id": citizen.user["id"], "sort": "occurred_at"},
    )
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 2
    assert [e["action"] for e in page["items"]] == ["user.registered", "auth.login"]
    registered = page["items"][0]
    assert registered["entity_type"] == "user"
    assert registered["actor"]["id"] == citizen.user["id"]
    assert registered["after"] == {"roles": ["citizen"], "via": "otp"}
    assert registered["request_id"]


async def test_audit_list_by_action_and_actor(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow, admin: Session
) -> None:
    response = await client.get(
        AUDIT, headers=admin.headers, params={"action": "auth.login", "actor_id": admin.user["id"]}
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["actor"] == {"id": admin.user["id"], "display_name": "Admin Asha"}


async def test_list_validation(client: httpx.AsyncClient, admin: Session) -> None:
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"sort": "-action"}):
        response = await client.get(AUDIT, headers=admin.headers, params=params)
        assert response.status_code == 422, params
        assert response.json()["error"]["code"] == "validation_error"


async def test_citizens_cannot_read_the_audit_trail(
    client: httpx.AsyncClient, sms: RecordingSms, tenant: TenantRow
) -> None:
    citizen = await login(client, sms, unique_phone(), tenant.slug)
    response = await client.get(AUDIT, headers=citizen.headers)
    assert response.status_code == 403
    assert set(response.json()) == {"error"}
    assert (await client.get(AUDIT)).status_code == 401


async def test_admins_only_see_their_own_tenant(
    client: httpx.AsyncClient,
    sms: RecordingSms,
    owner_engine: AsyncEngine,
    tenant: TenantRow,
    admin: Session,
) -> None:
    async with owner_engine.begin() as conn:
        other = await create_tenant(conn)
    outsider = await login(client, sms, unique_phone(), other.slug)
    response = await client.get(
        AUDIT, headers=admin.headers, params={"entity_id": outsider.user["id"]}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_platform_events_have_no_tenant(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        platform_admin = await create_user(conn, None, "platform_admin")
    await login(client, sms, platform_admin.phone, None)
    async with owner_engine.connect() as conn:
        tenant_ids = (
            (
                await conn.execute(
                    text("SELECT tenant_id FROM audit_events WHERE actor_id = :id"),
                    {"id": platform_admin.id},
                )
            )
            .scalars()
            .all()
        )
    assert tenant_ids == [None]


async def test_app_role_cannot_modify_audit_events(admin: Session, tenant: TenantRow) -> None:
    async with get_session_factory()() as session:
        await set_tenant(session, tenant.id)
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(
                text("UPDATE audit_events SET action = 'tampered' WHERE tenant_id = :t"),
                {"t": tenant.id},
            )
    async with get_session_factory()() as session:
        await set_tenant(session, tenant.id)
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(
                text("DELETE FROM audit_events WHERE tenant_id = :t"), {"t": tenant.id}
            )
