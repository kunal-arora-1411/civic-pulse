"""Per-tenant status transitions: defaults for new tenants and the
read-only admin listing."""

from __future__ import annotations

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.tenancy import system_session
from app.domains.workflow.service import DEFAULT_TRANSITIONS, install_default_transitions
from tests.factories import create_user, unique_slug
from tests.helpers import RecordingSms, login
from tests.phase1 import make_city

TRANSITIONS = "/api/v1/admin/workflow/transitions"


async def test_platform_tenant_creation_installs_the_default_workflow(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        platform = await create_user(conn, None, "platform_admin")
    session = await login(client, sms, platform.phone, None)
    slug = unique_slug("wf")
    created = await client.post(
        "/api/v1/platform/tenants", headers=session.headers, json={"slug": slug, "name": "WF"}
    )
    assert created.status_code == 201, created.text

    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT from_status, to_status, allowed_roles, requires_reason, system_only "
                    "FROM status_transitions WHERE tenant_id = :t"
                ),
                {"t": created.json()["id"]},
            )
        ).all()
    assert len(rows) == len(DEFAULT_TRANSITIONS)
    by_pair = {(r[0], r[1]): r for r in rows}
    assert by_pair[("reported", "rejected")][3] is True
    assert by_pair[("rejected", "under_review")][2] == ["supervisor", "municipal_admin"]
    assert by_pair[("verified", "assigned")][4] is True
    assert by_pair[("verified", "assigned")][2] == []


async def test_installing_defaults_again_keeps_tenant_changes(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    city = await make_city(client, sms, owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE status_transitions SET requires_reason = true "
                "WHERE tenant_id = :t AND from_status = 'reported' AND to_status = 'verified'"
            ),
            {"t": city.tenant.id},
        )
    async with system_session(reason="test") as db:
        assert await install_default_transitions(db, city.tenant.id) == 0
    async with owner_engine.connect() as conn:
        kept = await conn.scalar(
            text(
                "SELECT requires_reason FROM status_transitions WHERE tenant_id = :t "
                "AND from_status = 'reported' AND to_status = 'verified'"
            ),
            {"t": city.tenant.id},
        )
    assert kept is True


async def test_admin_lists_transitions_in_lifecycle_order(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    city = await make_city(client, sms, owner_engine)
    await make_city(client, sms, owner_engine)  # another tenant's rows must not show

    response = await client.get(TRANSITIONS, headers=city.admin.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == len(DEFAULT_TRANSITIONS)
    pairs = [(t["from_status"], t["to_status"]) for t in body["items"]]
    assert pairs[:3] == [
        ("reported", "under_review"),
        ("reported", "verified"),
        ("reported", "rejected"),
    ]
    assert pairs[-1] == ("reopened", "assigned")
    first = body["items"][0]
    assert first["allowed_roles"] == ["operator", "supervisor", "municipal_admin"]
    assert set(first) == {
        "id",
        "from_status",
        "to_status",
        "allowed_roles",
        "requires_reason",
        "system_only",
    }

    # config:read is enough; citizens and anonymous callers are refused.
    assert (await client.get(TRANSITIONS, headers=city.operator.headers)).status_code == 200
    assert (await client.get(TRANSITIONS, headers=city.citizen.headers)).status_code == 403
    assert (await client.get(TRANSITIONS)).status_code == 401
