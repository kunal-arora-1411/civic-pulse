"""Municipal administration: users, roles, departments and jurisdictions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import (
    TenantRow,
    create_department,
    create_jurisdiction,
    create_tenant,
    create_user,
    unique_phone,
)
from tests.helpers import RecordingSms, Session, login

USERS = "/api/v1/admin/users"
WARD_1 = "POLYGON((77.58 12.96, 77.59 12.96, 77.59 12.97, 77.58 12.97, 77.58 12.96))"
WARD_2 = "POLYGON((77.59 12.96, 77.60 12.96, 77.60 12.97, 77.59 12.97, 77.59 12.96))"


@dataclass
class Org:
    tenant: TenantRow
    admin: Session
    roads: uuid.UUID
    zone: uuid.UUID
    ward_1: uuid.UUID
    ward_2: uuid.UUID


@pytest.fixture
async def org(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> Org:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        roads = await create_department(conn, tenant.id, code="ROADS", name="Roads")
        await create_department(conn, tenant.id, code="SWM", name="Solid Waste")
        zone = await create_jurisdiction(conn, tenant.id, kind="zone", code="Z1", name="Zone 1")
        ward_1 = await create_jurisdiction(
            conn, tenant.id, kind="ward", code="W1", name="Ward 1", parent_id=zone, wkt=WARD_1
        )
        ward_2 = await create_jurisdiction(
            conn, tenant.id, kind="ward", code="W2", name="Ward 2", parent_id=zone, wkt=WARD_2
        )
        admin = await create_user(conn, tenant.id, "municipal_admin", display_name="Admin")
    session = await login(client, sms, admin.phone, tenant.slug)
    return Org(tenant, session, roads, zone, ward_1, ward_2)


async def _create(client: httpx.AsyncClient, org: Org, **overrides: object) -> httpx.Response:
    body = {
        "phone": unique_phone(),
        "display_name": "Ravi Operator",
        "roles": [{"role": "operator"}],
        **overrides,
    }
    return await client.post(USERS, headers=org.admin.headers, json=body)


# --- users -------------------------------------------------------------------------------


async def test_create_and_fetch_a_staff_user(client: httpx.AsyncClient, org: Org) -> None:
    phone = unique_phone()
    response = await _create(
        client,
        org,
        phone=phone.removeprefix("+91"),
        email="ravi@example.com",
        roles=[
            {"role": "supervisor", "department_id": str(org.roads)},
            {"role": "operator", "jurisdiction_id": str(org.zone)},
        ],
    )
    assert response.status_code == 201, response.text
    user = response.json()
    assert user["phone"] == phone
    assert user["tenant_id"] == str(org.tenant.id)
    assert user["is_staff"] is True
    assert user["is_active"] is True
    assert {r["role"] for r in user["roles"]} == {"supervisor", "operator"}

    fetched = await client.get(f"{USERS}/{user['id']}", headers=org.admin.headers)
    assert fetched.status_code == 200
    assert fetched.json() == user


async def test_created_staff_can_log_in_with_their_permissions(
    client: httpx.AsyncClient, sms: RecordingSms, org: Org
) -> None:
    phone = unique_phone()
    await _create(client, org, phone=phone, roles=[{"role": "operator"}])
    session = await login(client, sms, phone, org.tenant.slug)
    assert "issue:triage" in session.user["permissions"]
    assert "user:manage" not in session.user["permissions"]


async def test_duplicate_phone_is_a_conflict(client: httpx.AsyncClient, org: Org) -> None:
    phone = unique_phone()
    assert (await _create(client, org, phone=phone)).status_code == 201
    again = await _create(client, org, phone=phone)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    ("roles", "expected_loc"),
    [
        ([{"role": "platform_admin"}], ["body", "roles", 0, "role"]),
        ([{"role": "citizen", "department_id": "ROADS"}], ["body", "roles", 0]),
        ([{"role": "operator", "department_id": str(uuid.uuid4())}], None),
        ([{"role": "operator", "jurisdiction_id": str(uuid.uuid4())}], None),
        ([], None),
        ([{"role": "mayor"}], None),
    ],
)
async def test_invalid_role_assignments(
    client: httpx.AsyncClient, org: Org, roles: list[dict], expected_loc: list | None
) -> None:
    if roles and roles[0].get("department_id") == "ROADS":
        roles = [{**roles[0], "department_id": str(org.roads)}]
    response = await _create(client, org, roles=roles)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    if expected_loc is not None:
        assert response.json()["error"]["details"]["errors"][0]["loc"] == expected_loc


async def test_list_filters_search_and_sort(client: httpx.AsyncClient, org: Org) -> None:
    await _create(client, org, display_name="Zara Field", roles=[{"role": "field_worker"}])
    await _create(client, org, display_name="Arun Supervisor", roles=[{"role": "supervisor"}])

    everyone = await client.get(USERS, headers=org.admin.headers, params={"sort": "display_name"})
    assert everyone.status_code == 200
    names = [u["display_name"] for u in everyone.json()["items"]]
    assert names == sorted(names)
    assert everyone.json()["total"] == 3  # the admin plus the two above

    field = await client.get(USERS, headers=org.admin.headers, params={"role": "field_worker"})
    assert [u["display_name"] for u in field.json()["items"]] == ["Zara Field"]

    search = await client.get(USERS, headers=org.admin.headers, params={"q": "arun"})
    assert [u["display_name"] for u in search.json()["items"]] == ["Arun Supervisor"]

    # LIKE wildcards in the search term are matched literally.
    wildcard = await client.get(USERS, headers=org.admin.headers, params={"q": "%"})
    assert wildcard.json()["total"] == 0

    paged = await client.get(USERS, headers=org.admin.headers, params={"limit": 1, "offset": 1})
    assert paged.json()["limit"] == 1
    assert paged.json()["offset"] == 1
    assert len(paged.json()["items"]) == 1


async def test_replacing_roles_is_audited(
    client: httpx.AsyncClient, org: Org, owner_engine: AsyncEngine
) -> None:
    user = (await _create(client, org, roles=[{"role": "operator"}])).json()
    response = await client.put(
        f"{USERS}/{user['id']}/roles",
        headers=org.admin.headers,
        json={"roles": [{"role": "supervisor", "department_id": str(org.roads)}]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == [
        {"role": "supervisor", "department_id": str(org.roads), "jurisdiction_id": None}
    ]

    events = await client.get(
        "/api/v1/admin/audit-events",
        headers=org.admin.headers,
        params={"entity_id": user["id"], "action": "user.roles_changed"},
    )
    assert events.json()["total"] == 1
    event = events.json()["items"][0]
    assert event["actor"]["id"] == org.admin.user["id"]
    assert event["before"] == {
        "roles": [{"role": "operator", "department_id": None, "jurisdiction_id": None}]
    }
    assert event["after"] == {
        "roles": [{"role": "supervisor", "department_id": str(org.roads), "jurisdiction_id": None}]
    }

    async with owner_engine.connect() as conn:
        granted_by = (
            await conn.execute(
                text("SELECT granted_by FROM user_roles WHERE user_id = :id"), {"id": user["id"]}
            )
        ).scalar_one()
    assert str(granted_by) == org.admin.user["id"]


async def test_role_change_applies_to_live_sessions(
    client: httpx.AsyncClient, sms: RecordingSms, org: Org
) -> None:
    phone = unique_phone()
    user = (await _create(client, org, phone=phone, roles=[{"role": "operator"}])).json()
    session = await login(client, sms, phone, org.tenant.slug)
    assert (
        await client.get("/api/v1/admin/departments", headers=session.headers)
    ).status_code == 200
    await client.put(
        f"{USERS}/{user['id']}/roles",
        headers=org.admin.headers,
        json={"roles": [{"role": "citizen"}]},
    )
    # Same access token, but the role is gone.
    assert (
        await client.get("/api/v1/admin/departments", headers=session.headers)
    ).status_code == 403


async def test_unchanged_roles_write_no_audit_event(client: httpx.AsyncClient, org: Org) -> None:
    user = (await _create(client, org, roles=[{"role": "operator"}])).json()
    await client.put(
        f"{USERS}/{user['id']}/roles",
        headers=org.admin.headers,
        json={"roles": [{"role": "operator"}]},
    )
    events = await client.get(
        "/api/v1/admin/audit-events",
        headers=org.admin.headers,
        params={"entity_id": user["id"], "action": "user.roles_changed"},
    )
    assert events.json()["total"] == 0


async def test_admins_cannot_lock_themselves_out(client: httpx.AsyncClient, org: Org) -> None:
    me = org.admin.user["id"]
    demote = await client.put(
        f"{USERS}/{me}/roles", headers=org.admin.headers, json={"roles": [{"role": "operator"}]}
    )
    assert demote.status_code == 409
    deactivate = await client.patch(
        f"{USERS}/{me}", headers=org.admin.headers, json={"is_active": False}
    )
    assert deactivate.status_code == 409


async def test_update_and_deactivate_a_user(
    client: httpx.AsyncClient, sms: RecordingSms, org: Org
) -> None:
    phone = unique_phone()
    user = (await _create(client, org, phone=phone)).json()
    session = await login(client, sms, phone, org.tenant.slug)

    renamed = await client.patch(
        f"{USERS}/{user['id']}", headers=org.admin.headers, json={"display_name": "Ravi K"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "Ravi K"

    deactivated = await client.patch(
        f"{USERS}/{user['id']}", headers=org.admin.headers, json={"is_active": False}
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    # Their existing session ends immediately...
    assert (await client.get("/api/v1/users/me", headers=session.headers)).status_code == 401

    events = await client.get(
        "/api/v1/admin/audit-events",
        headers=org.admin.headers,
        params={"entity_id": user["id"], "sort": "occurred_at"},
    )
    actions = [e["action"] for e in events.json()["items"]]
    assert actions[0] == "user.created"
    assert actions[-2:] == ["user.updated", "auth.sessions_revoked"]
    update = events.json()["items"][-2]
    assert update["before"]["is_active"] is True
    assert update["after"]["is_active"] is False


async def test_unknown_user_is_404(client: httpx.AsyncClient, org: Org) -> None:
    response = await client.get(f"{USERS}/{uuid.uuid4()}", headers=org.admin.headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    malformed = await client.get(f"{USERS}/not-a-uuid", headers=org.admin.headers)
    assert malformed.status_code == 422


# --- departments and jurisdictions -------------------------------------------------------


async def test_departments(client: httpx.AsyncClient, org: Org) -> None:
    listed = await client.get("/api/v1/admin/departments", headers=org.admin.headers)
    assert listed.status_code == 200
    assert [d["code"] for d in listed.json()["items"]] == ["ROADS", "SWM"]

    created = await client.post(
        "/api/v1/admin/departments",
        headers=org.admin.headers,
        json={"name": "Street Lighting", "code": "street_lighting"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["code"] == "STREET_LIGHTING"

    duplicate = await client.post(
        "/api/v1/admin/departments",
        headers=org.admin.headers,
        json={"name": "Lights again", "code": "STREET_LIGHTING"},
    )
    assert duplicate.status_code == 409

    bad = await client.post(
        "/api/v1/admin/departments", headers=org.admin.headers, json={"name": "X", "code": "1!"}
    )
    assert bad.status_code == 422

    events = await client.get(
        "/api/v1/admin/audit-events",
        headers=org.admin.headers,
        params={"action": "department.created"},
    )
    assert events.json()["items"][0]["after"]["code"] == "STREET_LIGHTING"


async def test_jurisdictions(client: httpx.AsyncClient, org: Org) -> None:
    wards = await client.get(
        "/api/v1/admin/jurisdictions", headers=org.admin.headers, params={"kind": "ward"}
    )
    assert wards.status_code == 200
    items = wards.json()["items"]
    assert [j["code"] for j in items] == ["W1", "W2"]
    assert items[0] == {
        "id": str(org.ward_1),
        "parent_id": str(org.zone),
        "kind": "ward",
        "name": "Ward 1",
        "code": "W1",
        "geometry": None,
    }

    with_geometry = await client.get(
        "/api/v1/admin/jurisdictions",
        headers=org.admin.headers,
        params={"kind": "ward", "include_geometry": "true"},
    )
    geometry = with_geometry.json()["items"][0]["geometry"]
    assert geometry["type"] == "MultiPolygon"
    assert geometry["coordinates"][0][0][0] == [77.58, 12.96]

    children = await client.get(
        "/api/v1/admin/jurisdictions",
        headers=org.admin.headers,
        params={"parent_id": str(org.zone)},
    )
    assert children.json()["total"] == 2
