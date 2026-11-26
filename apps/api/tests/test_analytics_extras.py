"""Saved analytics views (FR-077) and service announcements (FR-087)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import RecordingSms
from tests.phase1 import City, make_city

VIEWS = "/api/v1/analytics/views"
ADMIN = "/api/v1/admin/announcements"


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


# --- Saved views -----------------------------------------------------------


async def test_saved_views_round_trip(client: httpx.AsyncClient, city: City) -> None:
    filters = {
        "range": "custom",
        "from": "2026-10-01",
        "to": "2026-10-31",
        "ward_id": str(city.wards["NE"]),
        "status": ["reported", "verified"],
        "interval": "week",
    }
    created = await client.post(
        VIEWS, headers=city.supervisor.headers, json={"name": "NE October", "filters": filters}
    )
    assert created.status_code == 201, created.text
    view = created.json()
    assert view["filters"]["from"] == "2026-10-01"
    assert view["filters"]["ward_id"] == str(city.wards["NE"])
    assert view["filters"]["category_id"] is None
    assert view["is_default"] is False

    renamed = await client.patch(
        f"{VIEWS}/{view['id']}",
        headers=city.supervisor.headers,
        json={"name": "NE, October", "is_default": True},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "NE, October"
    assert renamed.json()["is_default"] is True

    listed = await client.get(VIEWS, headers=city.supervisor.headers)
    assert [v["name"] for v in listed.json()] == ["NE, October"]

    deleted = await client.delete(f"{VIEWS}/{view['id']}", headers=city.supervisor.headers)
    assert deleted.status_code == 204
    assert (await client.get(VIEWS, headers=city.supervisor.headers)).json() == []


async def test_one_default_view_and_unique_names(client: httpx.AsyncClient, city: City) -> None:
    async def save(name: str, **extra: Any) -> httpx.Response:
        return await client.post(
            VIEWS, headers=city.supervisor.headers, json={"name": name, "filters": {}, **extra}
        )

    first = (await save("Weekly", is_default=True)).json()
    second = (await save("Monthly", is_default=True)).json()
    listed = (await client.get(VIEWS, headers=city.supervisor.headers)).json()
    assert [(v["id"], v["is_default"]) for v in listed] == [
        (second["id"], True),
        (first["id"], False),
    ]

    clash = await save("weekly")
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "name_taken"


async def test_saved_view_filters_are_validated(client: httpx.AsyncClient, city: City) -> None:
    for filters in (
        {"range": "7d", "from": "2026-10-01"},
        {"range": "custom", "from": "2026-10-31", "to": "2026-10-01"},
        {"status": ["nonsense"]},
        {"unexpected": 1},
    ):
        response = await client.post(
            VIEWS, headers=city.supervisor.headers, json={"name": "Bad", "filters": filters}
        )
        assert response.status_code == 422, filters


async def test_views_are_private_to_their_owner(client: httpx.AsyncClient, city: City) -> None:
    mine = await client.post(
        VIEWS, headers=city.supervisor.headers, json={"name": "Mine", "filters": {}}
    )
    view_id = mine.json()["id"]
    # The admin also has analytics:read, but sees nothing of the supervisor's.
    assert (await client.get(VIEWS, headers=city.admin.headers)).json() == []
    for method, body in (("PATCH", {"name": "Theirs"}), ("DELETE", None)):
        response = await client.request(
            method, f"{VIEWS}/{view_id}", headers=city.admin.headers, json=body
        )
        assert response.status_code == 404


async def test_views_need_analytics_read(client: httpx.AsyncClient, city: City) -> None:
    response = await client.get(VIEWS, headers=city.citizen.headers)
    assert response.status_code == 403
    response = await client.post(
        VIEWS, headers=city.citizen.headers, json={"name": "x", "filters": {}}
    )
    assert response.status_code == 403


async def test_views_are_isolated_between_tenants(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, city: City
) -> None:
    other = await make_city(client, sms, owner_engine)
    created = await client.post(
        VIEWS, headers=city.supervisor.headers, json={"name": "Here", "filters": {}}
    )
    view_id = created.json()["id"]
    assert (await client.get(VIEWS, headers=other.supervisor.headers)).json() == []
    response = await client.delete(f"{VIEWS}/{view_id}", headers=other.supervisor.headers)
    assert response.status_code == 404


# --- Announcements ---------------------------------------------------------


def _announcement(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "planned_works",
        "title_i18n": {"en": "Road resurfacing", "hi": "सड़क मरम्मत"},
        "body_i18n": {"en": "Main Road is closed overnight."},
        "starts_at": _iso(timedelta(hours=-1)),
        "ends_at": _iso(timedelta(days=2)),
    }
    body.update(overrides)
    return body


async def _create(client: httpx.AsyncClient, city: City, **overrides: Any) -> dict[str, Any]:
    response = await client.post(ADMIN, headers=city.admin.headers, json=_announcement(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


async def _public(client: httpx.AsyncClient, city: City, **params: Any) -> list[dict[str, Any]]:
    response = await client.get(f"/api/v1/public/{city.tenant.slug}/announcements", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_announcement_lifecycle_is_audited(
    client: httpx.AsyncClient, city: City, owner_engine: AsyncEngine
) -> None:
    created = await _create(client, city, ward_id=str(city.wards["NE"]))
    assert created["state"] == "active"
    assert created["ward"]["id"] == str(city.wards["NE"])
    assert created["created_by"]["display_name"] == "Ada Admin"

    updated = await client.patch(
        f"{ADMIN}/{created['id']}",
        headers=city.admin.headers,
        json={"kind": "outage", "ward_id": None},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["kind"] == "outage"
    assert updated.json()["ward"] is None

    withdrawn = await client.post(f"{ADMIN}/{created['id']}/withdraw", headers=city.admin.headers)
    assert withdrawn.status_code == 200
    assert withdrawn.json()["state"] == "withdrawn"
    again = await client.post(f"{ADMIN}/{created['id']}/withdraw", headers=city.admin.headers)
    assert again.json()["withdrawn_at"] == withdrawn.json()["withdrawn_at"]

    edit = await client.patch(
        f"{ADMIN}/{created['id']}", headers=city.admin.headers, json={"kind": "advisory"}
    )
    assert edit.status_code == 409

    async with owner_engine.connect() as conn:
        actions = (
            await conn.execute(
                text("SELECT action FROM audit_events WHERE entity_id = :id ORDER BY occurred_at"),
                {"id": created["id"]},
            )
        ).scalars()
        assert list(actions) == [
            "announcement.create",
            "announcement.update",
            "announcement.withdraw",
        ]


async def test_public_shows_only_active_notices_for_the_area(
    client: httpx.AsyncClient, city: City
) -> None:
    citywide = await _create(client, city)
    ne = await _create(client, city, ward_id=str(city.wards["NE"]))
    await _create(client, city, ward_id=str(city.wards["SW"]))
    pothole = await _create(client, city, category_id=str(city.pothole))
    scheduled = await _create(
        client, city, starts_at=_iso(timedelta(days=1)), ends_at=_iso(timedelta(days=2))
    )
    withdrawn = await _create(client, city)
    await client.post(f"{ADMIN}/{withdrawn['id']}/withdraw", headers=city.admin.headers)

    everything = {a["id"] for a in await _public(client, city)}
    assert scheduled["id"] not in everything
    assert withdrawn["id"] not in everything
    assert len(everything) == 4

    in_ne = {a["id"] for a in await _public(client, city, ward_id=str(city.wards["NE"]))}
    assert in_ne == {citywide["id"], ne["id"], pothole["id"]}

    waste = {a["id"] for a in await _public(client, city, category_id=str(city.waste))}
    assert pothole["id"] not in waste

    state = await client.get(ADMIN, headers=city.admin.headers, params={"state": "scheduled"})
    assert [a["id"] for a in state.json()["items"]] == [scheduled["id"]]
    assert "created_by" not in (await _public(client, city))[0]


async def test_announcement_input_is_validated(client: httpx.AsyncClient, city: City) -> None:
    for overrides in (
        {"ends_at": _iso(timedelta(hours=-2)), "starts_at": _iso(timedelta(hours=-3))},
        {"ends_at": _iso(timedelta(hours=-2))},
        {"ward_id": str(city.zones["N"])},
        {"title_i18n": {"hi": "केवल हिंदी"}},
        {"kind": "party"},
    ):
        response = await client.post(
            ADMIN, headers=city.admin.headers, json=_announcement(**overrides)
        )
        assert response.status_code == 422, overrides


async def test_announcements_need_config_permissions(client: httpx.AsyncClient, city: City) -> None:
    created = await _create(client, city)
    denied = await client.post(ADMIN, headers=city.operator.headers, json=_announcement())
    assert denied.status_code == 403
    denied = await client.post(f"{ADMIN}/{created['id']}/withdraw", headers=city.citizen.headers)
    assert denied.status_code == 403
    assert (await client.get(ADMIN, headers=city.citizen.headers)).status_code == 403


async def test_announcements_are_isolated_between_tenants(
    client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine, city: City
) -> None:
    other = await make_city(client, sms, owner_engine)
    created = await _create(client, city)
    assert (await _public(client, other)) == []
    response = await client.get(f"{ADMIN}/{created['id']}", headers=other.admin.headers)
    assert response.status_code == 404
    listed = await client.get(ADMIN, headers=other.admin.headers)
    assert listed.json()["total"] == 0
    # Another tenant's ward is unknown here.
    response = await client.post(
        ADMIN, headers=other.admin.headers, json=_announcement(ward_id=str(city.wards["NE"]))
    )
    assert response.status_code == 422


async def test_new_tables_force_row_level_security(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('analytics_views', 'announcements') ORDER BY relname"
                )
            )
        ).all()
    assert [tuple(r) for r in rows] == [
        ("analytics_views", True, True),
        ("announcements", True, True),
    ]
