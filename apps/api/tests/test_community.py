"""Community support ("I face this too"), the reporter's verification view
and public resolution tracking."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

import app.models  # noqa: F401  (configure every mapper before using the service)
from app.domains.config.schemas import PriorityConfig
from app.domains.priority.rules import (
    COMMUNITY_MAX_POINTS,
    PriorityInputs,
    SeverityLevel,
    compute_priority,
)
from tests.helpers import RecordingSms, Session
from tests.phase1 import NE, City, login_new, make_city
from tests.phase2 import ISSUES, issue, report, view
from tests.phase3 import Ops, make_ops, to_pending_verification

PUBLIC = "/api/v1/public"


@pytest.fixture
async def ops(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> Ops:
    return await make_ops(client, sms, owner_engine)


async def _support(
    client: httpx.AsyncClient, session: Session, issue_id: str, method: str = "POST"
) -> httpx.Response:
    return await client.request(method, f"{ISSUES}/{issue_id}/support", headers=session.headers)


def _factors(detail: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["factor"]: f for f in detail["priority"]["factors"]}


async def _reported(client: httpx.AsyncClient, city: City) -> dict[str, Any]:
    return await report(client, city, city.citizen, category=city.waste, description="Garbage pile")


# --- support ---------------------------------------------------------------------------------


async def test_support_counts_once_and_nudges_priority(
    client: httpx.AsyncClient, ops: Ops, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    city = ops.city
    issue_id = (await _reported(client, city))["issue"]["id"]
    neighbour = await login_new(client, sms, owner_engine, city, "citizen")
    before = await issue(client, city.operator, issue_id)
    assert before["support_count"] == 0
    assert "community" not in _factors(before)

    for _ in range(2):  # repeating is harmless
        response = await _support(client, neighbour, issue_id)
        assert response.status_code == 200, response.text
        assert response.json() == {"issue_id": issue_id, "support_count": 1, "supported": True}

    after = await issue(client, city.operator, issue_id)
    assert after["support_count"] == 1
    community = _factors(after)["community"]
    assert community["value"] == 1
    assert community["explanation_key"] == "priority.community"
    assert 0 < community["points"] <= COMMUNITY_MAX_POINTS
    assert after["priority"]["score"] == pytest.approx(
        before["priority"]["score"] + community["points"], abs=0.02
    )
    listed = await client.get(ISSUES, headers=city.operator.headers)
    assert next(i for i in listed.json()["items"] if i["id"] == issue_id)["support_count"] == 1

    state = await client.get(f"{ISSUES}/{issue_id}/support", headers=neighbour.headers)
    assert state.json()["supported"] is True
    removed = await _support(client, neighbour, issue_id, "DELETE")
    assert removed.json() == {"issue_id": issue_id, "support_count": 0, "supported": False}
    assert "community" not in _factors(await issue(client, city.operator, issue_id))


async def test_a_reporter_supporting_is_not_counted_twice_in_priority(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    city = ops.city
    own = await _reported(client, city)
    assert (await _support(client, city.citizen, own["issue"]["id"])).status_code == 200
    mine = await view(client, city.citizen, own["id"])
    assert mine["issue"]["support_count"] == 1
    detail = await issue(client, city.operator, own["issue"]["id"])
    assert "community" not in _factors(detail)


async def test_staff_and_anonymous_cannot_support(client: httpx.AsyncClient, ops: Ops) -> None:
    issue_id = (await _reported(client, ops.city))["issue"]["id"]
    response = await _support(client, ops.city.operator, issue_id)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert (await client.post(f"{ISSUES}/{issue_id}/support")).status_code == 401


async def test_rejected_issues_cannot_be_supported(
    client: httpx.AsyncClient, ops: Ops, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    city = ops.city
    issue_id = (await _reported(client, city))["issue"]["id"]
    response = await client.patch(
        f"{ISSUES}/{issue_id}/status",
        headers=city.operator.headers,
        json={"to_status": "rejected", "reason": "Duplicate of a private complaint", "version": 1},
    )
    assert response.status_code == 200, response.text
    neighbour = await login_new(client, sms, owner_engine, city, "citizen")
    refused = await _support(client, neighbour, issue_id)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "invalid_transition"


async def test_other_tenants_cannot_support_or_see_support(
    client: httpx.AsyncClient, ops: Ops, sms: RecordingSms, owner_engine: AsyncEngine
) -> None:
    issue_id = (await _reported(client, ops.city))["issue"]["id"]
    other = await make_city(client, sms, owner_engine)
    assert (await _support(client, other.citizen, issue_id)).status_code == 404
    assert (
        await client.get(f"{ISSUES}/{issue_id}/support", headers=other.citizen.headers)
    ).status_code == 404
    # And the other tenant's public tracker doesn't know the issue either.
    assert (await client.get(f"{PUBLIC}/{other.tenant.slug}/issues/{issue_id}")).status_code == 404


async def test_issue_supports_has_forced_rls(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'issue_supports'"
                )
            )
        ).one()
    assert row == (True, True)


def test_community_bonus_is_capped_and_never_decides_alone() -> None:
    config = PriorityConfig()
    quiet = PriorityInputs(
        severity=SeverityLevel.LOW, unique_reporters=1, age_days=0, recurrence=0, near_place=False
    )
    base = compute_priority(config, quiet)
    crowd = compute_priority(config, replace(quiet, supporters=100_000))
    assert crowd.score - base.score == pytest.approx(COMMUNITY_MAX_POINTS, abs=0.01)
    assert crowd.band == base.band
    some = compute_priority(config, replace(quiet, supporters=3))
    assert 0 < some.score - base.score < COMMUNITY_MAX_POINTS
    assert math.isclose(sum(f.points for f in some.factors), some.score, abs_tol=0.05)


# --- the reporter's verification view ----------------------------------------------------------


async def test_owner_view_shows_the_closure_round_and_the_answer(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    detail = await to_pending_verification(client, ops)
    own = detail["reports"][0]
    mine = (await view(client, ops.city.citizen, own["id"]))["issue"]
    assert mine["status"] == "pending_verification"
    assert mine["closure"]["state"] == "pending"
    assert len(mine["closure"]["after_photos"]) == 1
    assert mine["closure"]["after_photos"][0]["original_url"] is None
    assert (mine["can_verify"], mine["my_verification"], mine["can_reopen"]) == (
        True,
        None,
        False,
    )

    response = await client.post(
        f"{ISSUES}/{detail['id']}/verification",
        headers=ops.city.citizen.headers,
        json={"outcome": "unresolved", "note": "Still a crater"},
    )
    assert response.status_code == 200, response.text
    answered = response.json()["issue"]
    # One "no" sends the work back, so there is no open round any more.
    assert answered["status"] == "in_progress"
    assert answered["closure"] is None
    assert answered["can_verify"] is False


async def test_owner_view_offers_reopen_once_resolved(client: httpx.AsyncClient, ops: Ops) -> None:
    detail = await to_pending_verification(client, ops)
    approved = await client.post(
        f"{ISSUES}/{detail['id']}/closure/approve",
        headers=ops.city.supervisor.headers,
        json={"version": detail["version"], "public_note": "Patched"},
    )
    assert approved.status_code == 200, approved.text
    own = detail["reports"][0]
    mine = (await view(client, ops.city.citizen, own["id"]))["issue"]
    assert mine["closure"]["state"] == "approved"
    assert (mine["can_verify"], mine["can_reopen"]) == (True, True)
    response = await client.post(
        f"{ISSUES}/{detail['id']}/verification",
        headers=ops.city.citizen.headers,
        json={"outcome": "resolved"},
    )
    assert response.json()["issue"]["my_verification"] == "resolved"
    assert response.json()["issue"]["can_verify"] is False
    again = await client.post(
        f"{ISSUES}/{detail['id']}/verification",
        headers=ops.city.citizen.headers,
        json={"outcome": "resolved"},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_verified"


# --- public tracking ---------------------------------------------------------------------------


async def test_public_list_generalises_locations_and_hides_people(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    city = ops.city
    own = await report(
        client, city, city.citizen, category=city.waste, address_text="12 Private Lane"
    )
    response = await client.get(f"{PUBLIC}/{city.tenant.slug}/issues")
    assert response.status_code == 200, response.text
    assert "public" in response.headers["cache-control"]
    (item,) = response.json()["items"]
    assert item["id"] == own["issue"]["id"]
    assert (item["report_count"], item["support_count"]) == (1, 0)
    exact_lng, exact_lat = NE
    assert (item["location"]["lng"], item["location"]["lat"]) != (exact_lng, exact_lat)
    # Snapped to the cell centre: near, never exact.
    assert abs(item["location"]["lat"] - exact_lat) * 111_320 < 400
    body = response.text
    for secret in ("Private Lane", "Asha", city.citizen_row.phone, "address_text"):
        assert secret not in body

    geo = (await client.get(f"{PUBLIC}/{city.tenant.slug}/issues/geojson")).json()
    (feature,) = geo["features"]
    assert feature["geometry"]["coordinates"] == [item["location"]["lng"], item["location"]["lat"]]

    detail = await client.get(f"{PUBLIC}/{city.tenant.slug}/issues/{item['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["timeline"][0]["type"] == "created"
    assert "Private Lane" not in detail.text


async def test_public_tracker_hides_rejected_issues_and_unknown_tenants(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    city = ops.city
    issue_id = (await _reported(client, city))["issue"]["id"]
    response = await client.patch(
        f"{ISSUES}/{issue_id}/status",
        headers=city.operator.headers,
        json={"to_status": "rejected", "reason": "Spam", "version": 1},
    )
    assert response.status_code == 200, response.text
    listed = (await client.get(f"{PUBLIC}/{city.tenant.slug}/issues")).json()
    assert listed["total"] == 0
    assert (await client.get(f"{PUBLIC}/{city.tenant.slug}/issues/{issue_id}")).status_code == 404
    assert (await client.get(f"{PUBLIC}/no-such-city/issues")).status_code == 404


async def test_scorecard_counts_open_and_resolved_per_ward(
    client: httpx.AsyncClient, ops: Ops
) -> None:
    city = ops.city
    await _reported(client, city)
    detail = await to_pending_verification(client, ops)
    approved = await client.post(
        f"{ISSUES}/{detail['id']}/closure/approve",
        headers=city.supervisor.headers,
        json={"version": detail["version"]},
    )
    assert approved.status_code == 200, approved.text
    response = await client.get(f"{PUBLIC}/{city.tenant.slug}/scorecard")
    assert response.status_code == 200, response.text
    wards = {w["ward"]["name"]: w for w in response.json()["wards"]}
    assert set(wards) == {"Ward NE", "Ward NW", "Ward SE", "Ward SW"}
    ne = wards["Ward NE"]
    assert (ne["open_count"], ne["resolved_count"]) == (1, 1)
    assert ne["median_resolution_days"] is not None
    assert wards["Ward SW"]["median_resolution_days"] is None
