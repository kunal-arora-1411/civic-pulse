"""In-app notifications: created by triggers on real events, read and
acknowledged only by their owner, isolated per tenant."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import RecordingSms, Session
from tests.phase1 import NE, City, login_new, make_city
from tests.phase2 import ISSUES, issue, north_of, report, scene_photo
from tests.phase3 import Ops, assign, make_ops, verified_issue

NOTIFICATIONS = "/api/v1/notifications"


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def _list(client: httpx.AsyncClient, who: Session, **query: Any) -> dict[str, Any]:
    response = await client.get(NOTIFICATIONS, headers=who.headers, params=query)
    assert response.status_code == 200, response.text
    return response.json()


async def _unread(client: httpx.AsyncClient, who: Session) -> int:
    response = await client.get(f"{NOTIFICATIONS}/unread-count", headers=who.headers)
    assert response.status_code == 200, response.text
    return response.json()["unread"]


async def test_reporter_hears_about_their_new_issue_and_status_moves(
    client: httpx.AsyncClient, city: City
) -> None:
    own = await report(client, city, city.citizen, category=city.waste)
    page = await _list(client, city.citizen)
    (first,) = page["items"]
    assert first["kind"] == "report_new_issue"
    assert first["title_key"] == "report_new_issue.title"
    assert first["params"] == {"issue": own["issue"]["reference"], "report": own["reference"]}
    assert first["link"] == f"/reports/{own['id']}"
    assert first["read_at"] is None

    detail = await issue(client, city.operator, own["issue"]["id"])
    moved = await client.patch(
        f"{ISSUES}/{detail['id']}/status",
        headers=city.operator.headers,
        json={"to_status": "verified", "version": detail["version"]},
    )
    assert moved.status_code == 200, moved.text

    page = await _list(client, city.citizen)
    assert [n["kind"] for n in page["items"]] == ["issue_status", "report_new_issue"]
    assert page["items"][0]["params"]["status"] == "verified"
    assert page["unread"] == 2
    # Staff who made the move are not told about their own move.
    assert await _unread(client, city.operator) == 0


async def test_mark_one_and_all_read(client: httpx.AsyncClient, city: City) -> None:
    await report(client, city, city.citizen, category=city.waste)
    await report(client, city, city.citizen, point=north_of(NE, 900), category=city.waste)
    assert await _unread(client, city.citizen) == 2
    target = (await _list(client, city.citizen))["items"][0]

    response = await client.post(
        f"{NOTIFICATIONS}/{target['id']}/read", headers=city.citizen.headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["read_at"] is not None
    again = await client.post(f"{NOTIFICATIONS}/{target['id']}/read", headers=city.citizen.headers)
    assert again.json()["read_at"] == response.json()["read_at"]
    assert await _unread(client, city.citizen) == 1
    unread_only = await _list(client, city.citizen, unread="true")
    assert unread_only["total"] == 1
    assert unread_only["items"][0]["id"] != target["id"]

    done = await client.post(f"{NOTIFICATIONS}/read-all", headers=city.citizen.headers)
    assert done.json() == {"updated": 1}
    assert await _unread(client, city.citizen) == 0


async def test_nobody_else_reads_or_marks_my_notifications(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, city: City
) -> None:
    await report(client, city, city.citizen, category=city.waste)
    mine = (await _list(client, city.citizen))["items"][0]
    neighbour = await login_new(client, sms, owner_engine, city, "citizen")

    assert (await _list(client, neighbour))["total"] == 0
    for who in (neighbour, city.admin):
        response = await client.post(f"{NOTIFICATIONS}/{mine['id']}/read", headers=who.headers)
        assert response.status_code == 404
    assert (await client.get(NOTIFICATIONS)).status_code == 401
    assert (await client.post(f"{NOTIFICATIONS}/read-all")).status_code == 401
    assert await _unread(client, city.citizen) == 1


async def test_other_tenants_never_see_notifications(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, city: City
) -> None:
    await report(client, city, city.citizen, category=city.waste)
    mine = (await _list(client, city.citizen))["items"][0]
    other = await make_city(client, sms, owner_engine)

    assert (await _list(client, other.citizen))["total"] == 0
    response = await client.post(f"{NOTIFICATIONS}/{mine['id']}/read", headers=other.admin.headers)
    assert response.status_code == 404
    # Even with the row's owner id, the app role cannot see across tenants.
    async with owner_engine.connect() as conn:
        n = (
            await conn.execute(
                text("SELECT count(*) FROM notifications WHERE tenant_id = :t"),
                {"t": city.tenant.id},
            )
        ).scalar_one()
    assert n == 1


async def test_operators_hear_about_review_tasks(client: httpx.AsyncClient, city: City) -> None:
    await report(client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 6)])
    unsure = await report(
        client,
        city,
        city.citizen,
        point=north_of(NE, 20),
        media_ids=[await scene_photo(client, city.citizen, 6, variant=1)],
    )
    assert unsure["matching_status"] == "review"
    (note,) = (await _list(client, city.operator))["items"]
    assert note["kind"] == "review_task"
    assert note["params"] == {"report": unsure["reference"]}
    assert note["link"] == "/admin/review"


@pytest.fixture
async def ops(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> Ops:
    return await make_ops(client, sms, owner_engine)


async def test_assignee_hears_about_assignment(client: httpx.AsyncClient, ops: Ops) -> None:
    detail = await verified_issue(client, ops)
    assert (await assign(client, ops, detail, ops.worker)).status_code == 201
    (note,) = (await _list(client, ops.worker))["items"]
    assert note["kind"] == "assignment"
    assert note["params"] == {"issue": detail["reference"]}
    assert await _unread(client, ops.worker2) == 0
    # The reporter hears that their issue was assigned.
    kinds = [n["kind"] for n in (await _list(client, ops.city.citizen))["items"]]
    assert kinds.count("issue_status") == 2


async def test_notifications_table_has_forced_rls(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'notifications'"
                )
            )
        ).one()
    assert row == (True, True)
