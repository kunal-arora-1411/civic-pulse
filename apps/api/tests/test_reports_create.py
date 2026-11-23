"""POST /reports: the one-transaction submission, idempotency, references
under concurrency, and every validation rule in the contract."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests import images
from tests.factories import create_category
from tests.helpers import Session
from tests.phase1 import NE, OUTSIDE, City, login_new, make_city, upload, uploaded_media_id

REPORTS = "/api/v1/reports"
YY = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%y")


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


def pothole_body(city: City, media_ids: list[str], **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "category_id": str(city.pothole),
        "description": "Large pothole near the bus stop",
        "location": {"lat": NE[1], "lng": NE[0], "accuracy_m": 12.5, "source": "gps"},
        "address_text": "MG Road, Shivajinagar",
        "details": {"road_name": "MG Road", "size": "large"},
        "media_ids": media_ids,
        "client_created_at": "2026-11-24T08:15:00+05:30",
    }
    return {**body, **overrides}


def waste_body(city: City, description: str = "Garbage piling up by the gate") -> dict:
    return {
        "category_id": str(city.waste),
        "description": description,
        "location": {"lat": NE[1], "lng": NE[0], "source": "pin"},
    }


async def submit(
    client: httpx.AsyncClient, session: Session, body: dict, key: str | None = None
) -> httpx.Response:
    headers = {**session.headers, "Idempotency-Key": key or uuid.uuid4().hex}
    return await client.post(REPORTS, headers=headers, json=body)


def _error(response: httpx.Response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code, error
    return error


async def _count(engine: AsyncEngine, sql: str, **params: Any) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar_one()


async def test_report_creates_its_issue_in_one_go(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    media_id = await uploaded_media_id(client, city.citizen, images.jpeg())
    response = await submit(client, city.citizen, pothole_body(city, [media_id]))
    assert response.status_code == 201, response.text
    report = response.json()

    assert report["view"] == "owner"
    assert re.fullmatch(rf"R-{YY}-\d{{6}}", report["reference"])
    assert report["status"] == "accepted"
    assert report["category"] == {
        "id": str(city.pothole),
        "code": "pothole",
        "name_i18n": {"en": "Pothole", "hi": "श्रेणी"},
        "icon": "construction",
    }
    assert report["location"] == {"lat": NE[1], "lng": NE[0], "accuracy_m": 12.5, "source": "gps"}
    assert report["ward"] == {"id": str(city.wards["NE"]), "name": "Ward NE"}
    assert report["details"] == {"road_name": "MG Road", "size": "large"}
    assert [m["id"] for m in report["media"]] == [media_id]
    assert report["media"][0]["original_url"] is None  # never for the citizen

    issue = report["issue"]
    assert re.fullmatch(rf"CP-{YY}-\d{{6}}", issue["reference"])
    assert issue["status"] == "reported"
    assert issue["timeline"] == [
        {
            "at": issue["timeline"][0]["at"],
            "type": "created",
            "from_status": None,
            "to_status": "reported",
            "public_note": None,
        }
    ]

    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT i.report_count, i.unique_reporter_count, i.cover_media_id, i.ward_id, "
                    "i.version, m.report_id, m.position FROM civic_issues i "
                    "JOIN media_assets m ON m.id = i.cover_media_id WHERE i.id = :id"
                ),
                {"id": issue["id"]},
            )
        ).one()
        actions = (
            (
                await conn.execute(
                    text("SELECT action FROM audit_events WHERE entity_id IN (:r, :i) ORDER BY id"),
                    {"r": report["id"], "i": issue["id"]},
                )
            )
            .scalars()
            .all()
        )
    assert row.report_count == 1
    assert row.unique_reporter_count == 1
    assert str(row.cover_media_id) == media_id
    assert row.ward_id == city.wards["NE"]
    assert row.version == 1
    assert str(row.report_id) == report["id"]
    assert row.position == 0
    assert actions == ["report.created", "issue.created"]


async def test_replaying_a_submission_returns_the_same_report(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    body, key = waste_body(city), f"submit-{uuid.uuid4()}"
    first = await submit(client, city.citizen, body, key)
    assert first.status_code == 201
    replay = await submit(client, city.citizen, body, key)
    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["issue"]["reference"] == first.json()["issue"]["reference"]

    reused = await submit(client, city.citizen, {**body, "description": "Different text now"}, key)
    _error(reused, 422, "idempotency_key_reused")
    total = await _count(
        owner_engine, "SELECT count(*) FROM reports WHERE reporter_id = :u", u=city.citizen_row.id
    )
    assert total == 1


async def test_concurrent_replays_create_one_report(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    citizen = await login_new(client, sms, owner_engine, city, "citizen")
    body, key = waste_body(city), f"race-{uuid.uuid4()}"
    responses = await asyncio.gather(*(submit(client, citizen, body, key) for _ in range(5)))
    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 1
    total = await _count(
        owner_engine, "SELECT count(*) FROM reports WHERE reporter_id = :u", u=citizen.user["id"]
    )
    assert total == 1


async def test_idempotency_key_is_required(client: httpx.AsyncClient, city: City) -> None:
    response = await client.post(REPORTS, headers=city.citizen.headers, json=waste_body(city))
    error = _error(response, 422, "validation_error")
    assert error["details"]["errors"][0]["loc"] == ["header", "Idempotency-Key"]


async def test_concurrent_submissions_get_unique_references(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    responses = await asyncio.gather(
        *(submit(client, city.citizen, waste_body(city)) for _ in range(12))
    )
    assert [r.status_code for r in responses] == [201] * 12, [r.text for r in responses]
    report_refs = [r.json()["reference"] for r in responses]
    issue_refs = [r.json()["issue"]["reference"] for r in responses]
    assert len(set(report_refs)) == 12
    assert len(set(issue_refs)) == 12
    # One counter per tenant: the twelve numbers are exactly 1..12.
    assert sorted(int(ref.rsplit("-", 1)[1]) for ref in report_refs) == list(range(1, 13))
    assert (
        await _count(
            owner_engine, "SELECT count(*) FROM civic_issues WHERE tenant_id = :t", t=city.tenant.id
        )
        == 12
    )


async def test_references_are_per_tenant(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    other = await make_city(client, sms, owner_engine)
    mine = await submit(client, city.citizen, waste_body(city))
    theirs = await submit(client, other.citizen, waste_body(other))
    assert mine.json()["reference"] == f"R-{YY}-000001"
    assert theirs.json()["reference"] == f"R-{YY}-000001"


# --- validation ------------------------------------------------------------------------


async def test_point_outside_the_city_is_rejected(client: httpx.AsyncClient, city: City) -> None:
    body = {**waste_body(city), "location": {"lat": OUTSIDE[1], "lng": OUTSIDE[0], "source": "pin"}}
    _error(await submit(client, city.citizen, body), 422, "out_of_jurisdiction")


async def test_photo_count_must_fit_the_category(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    none = await submit(client, city.citizen, pothole_body(city, []))
    error = _error(none, 422, "evidence_required")
    assert error["details"] == {"min_photos": 1, "max_photos": 3, "received": 0}

    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE categories SET max_photos = 1 WHERE id = :id"), {"id": city.pothole}
        )
    two = [await uploaded_media_id(client, city.citizen, images.jpeg()) for _ in range(2)]
    too_many = await submit(client, city.citizen, pothole_body(city, two))
    assert _error(too_many, 422, "evidence_required")["details"]["received"] == 2


async def test_photo_or_long_enough_description_is_required(
    client: httpx.AsyncClient, city: City
) -> None:
    short = await submit(client, city.citizen, waste_body(city, "dirty"))
    assert _error(short, 422, "evidence_required")["details"]["min_description_length"] == 10
    blank = await submit(client, city.citizen, {**waste_body(city), "description": "    "})
    _error(blank, 422, "evidence_required")
    assert (await submit(client, city.citizen, waste_body(city, "0123456789"))).status_code == 201
    with_photo = {
        **waste_body(city, ""),
        "media_ids": [await uploaded_media_id(client, city.citizen, images.jpeg())],
    }
    assert (await submit(client, city.citizen, with_photo)).status_code == 201


async def test_unusable_media_is_rejected(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    stranger = await login_new(client, sms, owner_engine, city, "citizen")
    theirs = await uploaded_media_id(client, stranger, images.jpeg())

    pending = await client.post(
        "/api/v1/media/uploads",
        headers=city.citizen.headers,
        json={
            "purpose": "report_evidence",
            "content_type": "image/jpeg",
            "size_bytes": 100,
            "checksum_sha256": "0" * 64,
        },
    )
    pending_id = pending.json()["upload_id"]
    failed = await upload(client, city.citizen, images.jpeg(), "image/png")
    failed_id = str(failed.request.url).split("/")[-2]

    attached = await uploaded_media_id(client, city.citizen, images.jpeg())
    assert (await submit(client, city.citizen, pothole_body(city, [attached]))).status_code == 201

    cases = {
        theirs: "not_found",
        str(uuid.uuid4()): "not_found",
        pending_id: "not_completed",
        failed_id: "failed",
        attached: "already_attached",
    }
    for media_id, reason in cases.items():
        response = await submit(client, city.citizen, pothole_body(city, [media_id]))
        error = _error(response, 422, "invalid_media")
        assert error["details"] == {"media": [{"id": media_id, "reason": reason}]}


async def test_details_must_match_the_category_fields(
    client: httpx.AsyncClient, city: City
) -> None:
    media_id = await uploaded_media_id(client, city.citizen, images.jpeg())
    for details, key in (
        ({"road_name": "MG Road"}, "size"),
        ({"size": "enormous"}, "size"),
        ({"size": "small", "colour": "red"}, "colour"),
    ):
        response = await submit(
            client, city.citizen, pothole_body(city, [media_id], details=details)
        )
        error = _error(response, 422, "validation_error")
        assert ["body", "details", key] in [e["loc"] for e in error["details"]["errors"]]


@pytest.mark.parametrize(
    "change",
    [
        {"description": "x" * 2001},
        {"location": {"lat": 12.99, "lng": 77.61, "source": "satellite"}},
        {"location": {"lat": 120, "lng": 77.61, "source": "gps"}},
        {"client_created_at": "2026-11-24T08:15:00"},  # no offset
        {"category_id": "not-a-uuid"},
        {"unexpected": 1},
    ],
)
async def test_malformed_bodies_are_rejected(
    client: httpx.AsyncClient, city: City, change: dict
) -> None:
    _error(
        await submit(client, city.citizen, {**waste_body(city), **change}), 422, "validation_error"
    )


async def test_duplicate_media_ids_are_rejected(client: httpx.AsyncClient, city: City) -> None:
    media_id = await uploaded_media_id(client, city.citizen, images.jpeg())
    body = pothole_body(city, [media_id, media_id])
    _error(await submit(client, city.citizen, body), 422, "validation_error")


async def test_category_must_be_active_and_in_this_tenant(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine, city: City
) -> None:
    other = await make_city(client, sms, owner_engine)
    async with owner_engine.begin() as conn:
        retired = await create_category(conn, city.tenant.id, is_active=False)
    for category_id in (retired, other.waste):
        body = {**waste_body(city), "category_id": str(category_id)}
        error = _error(await submit(client, city.citizen, body), 422, "validation_error")
        assert error["details"]["errors"][0]["loc"] == ["body", "category_id"]


async def test_failed_submission_leaves_nothing_and_frees_the_key(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    key = f"retry-{uuid.uuid4()}"
    _error(
        await submit(client, city.citizen, waste_body(city, "short"), key), 422, "evidence_required"
    )
    assert (
        await _count(
            owner_engine, "SELECT count(*) FROM civic_issues WHERE tenant_id = :t", t=city.tenant.id
        )
        == 0
    )
    fixed = await submit(client, city.citizen, waste_body(city), key)
    assert fixed.status_code == 201
    # The failed attempt didn't consume a reference number.
    assert fixed.json()["reference"] == f"R-{YY}-000001"


async def test_report_permissions(client: httpx.AsyncClient, city: City) -> None:
    body = waste_body(city)
    assert (
        await client.post(REPORTS, json=body, headers={"Idempotency-Key": "k"})
    ).status_code == 401
    _error(await submit(client, city.operator, body), 403, "forbidden")
