"""Category AI prompts and severity rules through the admin API."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import InlineJobs
from tests.phase1 import City, make_city

ADMIN = "/api/v1/admin/categories"
RULES = {
    "base": "low",
    "field_rules": [{"field": "size", "equals": "large", "set": "high"}],
    "near_places": [{"kinds": ["school"], "within_m": 100, "raise_by": 1}],
    "report_count_raise": [],
}


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


def _new(**extra: Any) -> dict[str, Any]:
    return {
        "code": "broken_pavement",
        "name_i18n": {"en": "Broken pavement"},
        "icon": "construction",
        "fields": [
            {
                "key": "size",
                "type": "select",
                "label_i18n": {"en": "Size"},
                "options": [{"value": "large", "label_i18n": {"en": "Large"}}],
            }
        ],
        **extra,
    }


async def test_rules_and_prompts_round_trip(
    client: httpx.AsyncClient, city: City, jobs: InlineJobs
) -> None:
    created = await client.post(
        ADMIN,
        headers=city.admin.headers,
        json=_new(severity_rules=RULES, ai_prompts=["  a photo of a broken pavement  "]),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["severity_rules"] == RULES
    assert body["ai_prompts"] == ["a photo of a broken pavement"]

    cleared = await client.patch(
        f"{ADMIN}/{body['id']}",
        headers=city.admin.headers,
        json={"severity_rules": None, "ai_prompts": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert (cleared.json()["severity_rules"], cleared.json()["ai_prompts"]) == (None, None)
    # Changing the rules recomputes the category's issues afterwards.
    assert jobs.called("recompute_priorities") == [(city.tenant.id, uuid.UUID(body["id"]))]

    # Other edits don't.
    jobs.reset()
    await client.patch(f"{ADMIN}/{body['id']}", headers=city.admin.headers, json={"sort_order": 3})
    assert jobs.called("recompute_priorities") == []


async def test_rules_must_name_fields_the_category_has(
    client: httpx.AsyncClient, city: City
) -> None:
    bad = {**RULES, "field_rules": [{"field": "depth", "equals": "knee", "set": "high"}]}
    response = await client.post(ADMIN, headers=city.admin.headers, json=_new(severity_rules=bad))
    assert response.status_code == 422

    created = await client.post(ADMIN, headers=city.admin.headers, json=_new(severity_rules=RULES))
    category_id = created.json()["id"]
    # Removing the field a rule depends on is refused too.
    response = await client.patch(
        f"{ADMIN}/{category_id}", headers=city.admin.headers, json={"fields": []}
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"][0]["loc"] == [
        "body",
        "severity_rules",
        "field_rules",
    ]


@pytest.mark.parametrize(
    "extra",
    [
        {"ai_prompts": []},
        {"ai_prompts": ["no"]},
        {"ai_prompts": [f"prompt number {n}" for n in range(11)]},
        {"severity_rules": {"base": "extreme"}},
    ],
)
async def test_invalid_prompts_and_rules_are_rejected(
    client: httpx.AsyncClient, city: City, extra: dict[str, Any]
) -> None:
    response = await client.post(ADMIN, headers=city.admin.headers, json=_new(**extra))
    assert response.status_code == 422, response.text
