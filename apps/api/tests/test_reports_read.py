"""Reading reports: the citizen's own list, owner vs staff views, scope,
and what never leaks (reporter contact details, internal events)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domains.media.processing import process_asset
from tests import images
from tests.helpers import Session
from tests.phase1 import City, login_new, make_city, uploaded_media_id

REPORTS = "/api/v1/reports"
MINE = "/api/v1/users/me/reports"


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def _submit(client: httpx.AsyncClient, city: City, session: Session, **extra: Any) -> dict:
    body = {
        "category_id": str(city.waste),
        "description": "Overflowing bins outside the market",
        "location": {"lat": 12.99, "lng": 77.61, "source": "gps"},
        "address_text": "Market Road",
        **extra,
    }
    response = await client.post(
        REPORTS, headers={**session.headers, "Idempotency-Key": uuid.uuid4().hex}, json=body
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_my_reports_lists_only_mine_newest_first(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    media_id = await uploaded_media_id(client, city.citizen, images.jpeg())
    first = await _submit(client, city, city.citizen, media_ids=[media_id])
    second = await _submit(client, city, city.citizen)
    neighbour = await login_new(client, sms, owner_engine, city, "citizen")
    await _submit(client, city, neighbour)

    response = await client.get(MINE, headers=city.citizen.headers)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 2
    assert [i["id"] for i in page["items"]] == [second["id"], first["id"]]
    item = page["items"][1]
    assert set(item) == {
        "id",
        "reference",
        "created_at",
        "category",
        "thumb_url",
        "address_text",
        "issue",
    }
    assert item["issue"] == {"reference": first["issue"]["reference"], "status": "reported"}
    assert item["thumb_url"] is None  # still processing

    await process_asset(uuid.UUID(media_id), city.tenant.id)
    page = (await client.get(MINE, headers=city.citizen.headers)).json()
    assert page["items"][1]["thumb_url"].startswith("http://localhost:9000/")


async def test_my_reports_filters_by_issue_status(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    kept = await _submit(client, city, city.citizen)
    rejected = await _submit(client, city, city.citizen)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE civic_issues SET status = 'rejected' WHERE id = :id"),
            {"id": rejected["issue"]["id"]},
        )
    only = await client.get(MINE, headers=city.citizen.headers, params={"status": "rejected"})
    assert [i["id"] for i in only.json()["items"]] == [rejected["id"]]
    both = await client.get(
        MINE, headers=city.citizen.headers, params=[("status", "rejected"), ("status", "reported")]
    )
    assert {i["id"] for i in both.json()["items"]} == {kept["id"], rejected["id"]}
    bad = await client.get(MINE, headers=city.citizen.headers, params={"status": "lost"})
    assert bad.status_code == 422


async def test_owner_sees_the_owner_view(client: httpx.AsyncClient, city: City) -> None:
    media_id = await uploaded_media_id(client, city.citizen, images.jpeg())
    report = await _submit(client, city, city.citizen, media_ids=[media_id])
    response = await client.get(f"{REPORTS}/{report['id']}", headers=city.citizen.headers)
    assert response.status_code == 200
    body = response.json()
    assert body["view"] == "owner"
    assert "reporter" not in body
    assert body["media"][0]["original_url"] is None
    assert body["issue"]["timeline"][0]["type"] == "created"


async def test_staff_view_never_leaks_contact_details(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET email = 'asha@example.com' WHERE id = :id"),
            {"id": city.citizen_row.id},
        )
    media_id = await uploaded_media_id(client, city.citizen, images.jpeg())
    report = await _submit(client, city, city.citizen, media_ids=[media_id])
    url = f"{REPORTS}/{report['id']}"

    for staff in (city.operator, city.supervisor):
        response = await client.get(url, headers=staff.headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["view"] == "staff"
        assert body["reporter"] == {"id": str(city.citizen_row.id), "display_name": "Asha Citizen"}
        assert city.citizen_row.phone not in response.text
        assert "asha@example.com" not in response.text
        assert body["media"][0]["original_url"] is not None  # staff may see the original
        assert body["issue"] == {
            "id": report["issue"]["id"],
            "reference": report["issue"]["reference"],
            "status": "reported",
        }
        assert body["client_created_at"] is None

    # Only user:manage unlocks the contact details.
    admin = (await client.get(url, headers=city.admin.headers)).json()
    assert admin["reporter"]["phone"] == city.citizen_row.phone
    assert admin["reporter"]["email"] == "asha@example.com"


async def test_reports_outside_scope_or_ownership_are_404(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    report = await _submit(client, city, city.citizen)  # in ward NE, zone N
    url = f"{REPORTS}/{report['id']}"

    north = await login_new(
        client, sms, owner_engine, city, "operator", jurisdiction_id=city.zones["N"]
    )
    south = await login_new(
        client, sms, owner_engine, city, "operator", jurisdiction_id=city.zones["S"]
    )
    neighbour = await login_new(client, sms, owner_engine, city, "citizen")
    field_worker = await login_new(client, sms, owner_engine, city, "field_worker")
    other_city = await make_city(client, sms, owner_engine)

    assert (await client.get(url, headers=north.headers)).status_code == 200
    for session in (south, neighbour, field_worker, other_city.admin, other_city.operator):
        response = await client.get(url, headers=session.headers)
        assert response.status_code == 404, response.text
        assert response.json()["error"]["details"] == {}
    assert (
        await client.get(f"{REPORTS}/{uuid.uuid4()}", headers=city.admin.headers)
    ).status_code == 404
    assert (await client.get(url)).status_code == 401


async def test_citizens_never_see_internal_events(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    report = await _submit(client, city, city.citizen)
    issue_id = report["issue"]["id"]
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO issue_events (tenant_id, issue_id, type, reason, public_note, "
                "visibility, actor_id) VALUES (:t, :i, 'note', 'Probably a duplicate of CP-1', "
                "NULL, 'internal', :a)"
            ),
            {"t": city.tenant.id, "i": issue_id, "a": city.operator.user["id"]},
        )
        await conn.execute(
            text(
                "INSERT INTO issue_events (tenant_id, issue_id, type, from_status, to_status, "
                "reason, public_note, visibility, actor_id) VALUES (:t, :i, 'status_changed', "
                "'reported', 'under_review', 'Checking ward records', 'We are looking into it', "
                "'public', :a)"
            ),
            {"t": city.tenant.id, "i": issue_id, "a": city.operator.user["id"]},
        )

    response = await client.get(f"{REPORTS}/{report['id']}", headers=city.citizen.headers)
    timeline = response.json()["issue"]["timeline"]
    assert [e["type"] for e in timeline] == ["created", "status_changed"]
    assert timeline[1]["public_note"] == "We are looking into it"
    assert set(timeline[1]) == {"at", "type", "from_status", "to_status", "public_note"}
    assert "duplicate" not in response.text
    assert "ward records" not in response.text  # reasons are internal
    assert "Omar" not in response.text  # and so are staff identities
