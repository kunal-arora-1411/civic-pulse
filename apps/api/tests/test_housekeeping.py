"""The hourly cleanup job (contract §9)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.storage import get_storage
from app.domains.housekeeping.service import cleanup
from app.worker import celery_app
from tests import images
from tests.factories import create_tenant, create_user
from tests.phase1 import make_city, upload, uploaded_media_id

NOW = datetime.now(UTC)
LONG_AGO = NOW - timedelta(days=45)


async def _exists(conn: AsyncConnection, table: str, row_id: Any) -> bool:
    found = await conn.scalar(
        text(f"SELECT count(*) FROM {table} WHERE id = :id"),  # noqa: S608 - constant names
        {"id": row_id},
    )
    return found == 1


async def _session(
    conn: AsyncConnection, tenant_id: uuid.UUID, user_id: uuid.UUID, **times: Any
) -> Any:
    values = {"expires_at": NOW + timedelta(days=1), "revoked_at": None, **times}
    return (
        await conn.execute(
            text(
                "INSERT INTO auth_sessions (tenant_id, user_id, family_id, refresh_token_hash, "
                "expires_at, revoked_at) VALUES (:t, :u, gen_random_uuid(), :h, :e, :r) "
                "RETURNING id"
            ),
            {
                "t": tenant_id,
                "u": user_id,
                "h": uuid.uuid4().hex,
                "e": values["expires_at"],
                "r": values["revoked_at"],
            },
        )
    ).scalar_one()


async def _otp(conn: AsyncConnection, tenant_id: uuid.UUID, expires_at: datetime) -> Any:
    return (
        await conn.execute(
            text(
                "INSERT INTO otp_challenges (tenant_id, phone, code_hash, expires_at) "
                "VALUES (:t, '+918000000000', :h, :e) RETURNING id"
            ),
            {"t": tenant_id, "h": "0" * 64, "e": expires_at},
        )
    ).scalar_one()


async def _idempotency(conn: AsyncConnection, tenant_id: uuid.UUID, expires_at: datetime) -> Any:
    return (
        await conn.execute(
            text(
                "INSERT INTO idempotency_keys (tenant_id, scope, key, request_hash, expires_at) "
                "VALUES (:t, 'test', :k, :h, :e) RETURNING id"
            ),
            {"t": tenant_id, "k": uuid.uuid4().hex, "h": "0" * 64, "e": expires_at},
        )
    ).scalar_one()


async def test_cleanup_removes_only_what_has_expired(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn)
        user = await create_user(conn, tenant.id, "citizen")
        otp_old = await _otp(conn, tenant.id, NOW - timedelta(hours=2))
        otp_recent = await _otp(conn, tenant.id, NOW - timedelta(minutes=10))  # within grace
        expired_long_ago = await _session(conn, tenant.id, user.id, expires_at=LONG_AGO)
        revoked_long_ago = await _session(conn, tenant.id, user.id, revoked_at=LONG_AGO)
        revoked_recently = await _session(
            conn, tenant.id, user.id, revoked_at=NOW - timedelta(days=2)
        )
        live = await _session(conn, tenant.id, user.id)
        key_old = await _idempotency(conn, tenant.id, NOW - timedelta(minutes=1))
        key_live = await _idempotency(conn, tenant.id, NOW + timedelta(hours=23))

    result = await cleanup()
    assert result.otp_challenges >= 1
    assert result.auth_sessions >= 2
    assert result.idempotency_keys >= 1

    async with owner_engine.connect() as conn:
        assert not await _exists(conn, "otp_challenges", otp_old)
        assert await _exists(conn, "otp_challenges", otp_recent)
        assert not await _exists(conn, "auth_sessions", expired_long_ago)
        assert not await _exists(conn, "auth_sessions", revoked_long_ago)
        assert await _exists(conn, "auth_sessions", revoked_recently)
        assert await _exists(conn, "auth_sessions", live)
        assert not await _exists(conn, "idempotency_keys", key_old)
        assert await _exists(conn, "idempotency_keys", key_live)


async def test_cleanup_deletes_abandoned_uploads_and_their_objects(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine
) -> None:
    city = await make_city(client, sms, owner_engine)
    storage = get_storage()

    # Uploaded but never completed, a day and a half ago.
    data = images.jpeg()
    created = await client.post(
        "/api/v1/media/uploads",
        headers=city.citizen.headers,
        json={
            "purpose": "report_evidence",
            "content_type": "image/jpeg",
            "size_bytes": len(data),
            "checksum_sha256": images.sha256(data),
        },
    )
    abandoned = created.json()["upload_id"]
    async with httpx.AsyncClient() as http:
        put = await http.put(
            created.json()["url"], content=data, headers={"Content-Type": "image/jpeg"}
        )
    assert put.status_code == 200

    failed = str(
        (await upload(client, city.citizen, images.jpeg(), "image/png")).request.url
    ).split("/")[-2]
    fresh_pending = (
        await client.post(
            "/api/v1/media/uploads",
            headers=city.citizen.headers,
            json={
                "purpose": "report_evidence",
                "content_type": "image/jpeg",
                "size_bytes": 10,
                "checksum_sha256": "0" * 64,
            },
        )
    ).json()["upload_id"]
    attached = await uploaded_media_id(client, city.citizen, images.jpeg())
    report = await client.post(
        "/api/v1/reports",
        headers={**city.citizen.headers, "Idempotency-Key": uuid.uuid4().hex},
        json={
            "category_id": str(city.waste),
            "description": "Old but attached evidence",
            "location": {"lat": 12.99, "lng": 77.61, "source": "gps"},
            "media_ids": [attached],
        },
    )
    assert report.status_code == 201

    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE media_assets SET created_at = :old WHERE id IN (:a, :f, :t)"),
            {"old": NOW - timedelta(hours=36), "a": abandoned, "f": failed, "t": attached},
        )
        key = await conn.scalar(
            text("SELECT storage_key FROM media_assets WHERE id = :id"), {"id": abandoned}
        )
    assert await storage.head(key) is not None

    result = await cleanup()
    assert result.uploads >= 2

    async with owner_engine.connect() as conn:
        assert not await _exists(conn, "media_assets", abandoned)
        assert not await _exists(conn, "media_assets", failed)
        assert await _exists(conn, "media_assets", fresh_pending)
        assert await _exists(conn, "media_assets", attached)
    assert await storage.head(key) is None


async def test_cleanup_finds_media_stuck_in_processing(
    client: httpx.AsyncClient, sms: Any, owner_engine: AsyncEngine
) -> None:
    city = await make_city(client, sms, owner_engine)
    stuck = await uploaded_media_id(client, city.citizen, images.jpeg())
    recent = await uploaded_media_id(client, city.citizen, images.jpeg())
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE media_assets SET verified_at = :t WHERE id = :id"),
            {"t": NOW - timedelta(hours=1), "id": stuck},
        )
    result = await cleanup()
    stuck_ids = {str(asset_id) for asset_id, _ in result.stuck_processing}
    assert stuck in stuck_ids
    assert recent not in stuck_ids
    assert (uuid.UUID(stuck), city.tenant.id) in result.stuck_processing


def test_cleanup_is_scheduled_hourly() -> None:
    entry = celery_app.conf.beat_schedule["housekeeping-cleanup"]
    assert entry["task"] == "civicpulse.housekeeping.cleanup"
    assert entry["schedule"].minute == {17}
    # What a worker does at startup: import the modules listed in `include`.
    celery_app.loader.import_default_modules()
    assert "civicpulse.housekeeping.cleanup" in celery_app.tasks
    assert "civicpulse.media.process" in celery_app.tasks
