"""Matching and priority configuration: defaults, validation, audit, isolation."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from tests.phase1 import City, make_city

MATCHING = "/api/v1/admin/matching-config"
PRIORITY = "/api/v1/admin/priority-config"
REPORT_LIMITS = "/api/v1/admin/report-limits-config"

DEFAULT_MATCHING = {
    "auto_link_enabled": True,
    "weights": {"geo": 0.4, "visual": 0.4, "category": 0.1, "time": 0.1},
    # No visual floor of the tenant's own: matching uses the active model's.
    "thresholds": {"auto": 0.85, "review": 0.6, "visual_min": None},
    "classification_threshold": 0.45,
    "fallback_review_threshold": 0.4,
}
DEFAULT_PRIORITY = {
    "weights": {"severity": 40, "reporters": 20, "age": 15, "recurrence": 15, "near_places": 10},
    "severity_points": {"low": 0.1, "medium": 0.4, "high": 0.75, "critical": 1.0},
    "reporters_saturation": 10,
    "age_saturation_days": 30,
    "recurrence": {"radius_m": 50, "lookback_days": 180, "saturation": 3},
    "bands": {"critical": 80, "high": 60, "medium": 35},
}
DEFAULT_REPORT_LIMITS = {"max_per_hour": 10, "max_per_day": 30}


def _process_report_limits() -> dict[str, int]:
    """The effective default for a tenant with no row of its own: unlike
    the other three keys, this one falls back to REPORT_MAX_PER_HOUR/_DAY
    (the test suite raises these so bulk-report tests aren't throttled),
    not the schema's own literal default."""
    settings = get_settings()
    return {
        "max_per_hour": settings.report_max_per_hour,
        "max_per_day": settings.report_max_per_day,
    }


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def test_defaults_until_a_tenant_sets_its_own(client: httpx.AsyncClient, city: City) -> None:
    matching = await client.get(MATCHING, headers=city.operator.headers)
    assert matching.status_code == 200
    assert matching.json() == DEFAULT_MATCHING
    priority = await client.get(PRIORITY, headers=city.supervisor.headers)
    assert priority.json() == DEFAULT_PRIORITY
    report_limits = await client.get(REPORT_LIMITS, headers=city.supervisor.headers)
    assert report_limits.json() == _process_report_limits()


async def test_replacing_the_matching_config_is_validated_and_audited(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    body = {
        **DEFAULT_MATCHING,
        "auto_link_enabled": False,
        "weights": {"geo": 0.5, "visual": 0.3, "category": 0.1, "time": 0.1},
    }
    saved = await client.put(MATCHING, headers=city.admin.headers, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json() == body
    assert (await client.get(MATCHING, headers=city.operator.headers)).json() == body

    # A field left out goes back to its default.
    reset = await client.put(MATCHING, headers=city.admin.headers, json={"auto_link_enabled": True})
    assert reset.json() == DEFAULT_MATCHING

    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT before, after FROM audit_events WHERE tenant_id = :t "
                    "AND action = 'config.matching_updated' ORDER BY id"
                ),
                {"t": city.tenant.id},
            )
        ).all()
    assert [(r.before["auto_link_enabled"], r.after["auto_link_enabled"]) for r in rows] == [
        (True, False),
        (False, True),
    ]

    # Another tenant still has the defaults.
    other = await make_city(client, sms, owner_engine)
    assert (await client.get(MATCHING, headers=other.operator.headers)).json() == DEFAULT_MATCHING


@pytest.mark.parametrize(
    ("change", "loc"),
    [
        ({"weights": {"geo": 0.5, "visual": 0.5, "category": 0.1, "time": 0.1}}, "weights"),
        ({"weights": {"geo": -0.1, "visual": 0.9, "category": 0.1, "time": 0.1}}, "geo"),
        ({"thresholds": {"auto": 0.6, "review": 0.7, "visual_min": 0.8}}, "thresholds"),
        ({"thresholds": {"auto": 0, "review": 0, "visual_min": 0.8}}, "auto"),
        ({"classification_threshold": 1.2}, "classification_threshold"),
        ({"surprise": True}, "surprise"),
    ],
)
async def test_invalid_matching_configs_are_rejected(
    client: httpx.AsyncClient, city: City, change: dict[str, Any], loc: str
) -> None:
    response = await client.put(
        MATCHING, headers=city.admin.headers, json={**DEFAULT_MATCHING, **change}
    )
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any(loc in [str(part) for part in e["loc"]] for e in error["details"]["errors"])


@pytest.mark.parametrize(
    "change",
    [
        {
            "weights": {
                "severity": 50,
                "reporters": 20,
                "age": 15,
                "recurrence": 15,
                "near_places": 10,
            }
        },
        {"severity_points": {"low": 0.5, "medium": 0.4, "high": 0.75, "critical": 1.0}},
        {"bands": {"critical": 60, "high": 60, "medium": 35}},
        {"reporters_saturation": 0},
        {"recurrence": {"radius_m": 50, "lookback_days": 0, "saturation": 3}},
    ],
)
async def test_invalid_priority_configs_are_rejected(
    client: httpx.AsyncClient, city: City, change: dict[str, Any]
) -> None:
    response = await client.put(
        PRIORITY, headers=city.admin.headers, json={**DEFAULT_PRIORITY, **change}
    )
    assert response.status_code == 422, response.text


async def test_priority_config_round_trips(client: httpx.AsyncClient, city: City) -> None:
    body = {**DEFAULT_PRIORITY, "bands": {"critical": 90, "high": 70, "medium": 40}}
    saved = await client.put(PRIORITY, headers=city.admin.headers, json=body)
    assert saved.status_code == 200, saved.text
    assert (await client.get(PRIORITY, headers=city.admin.headers)).json() == body


async def test_replacing_the_report_limits_config_is_validated_and_audited(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    body = {"max_per_hour": 2, "max_per_day": 5}
    saved = await client.put(REPORT_LIMITS, headers=city.admin.headers, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json() == body
    assert (await client.get(REPORT_LIMITS, headers=city.operator.headers)).json() == body

    # A field left out goes back to its default.
    reset = await client.put(REPORT_LIMITS, headers=city.admin.headers, json={"max_per_hour": 10})
    assert reset.json() == DEFAULT_REPORT_LIMITS

    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT before, after FROM audit_events WHERE tenant_id = :t "
                    "AND action = 'config.report_limits_updated' ORDER BY id"
                ),
                {"t": city.tenant.id},
            )
        ).all()
    assert [(r.before["max_per_hour"], r.after["max_per_hour"]) for r in rows] == [
        (10, 2),
        (2, 10),
    ]

    # Another tenant, with no row of its own, still has the process default.
    other = await make_city(client, sms, owner_engine)
    assert (
        await client.get(REPORT_LIMITS, headers=other.operator.headers)
    ).json() == _process_report_limits()


@pytest.mark.parametrize(
    "change",
    [
        {"max_per_hour": 0},
        {"max_per_day": 0},
        {"surprise": True},
    ],
)
async def test_invalid_report_limits_configs_are_rejected(
    client: httpx.AsyncClient, city: City, change: dict[str, Any]
) -> None:
    response = await client.put(
        REPORT_LIMITS, headers=city.admin.headers, json={**DEFAULT_REPORT_LIMITS, **change}
    )
    assert response.status_code == 422, response.text


async def test_config_permissions(client: httpx.AsyncClient, city: City) -> None:
    for path in (MATCHING, PRIORITY, REPORT_LIMITS):
        assert (await client.get(path, headers=city.citizen.headers)).status_code == 403
        assert (await client.get(path)).status_code == 401
        denied = await client.put(path, headers=city.operator.headers, json={})
        assert denied.status_code == 403
