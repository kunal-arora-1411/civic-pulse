"""Categories: the public list, admin CRUD (audited) and the validation of
report `details` against category fields."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.errors import ValidationFailed
from app.domains.categories.service import validate_details
from tests.factories import create_category, create_department
from tests.phase1 import POTHOLE_FIELDS, City, make_city

PUBLIC = "/api/v1/categories"
ADMIN = "/api/v1/admin/categories"


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


def _new_category(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": f"c_{uuid.uuid4().hex[:8]}",
        "name_i18n": {"en": "Fallen tree", "hi": "गिरा हुआ पेड़"},
        "icon": "tree-pine",
        "evidence": {"min_photos": 1, "max_photos": 4},
        "fields": [
            {
                "key": "blocking",
                "type": "boolean",
                "required": True,
                "label_i18n": {"en": "Blocking the road?"},
            }
        ],
        "sort_order": 50,
    }
    return {**body, **overrides}


async def test_public_list_shows_active_categories_in_order(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    async with owner_engine.begin() as conn:
        await create_category(conn, city.tenant.id, code="retired", is_active=False)

    anonymous = await client.get(PUBLIC, headers={"X-Tenant": city.tenant.slug})
    assert anonymous.status_code == 200, anonymous.text
    codes = [c["code"] for c in anonymous.json()]
    assert codes == ["waste", "pothole"]  # sort_order 0, then 10; inactive hidden

    pothole = anonymous.json()[1]
    assert pothole["evidence"] == {"min_photos": 1, "max_photos": 3}
    assert pothole["dedup"] == {"radius_m": 30, "window_days": 30}
    assert pothole["fields"][1]["options"][0]["value"] == "small"
    assert pothole["fields"][0]["options"] is None

    signed_in = await client.get(PUBLIC, headers=city.citizen.headers)
    assert signed_in.json() == anonymous.json()


async def test_public_list_needs_a_tenant(client: httpx.AsyncClient, city: City) -> None:
    assert (await client.get(PUBLIC)).status_code == 401
    assert (await client.get(PUBLIC, headers={"X-Tenant": "no-such-city"})).status_code == 404
    mismatch = await client.get(
        PUBLIC, headers={**city.citizen.headers, "X-Tenant": "no-such-city"}
    )
    assert mismatch.json()["error"]["code"] == "tenant_mismatch"


async def test_tenants_never_see_each_others_categories(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    other = await make_city(client, sms, owner_engine)
    created = await client.post(ADMIN, headers=other.admin.headers, json=_new_category())
    assert created.status_code == 201

    mine = await client.get(PUBLIC, headers={"X-Tenant": city.tenant.slug})
    assert created.json()["id"] not in {c["id"] for c in mine.json()}
    patched = await client.patch(
        f"{ADMIN}/{created.json()['id']}", headers=city.admin.headers, json={"icon": "x"}
    )
    assert patched.status_code == 404


async def test_admin_creates_a_category_and_it_is_audited(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    body = _new_category(default_department_id=str(city.roads))
    response = await client.post(ADMIN, headers=city.admin.headers, json=body)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["code"] == body["code"]
    assert created["default_department_id"] == str(city.roads)
    assert created["is_active"] is True
    assert created["description_i18n"] == {}

    duplicate = await client.post(ADMIN, headers=city.admin.headers, json=body)
    assert duplicate.status_code == 409

    async with owner_engine.connect() as conn:
        event = (
            await conn.execute(
                text(
                    "SELECT action, after FROM audit_events WHERE entity_type = 'category' "
                    "AND entity_id = :id"
                ),
                {"id": created["id"]},
            )
        ).one()
    assert event[0] == "category.created"
    assert event[1]["code"] == body["code"]

    listed = await client.get(ADMIN, headers=city.operator.headers, params={"limit": 100})
    assert listed.status_code == 200
    assert created["id"] in {c["id"] for c in listed.json()["items"]}


@pytest.mark.parametrize(
    "overrides",
    [
        {"code": "Has Spaces"},
        {"name_i18n": {"hi": "केवल हिंदी"}},  # English is required
        {"icon": "Not An Icon"},
        {"evidence": {"min_photos": 3, "max_photos": 1}},
        {"evidence": {"min_photos": 0, "max_photos": 11}},
        {"fields": [{"key": "size", "type": "select", "label_i18n": {"en": "Size"}}]},
        {
            "fields": [
                {"key": "a", "type": "text", "label_i18n": {"en": "A"}},
                {"key": "a", "type": "number", "label_i18n": {"en": "A again"}},
            ]
        },
        {
            "fields": [
                {
                    "key": "n",
                    "type": "number",
                    "label_i18n": {"en": "N"},
                    "options": [{"value": "x", "label_i18n": {"en": "X"}}],
                }
            ]
        },
        {"fields": [{"key": "d", "type": "date", "label_i18n": {"en": "D"}}]},
        {"unexpected": True},
    ],
)
async def test_invalid_category_definitions_are_rejected(
    client: httpx.AsyncClient, city: City, overrides: dict[str, Any]
) -> None:
    response = await client.post(ADMIN, headers=city.admin.headers, json=_new_category(**overrides))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"


async def test_references_must_belong_to_the_tenant(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    async with owner_engine.begin() as conn:
        other = await make_city(client, sms, owner_engine)
        foreign_department = await create_department(conn, other.tenant.id, code="PARKS")
    for body in (
        _new_category(default_department_id=str(foreign_department)),
        _new_category(parent_id=str(other.pothole)),
        _new_category(parent_id=str(uuid.uuid4())),
    ):
        response = await client.post(ADMIN, headers=city.admin.headers, json=body)
        assert response.status_code == 422, response.text


async def test_admin_updates_a_category_and_the_change_is_audited(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    url = f"{ADMIN}/{city.pothole}"
    response = await client.patch(
        url,
        headers=city.admin.headers,
        json={
            "is_active": False,
            "fields": POTHOLE_FIELDS[:1],
            "parent_id": str(city.waste),
            "name_i18n": {"en": "Road damage", "hi": "सड़क क्षति"},
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["is_active"] is False
    assert [f["key"] for f in updated["fields"]] == ["road_name"]
    assert updated["parent_id"] == str(city.waste)
    assert updated["evidence"] == {"min_photos": 1, "max_photos": 3}  # untouched

    public = await client.get(PUBLIC, headers={"X-Tenant": city.tenant.slug})
    assert str(city.pothole) not in {c["id"] for c in public.json()}

    async with owner_engine.connect() as conn:
        before, after = (
            await conn.execute(
                text(
                    "SELECT before, after FROM audit_events WHERE action = 'category.updated' "
                    "AND entity_id = :id"
                ),
                {"id": str(city.pothole)},
            )
        ).one()
    assert before["is_active"] is True
    assert after["is_active"] is False

    # Clearing a nullable reference works; nulling a required field doesn't.
    cleared = await client.patch(url, headers=city.admin.headers, json={"parent_id": None})
    assert cleared.json()["parent_id"] is None
    bad = await client.patch(url, headers=city.admin.headers, json={"icon": None})
    assert bad.status_code == 422


async def test_parent_cycles_are_rejected(client: httpx.AsyncClient, city: City) -> None:
    child = await client.patch(
        f"{ADMIN}/{city.waste}", headers=city.admin.headers, json={"parent_id": str(city.pothole)}
    )
    assert child.status_code == 200
    for parent in (city.waste, city.pothole):
        response = await client.patch(
            f"{ADMIN}/{city.pothole}", headers=city.admin.headers, json={"parent_id": str(parent)}
        )
        assert response.status_code == 422, parent


async def test_category_admin_permissions(client: httpx.AsyncClient, city: City) -> None:
    assert (await client.get(ADMIN)).status_code == 401
    assert (await client.get(ADMIN, headers=city.citizen.headers)).status_code == 403
    for session in (city.citizen, city.operator, city.supervisor):
        created = await client.post(ADMIN, headers=session.headers, json=_new_category())
        assert created.status_code == 403
        patched = await client.patch(
            f"{ADMIN}/{city.waste}", headers=session.headers, json={"icon": "trash"}
        )
        assert patched.status_code == 403


# --- details validation ---------------------------------------------------------------

FIELDS: list[dict[str, Any]] = [
    *POTHOLE_FIELDS,
    {"key": "depth_cm", "type": "number", "label_i18n": {"en": "Depth"}},
    {"key": "near_school", "type": "boolean", "label_i18n": {"en": "Near a school"}},
]


def test_valid_details_are_cleaned() -> None:
    cleaned = validate_details(
        FIELDS, {"road_name": "  MG Road ", "size": "large", "depth_cm": 12.5, "near_school": False}
    )
    assert cleaned == {
        "road_name": "MG Road",
        "size": "large",
        "depth_cm": 12.5,
        "near_school": False,
    }
    assert validate_details(FIELDS, {"size": "small", "road_name": "   "}) == {"size": "small"}


@pytest.mark.parametrize(
    ("details", "bad_key"),
    [
        ({}, "size"),  # required
        ({"size": "huge"}, "size"),
        ({"size": "small", "depth_cm": "deep"}, "depth_cm"),
        ({"size": "small", "depth_cm": True}, "depth_cm"),
        ({"size": "small", "near_school": "yes"}, "near_school"),
        ({"size": "small", "road_name": 5}, "road_name"),
        ({"size": "small", "road_name": "x" * 501}, "road_name"),
        ({"size": "small", "colour": "red"}, "colour"),
    ],
)
def test_invalid_details_report_the_field(details: dict[str, Any], bad_key: str) -> None:
    with pytest.raises(ValidationFailed) as caught:
        validate_details(FIELDS, details)
    locs = [e["loc"] for e in caught.value.details["errors"]]
    assert ["body", "details", bad_key] in locs
