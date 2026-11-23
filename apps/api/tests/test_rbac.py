from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import get_session_factory
from app.core.tenancy import set_tenant
from app.domains.org.models import Jurisdiction
from app.domains.rbac.permissions import (
    PUBLIC_PERMISSIONS,
    ROLE_PERMISSIONS,
    Permission,
    is_staff_permission,
)
from app.domains.rbac.principal import Principal, RoleGrant
from app.domains.rbac.roles import STAFF_ROLES, Role
from app.domains.rbac.scope import (
    accessible_department_ids,
    accessible_jurisdiction_ids,
    jurisdiction_subtree,
    scope_filter,
)
from tests.factories import create_jurisdiction, create_tenant

P = Permission


def _principal(*grants: RoleGrant, tenant_id: uuid.UUID | None = None) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        session_id=uuid.uuid4(),
        grants=grants,
    )


def test_every_role_has_a_permission_set() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)


def test_citizens_hold_no_staff_permissions() -> None:
    for role in (Role.CITIZEN, Role.COMMUNITY_CONTRIBUTOR):
        assert not any(is_staff_permission(p) for p in ROLE_PERMISSIONS[role])
    assert P.USER_MANAGE not in PUBLIC_PERMISSIONS


def test_staff_roles_hold_only_staff_permissions() -> None:
    for role in STAFF_ROLES:
        assert all(is_staff_permission(p) for p in ROLE_PERMISSIONS[role]), role


def test_platform_admin_has_no_tenant_data_permissions() -> None:
    assert ROLE_PERMISSIONS[Role.PLATFORM_ADMIN] == {P.TENANT_MANAGE}


def test_principal_permissions_are_the_union_of_roles() -> None:
    principal = _principal(RoleGrant(Role.OPERATOR), RoleGrant(Role.FIELD_WORKER))
    assert principal.has(P.ISSUE_TRIAGE, P.EVIDENCE_UPLOAD)
    assert not principal.has(P.USER_MANAGE)
    assert principal.is_staff
    assert not _principal(RoleGrant(Role.CITIZEN)).is_staff


def test_department_scope() -> None:
    roads, drains = uuid.uuid4(), uuid.uuid4()
    scoped = _principal(RoleGrant(Role.SUPERVISOR, department_id=roads))
    assert accessible_department_ids(scoped, P.ISSUE_ASSIGN) == {roads}

    mixed = _principal(
        RoleGrant(Role.SUPERVISOR, department_id=roads),
        RoleGrant(Role.SUPERVISOR, department_id=drains),
    )
    assert accessible_department_ids(mixed, P.ISSUE_ASSIGN) == {roads, drains}

    unscoped = _principal(RoleGrant(Role.MUNICIPAL_ADMIN))
    assert accessible_department_ids(unscoped, P.ISSUE_READ) is None
    assert accessible_department_ids(unscoped, P.ISSUE_ASSIGN) == set()


def test_scope_filter_shapes() -> None:
    column = Jurisdiction.__table__.c.id
    assert str(scope_filter(column, None)) == "true"
    assert str(scope_filter(column, set())) == "false"
    assert "IN" in str(scope_filter(column, {uuid.uuid4()}))


@pytest.fixture
async def tree(owner_engine: AsyncEngine) -> dict[str, uuid.UUID]:
    """city -> zone_n -> (ward_1, ward_2); city -> zone_s -> ward_3, plus a
    ward in another tenant."""
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        other = await create_tenant(conn)
        ids: dict[str, uuid.UUID] = {"tenant": tenant.id}
        ids["city"] = await create_jurisdiction(conn, tenant.id, kind="city", code="CITY")
        ids["zone_n"] = await create_jurisdiction(
            conn, tenant.id, kind="zone", code="ZN", parent_id=ids["city"]
        )
        ids["zone_s"] = await create_jurisdiction(
            conn, tenant.id, kind="zone", code="ZS", parent_id=ids["city"]
        )
        for name, parent in (("ward_1", "zone_n"), ("ward_2", "zone_n"), ("ward_3", "zone_s")):
            ids[name] = await create_jurisdiction(
                conn, tenant.id, kind="ward", code=name.upper(), parent_id=ids[parent]
            )
        ids["foreign_ward"] = await create_jurisdiction(conn, other.id, kind="ward", code="W9")
    return ids


async def test_jurisdiction_subtree_expands_descendants(tree: dict[str, uuid.UUID]) -> None:
    async with get_session_factory()() as session:
        await set_tenant(session, tree["tenant"])
        assert await jurisdiction_subtree(session, [tree["zone_n"]]) == {
            tree["zone_n"],
            tree["ward_1"],
            tree["ward_2"],
        }
        everything = await jurisdiction_subtree(session, [tree["city"]])
        assert len(everything) == 6
        assert await jurisdiction_subtree(session, []) == set()


async def test_jurisdiction_subtree_never_crosses_tenants(tree: dict[str, uuid.UUID]) -> None:
    async with get_session_factory()() as session:
        await set_tenant(session, tree["tenant"])
        assert await jurisdiction_subtree(session, [tree["foreign_ward"]]) == set()


async def test_accessible_jurisdictions_for_scoped_and_unscoped_roles(
    tree: dict[str, uuid.UUID],
) -> None:
    async with get_session_factory()() as session:
        await set_tenant(session, tree["tenant"])

        zone_operator = _principal(RoleGrant(Role.OPERATOR, jurisdiction_id=tree["zone_s"]))
        assert await accessible_jurisdiction_ids(session, zone_operator, P.ISSUE_READ) == {
            tree["zone_s"],
            tree["ward_3"],
        }

        tenant_wide = _principal(RoleGrant(Role.OPERATOR))
        assert await accessible_jurisdiction_ids(session, tenant_wide, P.ISSUE_READ) is None

        citizen = _principal(RoleGrant(Role.CITIZEN))
        assert await accessible_jurisdiction_ids(session, citizen, P.ISSUE_READ) == set()

        # The scope helper composes with ordinary queries.
        scope = await accessible_jurisdiction_ids(session, zone_operator, P.ISSUE_READ)
        rows = await session.execute(
            select(Jurisdiction.code).where(scope_filter(Jurisdiction.id, scope))
        )
        assert sorted(rows.scalars()) == ["WARD_3", "ZS"]
