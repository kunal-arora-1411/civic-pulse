"""Analytics endpoints: figures follow docs/metrics.md, filters apply, and
only staff with analytics:read in the same tenant see them."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import RecordingSms, Session
from tests.phase1 import NE, NW, SE, City, login_new, make_city
from tests.phase2 import ISSUES, issue, report

ANALYTICS = "/api/v1/analytics"
ENDPOINTS = (
    "overview",
    "trend",
    "by-status",
    "by-category",
    "by-ward",
    "resolution-times",
    "matching-quality",
    "hotspots",
    "activity",
)


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> City:
    """Three waste issues in three wards: one verified by the operator, one
    resolved two days after it was reported."""
    city = await make_city(client, sms, owner_engine)
    owns = [
        await report(client, city, city.citizen, point=point, category=city.waste)
        for point in (NE, NW, SE)
    ]
    first = await issue(client, city.operator, owns[0]["issue"]["id"])
    moved = await client.patch(
        f"{ISSUES}/{first['id']}/status",
        headers=city.operator.headers,
        json={"to_status": "verified", "version": first["version"]},
    )
    assert moved.status_code == 200, moved.text
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO issue_events (tenant_id, issue_id, type, from_status, to_status,"
                " visibility, created_at) SELECT tenant_id, id, 'status_changed', 'reported',"
                " 'resolved', 'public', created_at + interval '48 hours'"
                " FROM civic_issues WHERE id = :id"
            ),
            {"id": owns[1]["issue"]["id"]},
        )
        await conn.execute(
            text("UPDATE civic_issues SET status = 'resolved' WHERE id = :id"),
            {"id": owns[1]["issue"]["id"]},
        )
    return city


async def _get(client: httpx.AsyncClient, who: Session, path: str, **query: Any) -> dict[str, Any]:
    response = await client.get(f"{ANALYTICS}/{path}", headers=who.headers, params=query)
    assert response.status_code == 200, response.text
    return response.json()


async def test_overview_follows_the_metric_definitions(
    client: httpx.AsyncClient, city: City
) -> None:
    body = await _get(client, city.supervisor, "overview")
    kpis = {k["metric"]: k for k in body["kpis"]}
    assert kpis["reports"]["value"] == 3
    assert kpis["issues"]["value"] == 3
    assert kpis["unique_reporters"]["value"] == 1
    assert kpis["resolution_time"]["value"] == pytest.approx(48, abs=0.01)
    assert kpis["acknowledgement_time"]["unit"] == "hours"
    assert kpis["duplicate_rate"]["value"] == 0
    assert kpis["reports"]["previous"] == 0
    assert len(kpis["reports"]["sparkline"]) == 30
    assert sum(p["value"] for p in kpis["reports"]["sparkline"]) == 3
    assert body["filters"]["period"]["end"] >= body["filters"]["period"]["start"]


async def test_breakdowns_add_up(client: httpx.AsyncClient, city: City) -> None:
    status = await _get(client, city.admin, "by-status")
    assert status["metric"] == "issues_by_status"
    assert {i["status"]: i["count"] for i in status["items"]} == {
        "reported": 1,
        "verified": 1,
        "resolved": 1,
    }
    category = await _get(client, city.admin, "by-category")
    (row,) = category["items"]
    assert row["category"]["code"] == "waste"
    assert row["total"] == 3
    wards = await _get(client, city.admin, "by-ward")
    assert sum(w["issues"] for w in wards["items"]) == 3
    assert {w["ward"]["name"] for w in wards["items"]} == {"Ward NE", "Ward NW", "Ward SE"}
    assert sum(w["resolved"] for w in wards["items"]) == 1

    times = await _get(client, city.admin, "resolution-times")
    assert times["count"] == 1
    assert times["median_hours"] == pytest.approx(48, abs=0.01)
    assert [b["count"] for b in times["bins"] if b["lower_hours"] == 48] == [1]

    trend = await _get(client, city.admin, "trend", interval="week")
    assert sum(p["reports"] for p in trend["points"]) == 3
    quality = await _get(client, city.admin, "matching-quality")
    assert quality["decided_reports"] == 3
    assert quality["duplicate_rate"] == 0
    hot = await _get(client, city.admin, "hotspots", resolution=7)
    assert sum(h["issues"] for h in hot["items"]) == 3
    assert all(77.5 < h["lng"] < 77.7 and 12.9 < h["lat"] < 13.1 for h in hot["items"])
    activity = await _get(client, city.admin, "activity")
    assert sum(c["count"] for c in activity["items"]) == 3


async def test_filters_narrow_every_figure(client: httpx.AsyncClient, city: City) -> None:
    potholes = await _get(client, city.admin, "overview", category_id=str(city.pothole))
    assert {k["metric"]: k["value"] for k in potholes["kpis"]}["reports"] == 0
    one_ward = await _get(client, city.admin, "by-status", ward_id=str(city.wards["NE"]))
    assert one_ward["total"] == 1
    resolved = await _get(client, city.admin, "by-category", status=["resolved", "closed"])
    assert resolved["items"][0]["total"] == 1
    long_ago = await _get(client, city.admin, "trend", **{"from": "2025-01-01", "to": "2025-01-31"})
    assert len(long_ago["points"]) == 31
    assert sum(p["reports"] for p in long_ago["points"]) == 0
    bad = await client.get(
        f"{ANALYTICS}/overview",
        headers=city.admin.headers,
        params={"from": "2026-02-01", "to": "2026-01-01"},
    )
    assert bad.status_code == 422


async def test_analytics_needs_the_permission(client: httpx.AsyncClient, city: City) -> None:
    for path in ENDPOINTS:
        for who in (city.citizen, city.operator):
            response = await client.get(f"{ANALYTICS}/{path}", headers=who.headers)
            assert response.status_code == 403, (path, response.text)
        assert (await client.get(f"{ANALYTICS}/{path}")).status_code == 401


async def test_other_tenants_figures_stay_separate(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, city: City
) -> None:
    other = await make_city(client, sms, owner_engine)
    body = await _get(client, other.admin, "overview")
    assert {k["metric"]: k["value"] for k in body["kpis"]}["reports"] == 0
    assert (await _get(client, other.admin, "hotspots"))["items"] == []
    # And this city's ward filter finds nothing from the other tenant.
    leaked = await _get(client, other.admin, "by-status", ward_id=str(city.wards["NE"]))
    assert leaked["total"] == 0


async def test_figures_follow_the_callers_scope(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, city: City
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE categories SET default_department_id = :d WHERE id = :c"),
            {"d": city.roads, "c": city.pothole},
        )
    north = await login_new(
        client, sms, owner_engine, city, "supervisor", jurisdiction_id=city.zones["N"]
    )
    roads = await login_new(client, sms, owner_engine, city, "supervisor", department_id=city.roads)

    def kpis(body: dict[str, Any]) -> dict[str, Any]:
        return {k["metric"]: k["value"] for k in body["kpis"]}

    # Zone N holds wards NE and NW: two of the three waste issues.
    assert kpis(await _get(client, north, "overview"))["reports"] == 2
    assert (await _get(client, north, "by-status"))["total"] == 2
    wards = await _get(client, north, "by-ward")
    assert {w["ward"]["name"] for w in wards["items"]} == {"Ward NE", "Ward NW"}
    assert sum(h["issues"] for h in (await _get(client, north, "hotspots"))["items"]) == 2
    assert sum(c["count"] for c in (await _get(client, north, "activity"))["items"]) == 2
    # Asking for a ward outside the scope finds nothing rather than leaking it.
    outside = await _get(client, north, "by-status", ward_id=str(city.wards["SE"]))
    assert outside["total"] == 0

    # Roads covers potholes only, and every issue here is waste.
    assert kpis(await _get(client, roads, "overview"))["reports"] == 0
    assert (await _get(client, roads, "by-category"))["items"] == []
    assert (await _get(client, roads, "matching-quality"))["decided_reports"] == 0

    # Unscoped staff still see the whole city.
    assert kpis(await _get(client, city.admin, "overview"))["reports"] == 3
    assert kpis(await _get(client, city.supervisor, "overview"))["reports"] == 3
