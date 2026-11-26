"""Citizen comments held for moderation, flags and the moderation queue
(FR-017, FR-086; docs/api/phase-3-contract.md §12)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

import app.models  # noqa: F401  (configure every mapper before using the service)
from app.domains.community.comments import DAILY_LIMIT
from tests.helpers import RecordingSms, Session
from tests.phase1 import City, login_new, make_city
from tests.phase2 import ISSUES, report

QUEUE = "/api/v1/moderation/comments"


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def _issue_id(client: httpx.AsyncClient, city: City) -> str:
    own = await report(client, city, city.citizen, category=city.waste, description="Garbage pile")
    return own["issue"]["id"]


async def _comment(
    client: httpx.AsyncClient, who: Session, issue_id: str, body: str = "Still there today"
) -> httpx.Response:
    return await client.post(
        f"{ISSUES}/{issue_id}/comments", headers=who.headers, json={"body": body}
    )


async def _list(client: httpx.AsyncClient, who: Session, issue_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"{ISSUES}/{issue_id}/comments", headers=who.headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def _decide(
    client: httpx.AsyncClient, who: Session, comment_id: str, **body: Any
) -> httpx.Response:
    return await client.post(f"{QUEUE}/{comment_id}", headers=who.headers, json=body)


async def _citizen(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, city: City, n: int
) -> Session:
    return await login_new(
        client, sms, owner_engine, city, "citizen", display_name=f"Neighbour {n}"
    )


async def test_a_comment_is_private_until_a_moderator_approves_it(
    client: httpx.AsyncClient, city: City, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    issue_id = await _issue_id(client, city)
    neighbour = await _citizen(client, sms, owner_engine, city, 1)
    created = await _comment(client, city.citizen, issue_id)
    assert created.status_code == 201, created.text
    comment = created.json()
    assert comment["state"] == "pending"
    assert comment["mine"] is True

    assert [c["id"] for c in await _list(client, city.citizen, issue_id)] == [comment["id"]]
    assert await _list(client, neighbour, issue_id) == []

    queue = await client.get(QUEUE, headers=city.operator.headers)
    assert queue.status_code == 200, queue.text
    (item,) = queue.json()["items"]
    assert item["id"] == comment["id"]
    assert item["author_name"] == "Asha Citizen"
    assert item["issue"]["id"] == issue_id

    approved = await _decide(client, city.operator, comment["id"], decision="approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "approved"

    (seen,) = await _list(client, neighbour, issue_id)
    assert seen["body"] == "Still there today"
    # Citizens never learn who wrote someone else's comment.
    assert seen["author_name"] is None
    assert seen["mine"] is False
    assert (await client.get(QUEUE, headers=city.operator.headers)).json()["items"] == []

    async with owner_engine.connect() as conn:
        n = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM audit_events "
                    "WHERE action = 'comment.approved' AND entity_id = :id"
                ),
                {"id": comment["id"]},
            )
        ).scalar_one()
    assert n == 1


async def test_rejecting_needs_a_reason_the_author_sees(
    client: httpx.AsyncClient, city: City, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    issue_id = await _issue_id(client, city)
    neighbour = await _citizen(client, sms, owner_engine, city, 1)
    comment = (await _comment(client, city.citizen, issue_id, "Call this number")).json()

    refused = await _decide(client, city.operator, comment["id"], decision="reject")
    assert refused.status_code == 422

    rejected = await _decide(
        client, city.operator, comment["id"], decision="reject", reason="Personal details"
    )
    assert rejected.status_code == 200, rejected.text
    (mine,) = await _list(client, city.citizen, issue_id)
    assert (mine["state"], mine["moderation_reason"]) == ("rejected", "Personal details")
    assert await _list(client, neighbour, issue_id) == []


async def test_flags_send_an_approved_comment_back_for_moderation(
    client: httpx.AsyncClient, city: City, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    issue_id = await _issue_id(client, city)
    comment = (await _comment(client, city.citizen, issue_id)).json()
    await _decide(client, city.operator, comment["id"], decision="approve")
    flag = f"/api/v1/comments/{comment['id']}/flag"

    own = await client.post(flag, headers=city.citizen.headers)
    assert own.status_code == 422

    neighbours = [await _citizen(client, sms, owner_engine, city, n) for n in range(3)]
    first = await client.post(flag, headers=neighbours[0].headers)
    assert first.status_code == 200, first.text
    assert first.json()["flagged_by_me"] is True
    # Flagging twice counts once.
    await client.post(flag, headers=neighbours[0].headers)
    assert len(await _list(client, neighbours[1], issue_id)) == 1

    await client.post(flag, headers=neighbours[1].headers)
    await client.post(flag, headers=neighbours[2].headers)
    assert await _list(client, neighbours[1], issue_id) == []
    (item,) = (await client.get(QUEUE, headers=city.operator.headers)).json()["items"]
    assert (item["id"], item["flag_count"]) == (comment["id"], 3)


async def test_citizens_get_a_daily_comment_limit(client: httpx.AsyncClient, city: City) -> None:
    issue_id = await _issue_id(client, city)
    for n in range(DAILY_LIMIT):
        assert (await _comment(client, city.citizen, issue_id, f"Note {n}")).status_code == 201
    limited = await _comment(client, city.citizen, issue_id, "One more")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"


async def test_moderation_needs_issue_update(
    client: httpx.AsyncClient, city: City, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    issue_id = await _issue_id(client, city)
    comment = (await _comment(client, city.citizen, issue_id)).json()
    # The municipal admin reads issues but doesn't update them.
    assert (await client.get(QUEUE, headers=city.admin.headers)).status_code == 403
    refused = await _decide(client, city.admin, comment["id"], decision="approve")
    assert refused.status_code == 403
    # Citizens can't moderate, and staff can't post as citizens.
    assert (await client.get(QUEUE, headers=city.citizen.headers)).status_code == 403
    assert (await _comment(client, city.operator, issue_id)).status_code == 403


async def test_other_tenants_cannot_see_or_moderate_comments(
    client: httpx.AsyncClient, city: City, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    issue_id = await _issue_id(client, city)
    comment = (await _comment(client, city.citizen, issue_id)).json()
    other = await make_city(client, sms, owner_engine)
    assert (
        await client.get(f"{ISSUES}/{issue_id}/comments", headers=other.citizen.headers)
    ).status_code == 404
    assert (await _comment(client, other.citizen, issue_id)).status_code == 404
    assert (await client.get(QUEUE, headers=other.operator.headers)).json()["items"] == []
    refused = await _decide(client, other.operator, comment["id"], decision="approve")
    assert refused.status_code == 404


async def test_comment_tables_have_forced_rls(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('issue_comments', 'comment_flags') ORDER BY relname"
                )
            )
        ).all()
    assert [tuple(r) for r in rows] == [
        ("comment_flags", True, True),
        ("issue_comments", True, True),
    ]
