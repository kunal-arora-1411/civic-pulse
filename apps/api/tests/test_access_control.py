"""AC-13 (unauthorised access is denied without disclosing data) and AC-14
(tenant isolation) at the API boundary. The database half of AC-14 lives in
test_tenancy.py."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import TenantRow, UserRow, create_department, create_tenant, create_user
from tests.helpers import RecordingSms, Session, login

ADMIN_ENDPOINTS = [
    ("GET", "/api/v1/admin/users", None),
    (
        "POST",
        "/api/v1/admin/users",
        {"phone": "+919812345678", "display_name": "X", "roles": [{"role": "operator"}]},
    ),
    ("GET", "/api/v1/admin/users/{user_id}", None),
    ("PATCH", "/api/v1/admin/users/{user_id}", {"display_name": "Hacked"}),
    ("PUT", "/api/v1/admin/users/{user_id}/roles", {"roles": [{"role": "municipal_admin"}]}),
    ("GET", "/api/v1/admin/departments", None),
    ("POST", "/api/v1/admin/departments", {"name": "Evil", "code": "EVIL"}),
    ("GET", "/api/v1/admin/jurisdictions", None),
    ("GET", "/api/v1/admin/audit-events", None),
    ("GET", "/api/v1/platform/tenants", None),
    ("POST", "/api/v1/platform/tenants", {"slug": "evil-city", "name": "Evil"}),
]


@dataclass
class World:
    a: TenantRow
    b: TenantRow
    admin_a: Session
    admin_b: Session
    citizen_a: Session
    victim_b: UserRow
    department_b: uuid.UUID


@pytest.fixture
async def world(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> World:
    async with owner_engine.begin() as conn:
        a = await create_tenant(conn, name="City A")
        b = await create_tenant(conn, name="City B")
        admin_a = await create_user(conn, a.id, "municipal_admin")
        admin_b = await create_user(conn, b.id, "municipal_admin")
        citizen_a = await create_user(conn, a.id, "citizen")
        victim_b = await create_user(conn, b.id, "operator", display_name="Bea Secret")
        department_b = await create_department(conn, b.id, code="ROADS")
    return World(
        a=a,
        b=b,
        admin_a=await login(client, sms, admin_a.phone, a.slug),
        admin_b=await login(client, sms, admin_b.phone, b.slug),
        citizen_a=await login(client, sms, citizen_a.phone, a.slug),
        victim_b=victim_b,
        department_b=department_b,
    )


def _assert_error_only(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, (response.request.url, response.text)
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["details"] == {}


# --- AC-13 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ENDPOINTS)
async def test_unauthenticated_requests_get_401(
    client: httpx.AsyncClient, world: World, method: str, path: str, body: dict | None
) -> None:
    url = path.format(user_id=world.victim_b.id)
    response = await client.request(method, url, json=body)
    _assert_error_only(response, 401, "unauthenticated")


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ENDPOINTS)
async def test_citizens_get_403_and_no_data(
    client: httpx.AsyncClient, world: World, method: str, path: str, body: dict | None
) -> None:
    url = path.format(user_id=world.admin_a.user["id"])
    response = await client.request(method, url, json=body, headers=world.citizen_a.headers)
    _assert_error_only(response, 403, "forbidden")
    assert world.admin_a.user["phone"] not in response.text


async def test_denied_writes_change_nothing(
    client: httpx.AsyncClient, world: World, owner_engine: AsyncEngine
) -> None:
    await client.put(
        f"/api/v1/admin/users/{world.citizen_a.user['id']}/roles",
        headers=world.citizen_a.headers,
        json={"roles": [{"role": "municipal_admin"}]},
    )
    me = await client.get("/api/v1/users/me", headers=world.citizen_a.headers)
    assert [r["role"] for r in me.json()["roles"]] == ["citizen"]


async def test_staff_only_get_what_their_role_allows(
    client: httpx.AsyncClient, sms: RecordingSms, world: World, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        operator = await create_user(conn, world.a.id, "operator")
        field_worker = await create_user(conn, world.a.id, "field_worker")
    operator_session = await login(client, sms, operator.phone, world.a.slug)
    field_session = await login(client, sms, field_worker.phone, world.a.slug)

    # Operators can read configuration but not manage users, config or audit.
    ok = await client.get("/api/v1/admin/departments", headers=operator_session.headers)
    assert ok.status_code == 200
    for method, path in (
        ("GET", "/api/v1/admin/users"),
        ("POST", "/api/v1/admin/departments"),
        ("GET", "/api/v1/admin/audit-events"),
    ):
        response = await client.request(
            method, path, headers=operator_session.headers, json={"name": "X", "code": "XX"}
        )
        _assert_error_only(response, 403, "forbidden")

    # Field workers don't even read configuration.
    response = await client.get("/api/v1/admin/jurisdictions", headers=field_session.headers)
    _assert_error_only(response, 403, "forbidden")


# --- AC-14 -------------------------------------------------------------------------------


async def test_x_tenant_must_match_the_token(client: httpx.AsyncClient, world: World) -> None:
    headers = {**world.admin_a.headers, "X-Tenant": world.b.slug}
    response = await client.get("/api/v1/admin/users", headers=headers)
    _assert_error_only(response, 403, "tenant_mismatch")
    # The matching header is fine.
    same = await client.get(
        "/api/v1/admin/users", headers={**world.admin_a.headers, "X-Tenant": world.a.slug}
    )
    assert same.status_code == 200


async def test_admin_lists_only_their_tenant(client: httpx.AsyncClient, world: World) -> None:
    response = await client.get(
        "/api/v1/admin/users", headers=world.admin_a.headers, params={"limit": 100}
    )
    tenant_ids = {u["tenant_id"] for u in response.json()["items"]}
    assert tenant_ids == {str(world.a.id)}
    assert "Bea Secret" not in response.text

    departments = await client.get("/api/v1/admin/departments", headers=world.admin_a.headers)
    assert str(world.department_b) not in departments.text


async def test_other_tenants_users_look_nonexistent(
    client: httpx.AsyncClient, world: World
) -> None:
    victim = f"/api/v1/admin/users/{world.victim_b.id}"
    for method, body in (
        ("GET", None),
        ("PATCH", {"display_name": "Hijacked"}),
        ("PUT", {"roles": [{"role": "citizen"}]}),
    ):
        url = victim if method != "PUT" else f"{victim}/roles"
        response = await client.request(method, url, json=body, headers=world.admin_a.headers)
        # 404, not 403: the API doesn't even confirm the user exists.
        _assert_error_only(response, 404, "not_found")

    # Tenant B's admin still sees the user untouched.
    intact = await client.get(victim, headers=world.admin_b.headers)
    assert intact.json()["display_name"] == "Bea Secret"
    assert [r["role"] for r in intact.json()["roles"]] == ["operator"]


async def test_cannot_scope_roles_to_another_tenants_department(
    client: httpx.AsyncClient, world: World
) -> None:
    response = await client.put(
        f"/api/v1/admin/users/{world.citizen_a.user['id']}/roles",
        headers=world.admin_a.headers,
        json={"roles": [{"role": "supervisor", "department_id": str(world.department_b)}]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"][0]["msg"] == "Unknown department."


async def test_same_phone_is_a_different_account_in_each_tenant(
    client: httpx.AsyncClient, sms: RecordingSms, world: World, redis: object
) -> None:
    phone = world.victim_b.phone
    in_a = await login(client, sms, phone, world.a.slug)
    assert in_a.user["id"] != str(world.victim_b.id)
    assert in_a.user["tenant_id"] == str(world.a.id)
    assert [r["role"] for r in in_a.user["roles"]] == ["citizen"]
