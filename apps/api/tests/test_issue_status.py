"""PATCH /issues/{id}/status: the workflow table, optimistic locking, and
the timeline and audit rows every change leaves behind."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import Session
from tests.phase1 import NE, City, login_new, make_city


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def _report(client: httpx.AsyncClient, city: City) -> dict:
    response = await client.post(
        "/api/v1/reports",
        headers={**city.citizen.headers, "Idempotency-Key": uuid.uuid4().hex},
        json={
            "category_id": str(city.waste),
            "description": "Garbage dumped on the footpath",
            "location": {"lat": NE[1], "lng": NE[0], "source": "gps"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _move(
    client: httpx.AsyncClient, session: Session, issue_id: str, **body: Any
) -> httpx.Response:
    return await client.patch(
        f"/api/v1/issues/{issue_id}/status", headers=session.headers, json=body
    )


async def _audit(engine: AsyncEngine, issue_id: str) -> list[Any]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    text(
                        "SELECT actor_id, before, after FROM audit_events "
                        "WHERE action = 'issue.status_changed' AND entity_id = :id ORDER BY id"
                    ),
                    {"id": issue_id},
                )
            ).all()
        )


async def test_allowed_transition_updates_everything(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    report = await _report(client, city)
    issue_id = report["issue"]["id"]
    response = await _move(
        client,
        city.operator,
        issue_id,
        to_status="under_review",
        public_note="We are checking this.",
        version=1,
    )
    assert response.status_code == 200, response.text
    issue = response.json()
    assert issue["status"] == "under_review"
    assert issue["version"] == 2
    event = issue["timeline"][-1]
    assert event["type"] == "status_changed"
    assert (event["from_status"], event["to_status"]) == ("reported", "under_review")
    assert event["public_note"] == "We are checking this."
    assert event["reason"] is None
    assert event["actor"] == {"id": city.operator.user["id"], "display_name": "Omar Operator"}
    assert [t["to_status"] for t in issue["allowed_transitions"]] == ["verified", "rejected"]

    (row,) = await _audit(owner_engine, issue_id)
    assert str(row.actor_id) == city.operator.user["id"]
    assert row.before == {"status": "reported", "version": 1}
    assert row.after["status"] == "under_review"
    assert row.after["version"] == 2

    mine = await client.get(f"/api/v1/reports/{report['id']}", headers=city.citizen.headers)
    assert mine.json()["issue"]["status"] == "under_review"
    assert mine.json()["issue"]["timeline"][-1]["public_note"] == "We are checking this."


async def test_rejection_needs_a_reason_that_citizens_never_see(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    report = await _report(client, city)
    issue_id = report["issue"]["id"]
    for reason in (None, "   "):
        response = await _move(
            client, city.operator, issue_id, to_status="rejected", reason=reason, version=1
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "reason_required"
    assert await _audit(owner_engine, issue_id) == []

    rejected = await _move(
        client,
        city.operator,
        issue_id,
        to_status="rejected",
        reason="Private land; not a municipal responsibility",
        public_note="This location is private property.",
        version=1,
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["timeline"][-1]["reason"].startswith("Private land")

    mine = await client.get(f"/api/v1/reports/{report['id']}", headers=city.citizen.headers)
    assert "Private land" not in mine.text
    assert "private property" in mine.text

    # Reopening a rejection is for supervisors and admins, with a reason.
    by_operator = await _move(
        client, city.operator, issue_id, to_status="under_review", reason="x", version=2
    )
    assert by_operator.json()["error"]["code"] == "invalid_transition"
    by_supervisor = await _move(
        client,
        city.supervisor,
        issue_id,
        to_status="under_review",
        reason="Owner disputes",
        version=2,
    )
    assert by_supervisor.status_code == 200
    assert by_supervisor.json()["version"] == 3


@pytest.mark.parametrize("target", ["resolved", "closed", "reported", "in_progress"])
async def test_transitions_not_in_the_table_are_rejected(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City, target: str
) -> None:
    issue_id = (await _report(client, city))["issue"]["id"]
    response = await _move(client, city.admin, issue_id, to_status=target, version=1)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_transition"
    assert error["details"]["from_status"] == "reported"
    assert error["details"]["allowed_transitions"] == [
        {"to_status": "under_review", "requires_reason": False},
        {"to_status": "verified", "requires_reason": False},
        {"to_status": "rejected", "requires_reason": True},
    ]
    assert await _audit(owner_engine, issue_id) == []


async def test_system_only_transitions_are_rejected(client: httpx.AsyncClient, city: City) -> None:
    issue_id = (await _report(client, city))["issue"]["id"]
    verified = await _move(client, city.admin, issue_id, to_status="verified", version=1)
    assert verified.status_code == 200
    for session in (city.admin, city.supervisor, city.operator):
        response = await _move(client, session, issue_id, to_status="assigned", version=2)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_transition"
        assert response.json()["error"]["details"]["allowed_transitions"] == []


async def test_stale_version_is_a_conflict(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    issue_id = (await _report(client, city))["issue"]["id"]
    assert (
        await _move(client, city.operator, issue_id, to_status="under_review", version=1)
    ).status_code == 200

    stale = await _move(client, city.supervisor, issue_id, to_status="verified", version=1)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"
    assert stale.json()["error"]["details"] == {"version": 2}
    assert len(await _audit(owner_engine, issue_id)) == 1


async def test_concurrent_changes_with_one_version_let_one_win(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    issue_id = (await _report(client, city))["issue"]["id"]
    responses = await asyncio.gather(
        _move(client, city.operator, issue_id, to_status="verified", version=1),
        _move(client, city.supervisor, issue_id, to_status="under_review", version=1),
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    async with owner_engine.connect() as conn:
        version, events = (
            await conn.execute(
                text(
                    "SELECT i.version, (SELECT count(*) FROM issue_events e "
                    "WHERE e.issue_id = i.id AND e.type = 'status_changed') "
                    "FROM civic_issues i WHERE i.id = :id"
                ),
                {"id": issue_id},
            )
        ).one()
    assert (version, events) == (2, 1)


async def test_status_changes_respect_scope_and_permissions(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    issue_id = (await _report(client, city))["issue"]["id"]  # ward NE
    south = await login_new(
        client, sms, owner_engine, city, "operator", jurisdiction_id=city.zones["S"]
    )
    other = await make_city(client, sms, owner_engine)
    body = {"to_status": "under_review", "version": 1}

    assert (await _move(client, south, issue_id, **body)).status_code == 404
    assert (await _move(client, other.admin, issue_id, **body)).status_code == 404
    assert (await _move(client, city.citizen, issue_id, **body)).status_code == 403
    response = await client.patch(f"/api/v1/issues/{issue_id}/status", json=body)
    assert response.status_code == 401
    bad = await _move(client, city.operator, issue_id, to_status="lost", version=1)
    assert bad.json()["error"]["code"] == "validation_error"
