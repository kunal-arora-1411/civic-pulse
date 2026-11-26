"""SLA targets, deadlines and escalation (FR-056, FR-057, AC-09)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domains.sla.service import scan
from tests.helpers import RecordingSms, Session
from tests.phase1 import NE, City, login_new, make_city
from tests.phase2 import ISSUES, issue, north_of, report
from tests.phase3 import assign, make_ops, verified_issue

TARGETS = "/api/v1/admin/sla-targets"


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


def _target(category: uuid.UUID, hours: int, band: str | None = None, escalate: int = 24) -> dict:
    return {
        "category_id": str(category),
        "priority_band": band,
        "resolve_hours": hours,
        "escalate_after_hours": escalate,
    }


async def _put(client: httpx.AsyncClient, who: Session, *items: dict[str, Any]) -> httpx.Response:
    return await client.put(TARGETS, headers=who.headers, json={"items": list(items)})


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def _backdate(owner_engine: AsyncEngine, issue_id: str, hours: int) -> None:
    """Start the issue's clock `hours` ago (the trigger recomputes `due_at`)."""
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE civic_issues SET sla_started_at = now() - make_interval(hours => :h) "
                "WHERE id = :id"
            ),
            {"h": hours, "id": issue_id},
        )


async def _notifications(client: httpx.AsyncClient, who: Session) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/notifications", headers=who.headers)
    assert response.status_code == 200, response.text
    return [n for n in response.json()["items"] if n["kind"] == "sla_breach"]


async def test_admin_sets_targets_and_it_is_audited(client: httpx.AsyncClient, city: City) -> None:
    assert (await client.get(TARGETS, headers=city.admin.headers)).json() == {"items": []}

    response = await _put(
        client, city.admin, _target(city.pothole, 72), _target(city.pothole, 8, "critical")
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [(i["priority_band"], i["resolve_hours"]) for i in items] == [
        (None, 72),
        ("critical", 8),
    ]
    # Supervisors and operators read them (config:read) but cannot change them.
    read = await client.get(TARGETS, headers=city.supervisor.headers)
    assert read.json()["items"] == items

    audit = await client.get(
        "/api/v1/admin/audit-events",
        headers=city.admin.headers,
        params={"action": "config.sla_targets_updated"},
    )
    assert audit.status_code == 200, audit.text
    (event,) = audit.json()["items"]
    assert event["before"] == {"items": []}
    assert len(event["after"]["items"]) == 2


async def test_only_config_managers_change_targets(client: httpx.AsyncClient, city: City) -> None:
    for who in (city.operator, city.supervisor, city.citizen):
        response = await _put(client, who, _target(city.pothole, 72))
        assert response.status_code == 403, response.text
    assert (await client.get(TARGETS, headers=city.citizen.headers)).status_code == 403
    assert (await client.get(TARGETS)).status_code == 401
    assert (await client.get(TARGETS, headers=city.admin.headers)).json() == {"items": []}


async def test_invalid_target_sets_are_refused(client: httpx.AsyncClient, city: City) -> None:
    duplicate = await _put(client, city.admin, _target(city.pothole, 72), _target(city.pothole, 9))
    assert duplicate.status_code == 422
    unknown = await _put(client, city.admin, _target(uuid.uuid4(), 72))
    assert unknown.status_code == 422
    zero = await _put(client, city.admin, _target(city.pothole, 0))
    assert zero.status_code == 422


async def test_other_tenants_neither_see_nor_use_targets(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, city: City
) -> None:
    assert (await _put(client, city.admin, _target(city.pothole, 72))).status_code == 200
    other = await make_city(client, sms, owner_engine)
    assert (await client.get(TARGETS, headers=other.admin.headers)).json() == {"items": []}
    # Another tenant's category id is unknown here, so it can't be targeted.
    response = await _put(client, other.admin, _target(city.pothole, 1))
    assert response.status_code == 422
    async with owner_engine.connect() as conn:
        n = (
            await conn.execute(
                text("SELECT count(*) FROM sla_targets WHERE tenant_id = :t"),
                {"t": city.tenant.id},
            )
        ).scalar_one()
    assert n == 1
    # Issues in the other city have no deadline.
    theirs = await report(client, other, other.citizen, category=other.waste)
    assert (await issue(client, other.operator, theirs["issue"]["id"]))["due_at"] is None


async def test_deadlines_follow_category_band_and_status(
    client: httpx.AsyncClient, city: City
) -> None:
    # No target yet: no deadline.
    own = await report(client, city, city.citizen, category=city.waste)
    issue_id = own["issue"]["id"]
    detail = await issue(client, city.operator, issue_id)
    assert detail["due_at"] is None
    assert detail["sla_state"] == "none"
    assert detail["overdue"] is False

    # Saving targets reschedules open issues.
    await _put(client, city.admin, _target(city.waste, 48), _target(city.waste, 4, "critical"))
    detail = await issue(client, city.operator, issue_id)
    created = _at(detail["created_at"])
    assert _at(detail["due_at"]) - created == pytest.approx(timedelta(hours=48), abs=timedelta(1))
    assert detail["sla_state"] == "on_track"

    # A critical override narrows it.
    response = await client.patch(
        f"{ISSUES}/{issue_id}/priority",
        headers=city.supervisor.headers,
        json={"band": "critical", "reason": "Blocking a school gate", "version": detail["version"]},
    )
    assert response.status_code == 200, response.text
    detail = await issue(client, city.operator, issue_id)
    assert _at(detail["due_at"]) - created == pytest.approx(timedelta(hours=4), abs=timedelta(1))

    # Rejecting freezes the deadline; the issue is no longer counted overdue.
    response = await client.patch(
        f"{ISSUES}/{issue_id}/status",
        headers=city.operator.headers,
        json={"to_status": "rejected", "reason": "Duplicate", "version": detail["version"]},
    )
    assert response.status_code == 200, response.text
    frozen = await issue(client, city.operator, issue_id)
    assert frozen["due_at"] == detail["due_at"]
    assert frozen["sla_state"] == "none"


async def test_overdue_issue_shows_breach_and_escalates(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, city: City
) -> None:
    """AC-09: an overdue issue shows its breach, the department's supervisors
    hear about it, and later the municipal admins."""
    water = uuid.uuid4()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO departments (id, tenant_id, code, name) "
                "VALUES (:d, :t, 'WATER', 'Water')"
            ),
            {"d": water, "t": city.tenant.id},
        )
        await conn.execute(
            text("UPDATE categories SET default_department_id = :d WHERE id = :c"),
            {"d": city.roads, "c": city.waste},
        )
    roads_lead = await login_new(client, sms, owner_engine, city, "supervisor")
    water_lead = await login_new(client, sms, owner_engine, city, "supervisor")
    async with owner_engine.begin() as conn:
        for who, dept in ((roads_lead, city.roads), (water_lead, water)):
            await conn.execute(
                text("UPDATE user_roles SET department_id = :d WHERE user_id = :u"),
                {"d": dept, "u": who.user["id"]},
            )

    await _put(client, city.admin, _target(city.waste, 24, escalate=12))
    late = (await report(client, city, city.citizen, category=city.waste))["issue"]["id"]
    elsewhere = north_of(NE, 900)
    on_time = (await report(client, city, city.citizen, point=elsewhere, category=city.waste))[
        "issue"
    ]["id"]
    await _backdate(owner_engine, late, 30)

    detail = await issue(client, city.operator, late)
    assert detail["overdue"] is True
    assert detail["sla_state"] == "overdue"
    listed = await client.get(ISSUES, headers=city.operator.headers, params={"overdue": "true"})
    assert [i["id"] for i in listed.json()["items"]] == [late]
    rest = await client.get(ISSUES, headers=city.operator.headers, params={"overdue": "false"})
    assert late not in [i["id"] for i in rest.json()["items"]]
    assert on_time in [i["id"] for i in rest.json()["items"]]

    now = datetime.now(UTC)
    # scan() covers every tenant in the test database, so the checks below
    # look at this issue rather than the number of escalations.
    await scan(now)
    await scan(now)  # idempotent: one event and one notification each
    detail = await issue(client, city.operator, late)
    assert detail["escalation_level"] == 1
    assert detail["breached_at"] is not None
    (event,) = [e for e in detail["timeline"] if e["type"] == "sla_breached"]
    assert event["visibility"] == "internal"
    assert event["data"]["level"] == 1

    # The unscoped supervisor and the roads one; not water, not the admin.
    for who, expected in (
        (city.supervisor, 1),
        (roads_lead, 1),
        (water_lead, 0),
        (city.admin, 0),
        (city.citizen, 0),
    ):
        assert len(await _notifications(client, who)) == expected
    (note,) = await _notifications(client, roads_lead)
    assert note["body_key"] == "sla_breach.body_level_1"
    assert note["link"] == f"/admin/issues/{late}"

    # Not yet 12 hours after the breach: nothing more.
    await scan(now + timedelta(hours=11))
    assert (await issue(client, city.operator, late))["escalation_level"] == 1
    await scan(now + timedelta(hours=13))
    detail = await issue(client, city.operator, late)
    assert detail["escalation_level"] == 2
    assert [e["type"] for e in detail["timeline"] if e["type"].startswith("sla_")] == [
        "sla_breached",
        "sla_escalated",
    ]
    (admin_note,) = await _notifications(client, city.admin)
    assert admin_note["body_key"] == "sla_breach.body_level_2"
    await scan(now + timedelta(hours=14))  # level 2 is the last
    assert len(await _notifications(client, city.admin)) == 1

    audit = await client.get(
        "/api/v1/admin/audit-events",
        headers=city.admin.headers,
        params={"action": "issue.sla_escalated"},
    )
    assert audit.json()["total"] == 2

    # Reopening restarts the clock and lifts the breach.
    await _backdate(owner_engine, late, 0)
    detail = await issue(client, city.operator, late)
    assert detail["overdue"] is False
    assert detail["escalation_level"] == 0
    assert detail["breached_at"] is None


async def test_workload_counts_overdue_issues(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    ops = await make_ops(client, sms, owner_engine)
    await _put(client, ops.city.admin, _target(ops.city.pothole, 24))
    detail = await verified_issue(client, ops)
    response = await assign(client, ops, detail, ops.worker)
    assert response.status_code in (200, 201), response.text

    async def overdue() -> int:
        response = await client.get("/api/v1/workload", headers=ops.city.supervisor.headers)
        assert response.status_code == 200, response.text
        (team,) = response.json()["items"]
        return team["overdue"]

    assert await overdue() == 0
    await _backdate(owner_engine, detail["id"], 25)
    assert await overdue() == 1
