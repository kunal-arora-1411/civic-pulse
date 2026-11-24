"""Severity and priority on real issues: the recompute triggers, overrides,
category correction, sorting and filtering (contract C, E and F)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domains.priority.service import recompute_never_computed, recompute_tenant
from tests.helpers import Session
from tests.phase1 import NE, City, login_new, make_city
from tests.phase2 import ISSUES, issue, north_of, report, scene_photo

RULES = {
    "base": "medium",
    "field_rules": [{"field": "size", "equals": "large", "set": "high"}],
    "near_places": [{"kinds": ["school"], "within_m": 150, "raise_by": 1}],
    "report_count_raise": [{"unique_reporters_gte": 3, "raise_by": 1}],
}
SCHOOL = north_of(NE, 100)


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    city = await make_city(client, sms, owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE categories SET severity_rules = CAST(:r AS jsonb) WHERE id = :c"),
            {"r": json.dumps(RULES), "c": city.pothole},
        )
        await conn.execute(
            text(
                "INSERT INTO places_of_interest (tenant_id, kind, name, geom) VALUES "
                "(:t, 'school', 'Synthetic School', ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))"
            ),
            {"t": city.tenant.id, "lng": SCHOOL[0], "lat": SCHOOL[1]},
        )
    return city


async def _patch(
    client: httpx.AsyncClient, session: Session, issue_id: str, what: str, **body: Any
) -> httpx.Response:
    return await client.patch(f"{ISSUES}/{issue_id}/{what}", headers=session.headers, json=body)


def _factors(detail: dict) -> dict[str, dict]:
    return {f["factor"]: f for f in detail["priority"]["factors"]}


async def test_new_issues_get_severity_and_priority_from_the_rules(
    client: httpx.AsyncClient, city: City
) -> None:
    near_school = await report(
        client,
        city,
        city.citizen,
        details={"size": "large"},
        media_ids=[await scene_photo(client, city.citizen, 50)],
    )
    detail = await issue(client, city.operator, near_school["issue"]["id"])
    # medium -> high (size large) -> critical (a school 100 m away)
    assert detail["severity"]["level"] == "critical"
    assert detail["severity"]["source"] == "rule"
    assert "size = large sets high; school" in detail["severity"]["reason"]
    assert detail["severity"]["reason"].endswith("raises 1 -> critical")
    factors = _factors(detail)
    assert factors["severity"]["value"] == "critical"
    assert factors["near_places"]["value"] is True
    assert factors["reporters"]["value"] == 1
    priority = detail["priority"]
    assert priority["score"] == pytest.approx(40 + 20 * 0.2890648 + 10, abs=0.05)
    assert (priority["band"], priority["computed_band"], priority["overridden"]) == (
        "medium",
        "medium",
        False,
    )
    listed = (await client.get(ISSUES, headers=city.operator.headers)).json()["items"][0]
    assert "factors" not in listed["priority"]
    assert listed["priority"]["score"] == priority["score"]

    far = await report(
        client,
        city,
        city.citizen,
        point=north_of(NE, 900),
        media_ids=[await scene_photo(client, city.citizen, 51)],
    )
    assert (await issue(client, city.operator, far["issue"]["id"]))["severity"]["level"] == "medium"


async def test_links_and_status_changes_recompute_priority(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    first = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 52)]
    )
    issue_id = first["issue"]["id"]
    before = await issue(client, city.operator, issue_id)
    for n in (1, 2):
        neighbour = await login_new(client, sms, owner_engine, city, "citizen")
        linked = await report(
            client, city, neighbour, media_ids=[await scene_photo(client, neighbour, 52, variant=n)]
        )
        assert linked["issue"]["id"] == issue_id
    after = await issue(client, city.operator, issue_id)
    assert _factors(after)["reporters"]["value"] == 3
    # Three distinct reporters also raise the severity (rule: 3+ raise 1).
    assert (before["severity"]["level"], after["severity"]["level"]) == ("high", "critical")
    assert after["priority"]["score"] > before["priority"]["score"]

    rejected = await client.patch(
        f"{ISSUES}/{issue_id}/status",
        headers=city.operator.headers,
        json={"to_status": "rejected", "reason": "Private road", "version": after["version"]},
    )
    assert rejected.status_code == 200, rejected.text
    priority = rejected.json()["priority"]
    assert (priority["score"], priority["band"]) == (0, "low")
    assert priority["factors"][0]["explanation_key"] == "priority.inactive"


async def test_severity_override_needs_a_reason_and_can_be_cleared(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    placed = await report(
        client,
        city,
        city.citizen,
        point=north_of(NE, 900),
        media_ids=[await scene_photo(client, city.citizen, 53)],
    )
    detail = await issue(client, city.operator, placed["issue"]["id"])
    issue_id, version = detail["id"], detail["version"]
    assert (
        await _patch(
            client, city.operator, issue_id, "severity", severity="critical", version=version
        )
    ).json()["error"]["code"] == "reason_required"
    stale = await _patch(
        client,
        city.operator,
        issue_id,
        "severity",
        severity="critical",
        reason="Bus route",
        version=version + 1,
    )
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "version_conflict")
    assert (
        await _patch(
            client, city.admin, issue_id, "severity", severity="low", reason="x", version=version
        )
    ).status_code == 403

    response = await _patch(
        client,
        city.operator,
        issue_id,
        "severity",
        severity="critical",
        reason="On the bus route",
        version=version,
    )
    assert response.status_code == 200, response.text
    overridden = response.json()
    assert overridden["severity"] == {
        "level": "critical",
        "source": "override",
        "reason": "On the bus route",
    }
    assert overridden["version"] == version + 1
    assert _factors(overridden)["severity"]["value"] == "critical"  # priority follows
    assert overridden["priority"]["score"] > detail["priority"]["score"]
    event = overridden["timeline"][-1]
    assert (event["type"], event["visibility"], event["reason"]) == (
        "severity_changed",
        "internal",
        "On the bus route",
    )
    citizen_view = (
        await client.get(f"/api/v1/reports/{placed['id']}", headers=city.citizen.headers)
    ).json()
    assert "severity_changed" not in [e["type"] for e in citizen_view["issue"]["timeline"]]

    # The override survives recomputes until it is cleared.
    await recompute_tenant(city.tenant.id)
    assert (await issue(client, city.operator, issue_id))["severity"]["source"] == "override"
    cleared = await _patch(
        client, city.operator, issue_id, "severity", severity=None, version=version + 1
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["severity"]["level"] == "medium"
    assert cleared.json()["severity"]["source"] == "rule"
    async with owner_engine.connect() as conn:
        actions = (
            (
                await conn.execute(
                    text(
                        "SELECT action FROM audit_events WHERE entity_id = :i "
                        "AND action LIKE 'issue.severity%' ORDER BY id"
                    ),
                    {"i": issue_id},
                )
            )
            .scalars()
            .all()
        )
    assert actions == ["issue.severity_overridden", "issue.severity_override_cleared"]


async def test_priority_override_takes_effect_over_the_computed_band(
    client: httpx.AsyncClient, city: City
) -> None:
    placed = await report(
        client,
        city,
        city.citizen,
        details={"size": "large"},
        media_ids=[await scene_photo(client, city.citizen, 54)],
    )
    detail = await issue(client, city.operator, placed["issue"]["id"])
    issue_id, version = detail["id"], detail["version"]
    assert (
        await _patch(
            client, city.operator, issue_id, "priority", band="low", reason="x", version=version
        )
    ).status_code == 403
    assert (
        await _patch(client, city.supervisor, issue_id, "priority", band="low", version=version)
    ).json()["error"]["code"] == "reason_required"

    response = await _patch(
        client,
        city.supervisor,
        issue_id,
        "priority",
        band="low",
        reason="Repair already scheduled",
        version=version,
    )
    assert response.status_code == 200, response.text
    priority = response.json()["priority"]
    assert (priority["band"], priority["computed_band"], priority["overridden"]) == (
        "low",
        "medium",
        True,
    )
    assert priority["override_reason"] == "Repair already scheduled"
    assert priority["score"] == detail["priority"]["score"]
    assert response.json()["timeline"][-1]["type"] == "priority_changed"

    low = (
        await client.get(ISSUES, headers=city.operator.headers, params={"priority_band": "low"})
    ).json()
    assert [i["id"] for i in low["items"]] == [issue_id]
    high = (
        await client.get(
            ISSUES, headers=city.operator.headers, params={"priority_band": ["high", "critical"]}
        )
    ).json()
    assert high["total"] == 0

    cleared = await _patch(
        client, city.supervisor, issue_id, "priority", band=None, version=version + 1
    )
    assert (cleared.json()["priority"]["band"], cleared.json()["priority"]["overridden"]) == (
        "medium",
        False,
    )


async def test_category_correction_relabels_the_reports(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    placed = await report(
        client,
        city,
        city.citizen,
        details={"size": "large"},
        media_ids=[await scene_photo(client, city.citizen, 55)],
    )
    detail = await issue(client, city.operator, placed["issue"]["id"])
    issue_id, version = detail["id"], detail["version"]
    url = f"{ISSUES}/{issue_id}/category"

    same = await client.patch(
        url,
        headers=city.operator.headers,
        json={"category_id": str(city.pothole), "reason": "x", "version": version},
    )
    assert same.status_code == 422
    blank = await client.patch(
        url,
        headers=city.operator.headers,
        json={"category_id": str(city.waste), "version": version},
    )
    assert blank.json()["error"]["code"] == "reason_required"

    response = await client.patch(
        url,
        headers=city.operator.headers,
        json={"category_id": str(city.waste), "reason": "It is rubble", "version": version},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["category"]["code"] == "waste"
    assert body["severity"]["level"] == "medium"  # waste has no rules
    assert body["reports"][0]["category"]["code"] == "waste"
    assert body["reports"][0]["category_source"] == "operator"
    assert body["timeline"][-1]["data"] == {"from": "pothole", "to": "waste"}
    async with owner_engine.connect() as conn:
        audit = (
            await conn.execute(
                text(
                    "SELECT before, after FROM audit_events WHERE entity_id = :i "
                    "AND action = 'issue.category_changed'"
                ),
                {"i": issue_id},
            )
        ).one()
    assert audit.before["report_categories"] == {placed["id"]: str(city.pothole)}
    assert audit.after["reason"] == "It is rubble"


async def test_the_queue_sorts_by_priority_and_filters_by_severity(
    client: httpx.AsyncClient, city: City
) -> None:
    calm = await report(
        client,
        city,
        city.citizen,
        point=north_of(NE, 900),
        media_ids=[await scene_photo(client, city.citizen, 56)],
    )
    urgent = await report(
        client,
        city,
        city.citizen,
        details={"size": "large"},
        media_ids=[await scene_photo(client, city.citizen, 57)],
    )
    rubbish = await report(
        client,
        city,
        city.citizen,
        category=city.waste,
        point=north_of(NE, 1500),
        description="Bins overflowing again",
    )
    order = [
        i["id"] for i in (await client.get(ISSUES, headers=city.operator.headers)).json()["items"]
    ]
    assert order[0] == urgent["issue"]["id"]
    ascending = [
        i["id"]
        for i in (
            await client.get(ISSUES, headers=city.operator.headers, params={"sort": "priority"})
        ).json()["items"]
    ]
    assert ascending[-1] == urgent["issue"]["id"]
    critical = (
        await client.get(ISSUES, headers=city.operator.headers, params={"severity": "critical"})
    ).json()
    assert [i["id"] for i in critical["items"]] == [urgent["issue"]["id"]]
    medium = (
        await client.get(
            ISSUES, headers=city.operator.headers, params={"severity": ["medium", "low"]}
        )
    ).json()
    assert {i["id"] for i in medium["items"]} == {calm["issue"]["id"], rubbish["issue"]["id"]}
    assert (
        await client.get(ISSUES, headers=city.operator.headers, params={"severity": "extreme"})
    ).status_code == 422
    features = (
        await client.get(
            f"{ISSUES}/geojson",
            headers=city.operator.headers,
            params={"bbox": "77.5,12.9,77.7,13.1", "severity": "critical"},
        )
    ).json()["features"]
    assert [(f["id"], f["properties"]["severity"]) for f in features] == [
        (urgent["issue"]["id"], "critical")
    ]


async def test_batch_recomputes_never_touch_version_or_updated_at(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    placed = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 58)]
    )
    issue_id = placed["issue"]["id"]
    async with owner_engine.begin() as conn:
        # As if the issue was created three weeks ago and never computed.
        await conn.execute(
            text(
                "UPDATE civic_issues SET created_at = now() - interval '21 days', "
                "priority_score = NULL, priority_band = NULL, priority_factors = NULL, "
                "priority_computed_at = NULL WHERE id = :i"
            ),
            {"i": issue_id},
        )
    stamp = await issue(client, city.operator, issue_id)
    assert stamp["priority"] is None
    assert await recompute_never_computed() >= 1
    computed = await issue(client, city.operator, issue_id)
    assert _factors(computed)["age"]["value"] == pytest.approx(21, abs=0.1)
    assert (computed["version"], computed["updated_at"]) == (stamp["version"], stamp["updated_at"])

    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE civic_issues SET created_at = now() - interval '40 days' WHERE id = :i"),
            {"i": issue_id},
        )
    assert await recompute_tenant(city.tenant.id) >= 1
    aged = await issue(client, city.operator, issue_id)
    assert _factors(aged)["age"]["normalized"] == 1.0
    assert aged["updated_at"] == stamp["updated_at"]


async def test_changing_the_priority_config_recomputes_every_issue(
    client: httpx.AsyncClient, city: City
) -> None:
    placed = await report(
        client,
        city,
        city.citizen,
        point=north_of(NE, 900),
        media_ids=[await scene_photo(client, city.citizen, 59)],
    )
    before = await issue(client, city.operator, placed["issue"]["id"])
    weights = {"severity": 100, "reporters": 0, "age": 0, "recurrence": 0, "near_places": 0}
    saved = await client.put(
        "/api/v1/admin/priority-config", headers=city.admin.headers, json={"weights": weights}
    )
    assert saved.status_code == 200, saved.text
    after = await issue(client, city.operator, placed["issue"]["id"])
    assert before["priority"]["score"] != after["priority"]["score"]
    assert after["priority"]["score"] == 40.0


async def test_override_and_category_endpoints_respect_scope(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    placed = await report(
        client, city, city.citizen, media_ids=[await scene_photo(client, city.citizen, 60)]
    )
    detail = await issue(client, city.operator, placed["issue"]["id"])
    south = await login_new(
        client, sms, owner_engine, city, "supervisor", jurisdiction_id=city.zones["S"]
    )
    for what, body in (
        ("severity", {"severity": "low", "reason": "x"}),
        ("priority", {"band": "low", "reason": "x"}),
        ("category", {"category_id": str(city.waste), "reason": "x"}),
    ):
        response = await _patch(
            client, south, detail["id"], what, version=detail["version"], **body
        )
        assert response.status_code == 404, (what, response.text)
    other = await make_city(client, sms, owner_engine)
    response = await _patch(
        client, other.supervisor, detail["id"], "priority", band="low", reason="x", version=1
    )
    assert response.status_code == 404
