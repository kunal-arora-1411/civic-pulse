"""Retention (P6-12): account anonymization and the original-photo purge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.storage import get_storage
from app.domains.auth.cookies import REFRESH_COOKIE
from app.domains.housekeeping.service import cleanup
from app.domains.users.anonymize import PLACEHOLDER_PREFIX
from tests import images
from tests.helpers import RecordingSms, clear_otp_limits, login, request_otp
from tests.phase1 import City, make_city, ready_media_id

ANONYMIZE = "/api/v1/users/me/anonymize"


@pytest.fixture
async def city(client: httpx.AsyncClient, sms: RecordingSms, owner_engine: AsyncEngine) -> City:
    return await make_city(client, sms, owner_engine)


async def _user(engine: AsyncEngine, user_id: Any) -> Any:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT phone, email, display_name, preferences, is_active, anonymized_at "
                    "FROM users WHERE id = :id"
                ),
                {"id": user_id},
            )
        ).one()


async def _asset(engine: AsyncEngine, asset_id: str) -> Any:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT storage_key, display_key, exif, original_purged_at "
                    "FROM media_assets WHERE id = :id"
                ),
                {"id": asset_id},
            )
        ).one()


async def test_citizen_can_anonymize_their_account(
    client: httpx.AsyncClient,
    sms: RecordingSms,
    owner_engine: AsyncEngine,
    city: City,
    redis: Any,
) -> None:
    citizen = city.citizen
    old_phone = city.citizen_row.phone
    media_id = await ready_media_id(client, citizen, images.jpeg())
    assert (await _asset(owner_engine, media_id)).exif is not None

    response = await client.post(ANONYMIZE, headers=citizen.headers)
    assert response.status_code == 204, response.text
    assert REFRESH_COOKIE in response.headers.get("set-cookie", "")

    row = await _user(owner_engine, citizen.user["id"])
    assert row.phone.startswith(PLACEHOLDER_PREFIX)
    assert row.phone != old_phone
    assert (row.email, row.display_name, row.preferences) == (None, None, {})
    assert row.is_active is False
    assert row.anonymized_at is not None
    # The photo stays, without its private metadata.
    assert (await _asset(owner_engine, media_id)).exif is None

    # Every session ended: the old token no longer works.
    me = await client.get("/api/v1/users/me", headers=citizen.headers)
    assert me.status_code == 401
    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": citizen.refresh_token}
    )
    assert refreshed.status_code == 401

    async with owner_engine.connect() as conn:
        audit = (
            await conn.execute(
                text(
                    "SELECT action, before, after FROM audit_events "
                    "WHERE entity_id = :id AND action = 'user.anonymized'"
                ),
                {"id": citizen.user["id"]},
            )
        ).one()
        # The audit trail records the act, not the wiped data.
        assert old_phone not in str(audit)

    # Logging in again with the same number makes a new, empty account.
    await clear_otp_limits(redis, old_phone)
    fresh = await login(client, sms, old_phone, city.tenant.slug)
    assert fresh.user["id"] != citizen.user["id"]
    assert fresh.user["display_name"] is None


async def test_staff_cannot_anonymize_themselves(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City
) -> None:
    response = await client.post(ANONYMIZE, headers=city.operator.headers)
    assert response.status_code == 403
    assert (await _user(owner_engine, city.operator.user["id"])).anonymized_at is None


async def test_anonymizing_needs_a_login(client: httpx.AsyncClient) -> None:
    assert (await client.post(ANONYMIZE)).status_code == 401


async def test_anonymizing_clears_pending_codes_for_the_old_number(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, city: City, redis: Any
) -> None:
    phone = city.citizen_row.phone
    await redis.delete(f"otp:cooldown:{phone}", f"otp:hourly:{phone}")
    assert (await request_otp(client, phone, city.tenant.slug)).status_code == 200
    assert (await client.post(ANONYMIZE, headers=city.citizen.headers)).status_code == 204
    async with owner_engine.connect() as conn:
        left = await conn.scalar(
            text("SELECT count(*) FROM otp_challenges WHERE phone = :p"), {"p": phone}
        )
    assert left == 0


async def test_original_photos_are_purged_after_the_retention_period(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    city: City,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_id = await ready_media_id(client, city.citizen, images.jpeg())
    new_id = await ready_media_id(client, city.citizen, images.jpeg((320, 240)))
    long_ago = datetime.now(UTC) - timedelta(days=100)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE media_assets SET processed_at = :t, "
                "faces_checked_at = coalesce(faces_checked_at, :t) WHERE id = :id"
            ),
            {"t": long_ago, "id": old_id},
        )

    # Off by default: nothing is purged.
    assert settings.media_original_retention_days == 0
    assert (await cleanup()).purged_originals == 0

    monkeypatch.setattr(settings, "media_original_retention_days", 90)
    result = await cleanup()
    assert result.purged_originals >= 1

    old = await _asset(owner_engine, old_id)
    assert old.original_purged_at is not None
    assert old.exif is None
    storage = get_storage()
    assert await storage.head(old.storage_key) is None
    assert await storage.head(old.display_key) is not None  # variants stay

    new = await _asset(owner_engine, new_id)
    assert new.original_purged_at is None
    assert await storage.head(new.storage_key) is not None
