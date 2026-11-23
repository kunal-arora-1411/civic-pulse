"""The staff issue queue, the map endpoint and the detail page: filters,
search (Hindi included), sorting, scope and the GeoJSON cap."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import IssueRow, create_issue
from tests.phase1 import NE, NW, SE, SW, City, login_new, make_city

ISSUES = "/api/v1/issues"
GEOJSON = "/api/v1/issues/geojson"


@dataclass
class Queue:
    city: City
    pothole_ne: IssueRow  # reported, MG Road, created 2026-11-11 00:15 IST
    waste_nw: IssueRow  # under_review, Hindi description
    pothole_se: IssueRow  # verified
    waste_sw: IssueRow  # rejected, created 2026-11-10 23:50 IST
    no_ward: IssueRow  # outside every ward


@pytest.fixture
async def queue(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> Queue:
    city = await make_city(client, sms, owner_engine)
    reporter = city.citizen_row.id
    async with owner_engine.begin() as conn:

        async def issue(category: uuid.UUID, point: tuple[float, float], **kw: Any) -> IssueRow:
            return await create_issue(
                conn,
                city.tenant.id,
                category_id=category,
                reporter_id=reporter,
                lng=point[0],
                lat=point[1],
                **kw,
            )

        queue = Queue(
            city=city,
            pothole_ne=await issue(
                city.pothole,
                NE,
                ward_id=city.wards["NE"],
                address_text="MG Road, Shivajinagar",
                description="Large pothole near the bus stop",
                created_at="2026-11-10T18:45:00Z",
            ),
            waste_nw=await issue(
                city.waste,
                NW,
                ward_id=city.wards["NW"],
                status="under_review",
                description="मंदिर के पास कूड़े का ढेर",
                created_at="2026-11-12T10:00:00Z",
            ),
            pothole_se=await issue(
                city.pothole,
                SE,
                ward_id=city.wards["SE"],
                status="verified",
                description="Road caved in after rain",
                created_at="2026-11-13T10:00:00Z",
            ),
            waste_sw=await issue(
                city.waste,
                SW,
                ward_id=city.wards["SW"],
                status="rejected",
                description="Bins not collected",
                created_at="2026-11-10T18:20:00Z",
            ),
            no_ward=await issue(
                city.waste,
                (77.70, 12.80),
                description="Edge case",
                created_at="2026-11-14T10:00:00Z",
            ),
        )
        await conn.execute(
            text(
                "UPDATE civic_issues SET report_count = 5, unique_reporter_count = 3 WHERE id = :id"
            ),
            {"id": queue.pothole_se.id},
        )
    return queue


async def _ids(client: httpx.AsyncClient, session: Any, **params: Any) -> list[str]:
    response = await client.get(ISSUES, headers=session.headers, params=params)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


async def test_list_shape_and_default_order(client: httpx.AsyncClient, queue: Queue) -> None:
    response = await client.get(ISSUES, headers=queue.city.operator.headers)
    page = response.json()
    assert page["total"] == 5
    q = queue
    assert [i["id"] for i in page["items"]] == [
        str(x.id) for x in (q.no_ward, q.pothole_se, q.waste_nw, q.pothole_ne, q.waste_sw)
    ]
    item = next(i for i in page["items"] if i["id"] == str(q.pothole_ne.id))
    assert item == {
        "id": str(q.pothole_ne.id),
        "reference": q.pothole_ne.reference,
        "status": "reported",
        "category": item["category"],
        "location": {"lat": NE[1], "lng": NE[0]},
        "address_text": "MG Road, Shivajinagar",
        "ward": {"id": str(q.city.wards["NE"]), "name": "Ward NE"},
        "report_count": 1,
        "unique_reporter_count": 1,
        "severity": None,
        "priority": None,
        "thumb_url": None,
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
        "version": 1,
    }
    assert item["category"]["code"] == "pothole"


async def test_filters_combine(client: httpx.AsyncClient, queue: Queue) -> None:
    op, q = queue.city.operator, queue
    statuses = await _ids(client, op, status=["reported", "verified"])
    assert set(statuses) == {str(q.pothole_ne.id), str(q.pothole_se.id), str(q.no_ward.id)}
    categories = await _ids(client, op, category_id=str(q.city.waste))
    assert set(categories) == {str(q.waste_nw.id), str(q.waste_sw.id), str(q.no_ward.id)}
    wards = await _ids(client, op, ward_id=[str(q.city.wards["NE"]), str(q.city.wards["SW"])])
    assert set(wards) == {str(q.pothole_ne.id), str(q.waste_sw.id)}
    combined = await _ids(
        client,
        op,
        category_id=str(q.city.waste),
        ward_id=str(q.city.wards["SW"]),
        status="rejected",
    )
    assert combined == [str(q.waste_sw.id)]


async def test_date_bounds_are_whole_days_in_kolkata(
    client: httpx.AsyncClient, queue: Queue
) -> None:
    op, q = queue.city.operator, queue
    # pothole_ne was created at 18:45 UTC on the 10th, which is 00:15 on the
    # 11th in Kolkata; waste_sw at 23:50 on the 10th, Kolkata time.
    on_11th = await _ids(client, op, **{"from": "2026-11-11", "to": "2026-11-11"})
    assert on_11th == [str(q.pothole_ne.id)]
    up_to_10th = await _ids(client, op, to="2026-11-10")
    assert up_to_10th == [str(q.waste_sw.id)]
    from_13th = await _ids(client, op, **{"from": "2026-11-13"})
    assert set(from_13th) == {str(q.pothole_se.id), str(q.no_ward.id)}
    backwards = await client.get(
        ISSUES, headers=op.headers, params={"from": "2026-11-12", "to": "2026-11-11"}
    )
    assert backwards.status_code == 422


async def test_bbox_filter(client: httpx.AsyncClient, queue: Queue) -> None:
    op, q = queue.city.operator, queue
    north_east = await _ids(client, op, bbox="77.60,12.98,77.62,13.00")
    assert north_east == [str(q.pothole_ne.id)]
    for bad in ("1,2,3", "77.7,12.9,77.6,13.0", "a,b,c,d", "77.6,95,77.7,96"):
        response = await client.get(ISSUES, headers=op.headers, params={"bbox": bad})
        assert response.status_code == 422, bad


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("shivajinagar", "pothole_ne"),
        ("pothole bus", "pothole_ne"),
        ("POTH", "pothole_ne"),  # prefix, case-insensitive
        ("कूड़े", "waste_nw"),  # Hindi word
        ("मंदि", "waste_nw"),  # Hindi prefix
        ("caved rain", "pothole_se"),
    ],
)
async def test_full_text_search(
    client: httpx.AsyncClient, queue: Queue, query: str, expected: str
) -> None:
    found = await _ids(client, queue.city.operator, q=query)
    assert found == [str(getattr(queue, expected).id)]


async def test_search_by_issue_and_report_reference(
    client: httpx.AsyncClient, queue: Queue
) -> None:
    op, q = queue.city.operator, queue
    assert await _ids(client, op, q=q.pothole_se.reference) == [str(q.pothole_se.id)]
    assert await _ids(client, op, q=q.waste_nw.report_reference.lower()) == [str(q.waste_nw.id)]
    assert await _ids(client, op, q="nothing like this anywhere") == []
    # Search syntax characters are just text.
    assert await _ids(client, op, q="') & !(:*") == []
    assert await _ids(client, op, q="100%_") == []


async def test_sorting(client: httpx.AsyncClient, queue: Queue) -> None:
    op, q = queue.city.operator, queue
    by_reports = await _ids(client, op, sort="-report_count")
    assert by_reports[0] == str(q.pothole_se.id)
    oldest = await _ids(client, op, sort="created_at")
    assert oldest[0] == str(q.waste_sw.id)
    assert (await client.get(ISSUES, headers=op.headers, params={"sort": "-x"})).status_code == 422
    page = await client.get(ISSUES, headers=op.headers, params={"limit": 2, "offset": 2})
    assert page.json()["total"] == 5
    assert len(page.json()["items"]) == 2


async def test_scope_limits_the_queue_and_hides_the_rest(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, queue: Queue
) -> None:
    q = queue
    south = await login_new(
        client, sms, owner_engine, q.city, "operator", jurisdiction_id=q.city.zones["S"]
    )
    ward_ne = await login_new(
        client, sms, owner_engine, q.city, "operator", jurisdiction_id=q.city.wards["NE"]
    )
    assert set(await _ids(client, south)) == {str(q.pothole_se.id), str(q.waste_sw.id)}
    assert await _ids(client, ward_ne) == [str(q.pothole_ne.id)]

    for hidden in (q.pothole_ne, q.no_ward):  # other zone; no ward at all
        response = await client.get(f"{ISSUES}/{hidden.id}", headers=south.headers)
        assert response.status_code == 404
        assert response.json()["error"]["details"] == {}
    visible = await client.get(f"{ISSUES}/{q.pothole_se.id}", headers=south.headers)
    assert visible.status_code == 200

    geo = await client.get(GEOJSON, headers=south.headers, params={"bbox": "77.5,12.9,77.7,13.1"})
    assert {f["id"] for f in geo.json()["features"]} == {str(q.pothole_se.id), str(q.waste_sw.id)}


async def test_other_tenants_issues_do_not_exist(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, queue: Queue
) -> None:
    other = await make_city(client, sms, owner_engine)
    assert await _ids(client, other.admin) == []
    response = await client.get(f"{ISSUES}/{queue.pothole_ne.id}", headers=other.admin.headers)
    assert response.status_code == 404


async def test_issue_permissions(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, queue: Queue
) -> None:
    field_worker = await login_new(client, sms, owner_engine, queue.city, "field_worker")
    detail = f"{ISSUES}/{queue.pothole_ne.id}"
    for url in (ISSUES, detail, f"{GEOJSON}?bbox=77.5,12.9,77.7,13.1"):
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers=queue.city.citizen.headers)).status_code == 403
        assert (await client.get(url, headers=field_worker.headers)).status_code == 403
        assert (await client.get(url, headers=queue.city.admin.headers)).status_code == 200


async def test_geojson_shape_and_filters(client: httpx.AsyncClient, queue: Queue) -> None:
    op, q = queue.city.operator, queue
    missing = await client.get(GEOJSON, headers=op.headers)
    assert missing.status_code == 422
    response = await client.get(
        GEOJSON, headers=op.headers, params={"bbox": "77.5,12.9,77.7,13.1", "status": "reported"}
    )
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert body["truncated"] is False
    assert body["features"] == [
        {
            "type": "Feature",
            "id": str(q.pothole_ne.id),
            "geometry": {"type": "Point", "coordinates": [NE[0], NE[1]]},
            "properties": {
                "id": str(q.pothole_ne.id),
                "reference": q.pothole_ne.reference,
                "status": "reported",
                "category_code": "pothole",
                "report_count": 1,
            },
        }
    ]


async def test_geojson_is_capped_at_5000(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine
) -> None:
    city = await make_city(client, sms, owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO civic_issues (tenant_id, reference, category_id, status, location, "
                "report_count, unique_reporter_count, ward_id) "
                "SELECT :t, 'CP-98-' || lpad(g::text, 6, '0'), :c, 'reported', "
                "ST_SetSRID(ST_MakePoint(77.551 + (g % 70) * 0.001, 12.931 + (g / 70) * 0.001), "
                "4326), 1, 1, :w FROM generate_series(1, 5001) AS g"
            ),
            {"t": city.tenant.id, "c": city.waste, "w": city.wards["SW"]},
        )
    everything = await client.get(
        GEOJSON, headers=city.operator.headers, params={"bbox": "77.5,12.9,77.7,13.1"}
    )
    body = everything.json()
    assert len(body["features"]) == 5000
    assert body["truncated"] is True

    corner = await client.get(
        GEOJSON, headers=city.operator.headers, params={"bbox": "77.5,12.9,77.555,12.935"}
    )
    assert corner.json()["truncated"] is False
    assert 0 < len(corner.json()["features"]) < 5000


async def test_detail_has_reports_timeline_and_transitions(
    client: httpx.AsyncClient, queue: Queue
) -> None:
    q = queue
    response = await client.get(f"{ISSUES}/{q.pothole_ne.id}", headers=q.city.operator.headers)
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["reference"] == q.pothole_ne.reference
    assert [r["id"] for r in detail["reports"]] == [str(q.pothole_ne.report_id)]
    report = detail["reports"][0]
    assert report["view"] == "staff"
    assert report["reporter"] == {"id": str(q.city.citizen_row.id), "display_name": "Asha Citizen"}
    assert detail["timeline"] == [
        {
            "id": detail["timeline"][0]["id"],
            "at": detail["timeline"][0]["at"],
            "type": "created",
            "from_status": None,
            "to_status": "reported",
            "reason": None,
            "public_note": None,
            "visibility": "public",
            "actor": {"id": str(q.city.citizen_row.id), "display_name": "Asha Citizen"},
        }
    ]
    assert detail["allowed_transitions"] == [
        {"to_status": "under_review", "requires_reason": False},
        {"to_status": "verified", "requires_reason": False},
        {"to_status": "rejected", "requires_reason": True},
    ]


async def test_allowed_transitions_depend_on_role_status_and_scope(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, queue: Queue
) -> None:
    q = queue

    async def allowed(session: Any, issue: IssueRow) -> list[str]:
        response = await client.get(f"{ISSUES}/{issue.id}", headers=session.headers)
        return [t["to_status"] for t in response.json()["allowed_transitions"]]

    # Only supervisors and admins may reopen a rejection.
    assert await allowed(q.city.operator, q.waste_sw) == []
    assert await allowed(q.city.supervisor, q.waste_sw) == ["under_review"]
    # verified -> assigned is system-only.
    assert await allowed(q.city.admin, q.pothole_se) == []

    # A supervisor role scoped to the north doesn't apply in the south.
    mixed = await login_new(
        client,
        sms,
        owner_engine,
        q.city,
        "operator",
        "supervisor",
        jurisdiction_id=q.city.zones["N"],
    )
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE user_roles SET jurisdiction_id = NULL "
                "WHERE user_id = :u AND role = 'operator'"
            ),
            {"u": mixed.user["id"]},
        )
    assert await allowed(mixed, q.waste_sw) == []  # SW: operator only
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE civic_issues SET status = 'rejected' WHERE id = :id"),
            {"id": q.waste_nw.id},
        )
    assert await allowed(mixed, q.waste_nw) == ["under_review"]  # NW: supervisor applies
