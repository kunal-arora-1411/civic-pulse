"""Helpers for Phase 2 tests: photos of chosen scenes, reports at chosen
spots, and reading back how matching placed them."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from app.ai.fake import make_scene
from tests.helpers import Session
from tests.phase1 import NE, City, uploaded_media_id

REPORTS = "/api/v1/reports"
ISSUES = "/api/v1/issues"
REVIEW = "/api/v1/review-tasks"
METERS_PER_DEGREE_LAT = 111_320.0


def north_of(point: tuple[float, float], meters: float) -> tuple[float, float]:
    """`point` ([lng, lat]) moved `meters` due north."""
    return point[0], point[1] + meters / METERS_PER_DEGREE_LAT


async def scene_photo(
    client: httpx.AsyncClient,
    session: Session,
    seed: int,
    *,
    variant: int = 0,
    label: str | None = None,
) -> str:
    """Upload a photo of scene `seed` (another shot of it with `variant`)."""
    return await uploaded_media_id(client, session, make_scene(seed, variant=variant, label=label))


async def report(
    client: httpx.AsyncClient,
    city: City,
    session: Session,
    *,
    point: tuple[float, float] = NE,
    media_ids: list[str] | None = None,
    category: uuid.UUID | None = None,
    description: str = "Deep pothole in the left lane",
    **extra: Any,
) -> dict[str, Any]:
    """Submit a report and return its owner view as it stands afterwards
    (in tests, matching runs inline right after the request commits)."""
    category = category or city.pothole
    body: dict[str, Any] = {
        "category_id": str(category),
        "description": description,
        "location": {"lat": point[1], "lng": point[0], "source": "gps", "accuracy_m": 5},
        "media_ids": media_ids or [],
        **extra,
    }
    if category == city.pothole:
        body.setdefault("details", {"size": "small"})
    response = await client.post(
        REPORTS, headers={**session.headers, "Idempotency-Key": uuid.uuid4().hex}, json=body
    )
    assert response.status_code == 201, response.text
    return await view(client, session, response.json()["id"])


async def view(client: httpx.AsyncClient, session: Session, report_id: str) -> dict[str, Any]:
    response = await client.get(f"{REPORTS}/{report_id}", headers=session.headers)
    assert response.status_code == 200, response.text
    return response.json()


async def issue(client: httpx.AsyncClient, session: Session, issue_id: str) -> dict[str, Any]:
    response = await client.get(f"{ISSUES}/{issue_id}", headers=session.headers)
    assert response.status_code == 200, response.text
    return response.json()
